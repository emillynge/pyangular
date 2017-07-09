import asyncio
import re
from typing import NamedTuple, Optional, Awaitable
import aiohttp
import google.auth.transport.requests
import google.oauth2.credentials
import graphql
import logging
import uvloop
import aiogcd.connector.connector
from aiohttp import web
from google.auth._default import _load_credentials_from_file
from graphql.execution.executors.asyncio import AsyncioExecutor
from graphql.error.format_error import format_error
import json
from .datastore import GcdConnector, Roles
from .datastore import DemoUser as User
from .googleauth import ServiceAccount, verify_oauth2_token_simple
from .settings import BaseEnviron
from .graph import GRAPHENE_SCHEMA, Caller

request = google.auth.transport.requests.Request()

loop = uvloop.new_event_loop()
asyncio.set_event_loop(loop)

ROOT_ACCOUNT = ServiceAccount(*_load_credentials_from_file(BaseEnviron.SERVICE_ACCOUNT_SECRETS_PATH))
with open(BaseEnviron.WEBAPP_SECRETS_PATH) as fp:
    s = fp.read()
    BaseEnviron.WEBAPP_CLIENT_ID = json.loads(s)['web']['client_id']

(GCD_CREDENTIALS,) = ROOT_ACCOUNT.sub_credentials(aiogcd.connector.connector.DEFAULT_SCOPES)
VANILLA_SESSION = aiohttp.ClientSession()
ANONYMOUS = User(name="anonymous", gid="", role=Roles.SIGNED_OUT, token="", project_id=ROOT_ACCOUNT.project_name,
                 email='anon@ymo.us')
GCD_CONNECTOR = GcdConnector(ROOT_ACCOUNT.project_name, GCD_CREDENTIALS)
User.set_connector(GCD_CONNECTOR)
app = web.Application()


def add_routes(*routes, GET=True, POST=False):
    def decorator(fun):
        for route in routes:
            if GET:
                app.router.add_get(route, fun)

            if POST:
                app.router.add_post(route, fun)
        return fun

    return decorator


@add_routes('/', '/user')
def index(*args):
    INDEX_BODY = BaseEnviron.ANGULAR_BUNDLE_PATH.joinpath('index.html').read_text()
    INDEX_BODY = re.sub('"(\w+\.bundle.js)"', '"app/\g<1>"', INDEX_BODY).encode()
    return web.Response(body=INDEX_BODY,
                        content_type='text/html')


app.router.add_static(
    '/app/',
    path=str(BaseEnviron.ANGULAR_BUNDLE_PATH),
    name='static')

app.router.add_static(
    '/assets/',
    path=str(BaseEnviron.ANGULAR_BUNDLE_PATH.joinpath('assets')),
    name='assets')


class GraphQLQuery(NamedTuple):
    query: str
    variables: Optional[dict]
    operation_name: Optional[str]


async def extract_graphql_query(request: web.Request) -> GraphQLQuery:
    if request.method == 'GET':
        return GraphQLQuery(request.rel_url.query['query'], None, None)

    if request.headers['Content-Type'] == 'application/graphql':
        return GraphQLQuery(await request.text(), None, None)

    data = await request.json()
    return GraphQLQuery(
        data['query'],
        data.get('variables'),
        data.get('operationName'))


def _ensure_future(coro_or_result):
    if not isinstance(coro_or_result, Awaitable):
        fut = asyncio.Future()
        fut.set_result(coro_or_result)
        return fut
    return coro_or_result


@add_routes('/graphql', GET=True, POST=True)
async def graphql_handler(request: web.Request) -> web.Response:
    # parse the aiohttp Request to get a GraphqlQuery object
    query: GraphQLQuery = await extract_graphql_query(request)

    # populate context with caller info
    try:
        # extract and verify credentials and user info
        try:
            gid, access_token = request.headers.get('authorization').split(':', 1)
            # base64.b64decode(access_token)
        except ValueError:
            msg = f"Malformed auth: {request.headers.get('authorization')}"
            logging.warning(msg)
            return web.Response(status=403, text=msg, reason=msg)

        try:
            user_entity, (token_uid, token_email) = await asyncio.gather(
                User.filter(User.gid == gid).get_entity(),
                verify_oauth2_token_simple(access_token, VANILLA_SESSION, BaseEnviron.WEBAPP_CLIENT_ID),
            )
            if gid != token_uid:
                msg = f'Token was not issued for the calling user'
                logging.warning(msg)
                return web.Response(status=403, text=msg, reason=msg)

        except ValueError as exc:  # verification will raise ValueError if it fails
            # raise
            msg = f'Token could not be verified: "{exc.args[0]}"'
            logging.warning(msg)
            return web.Response(status=403, text=msg, reason=msg)

        # make authorized session and credentials object
        # credentials = google.oauth2.credentials.Credentials(token)
        session = aiohttp.ClientSession(headers={
            'Authorization': f'Bearer {access_token}',
            'Referrer': str(request.url)})

        # populate user_entity if needed
        if user_entity is None:
            user_entity = User(gid=gid, token=access_token, role=Roles.UNREGISTERED)
            await user_entity.put()
        elif user_entity.token != access_token:
            user_entity.token = access_token
            await user_entity.put()

        caller = Caller(gid, user_entity, session)
    except AttributeError as exc:  # authorization is None -> no auth
        raise
        caller = Caller(None, ANONYMOUS, VANILLA_SESSION)

    coro = graphql.graphql(
        GRAPHENE_SCHEMA,
        query.query,
        context_value={'caller': caller},
        executor=AsyncioExecutor(loop=request.app.loop),
        variable_values=query.variables,
        operation_name=query.operation_name,
        return_promise=True)

    coro = _ensure_future(coro)

    # close session after use if it is not the vanilla
    if caller.session is not VANILLA_SESSION:
        async with caller.session:
            result = await coro
    else:
        result = await coro

    if result.errors:
        status = 400
        resp = dict(errors=[format_error(err) for err in result.errors])
        for err in result.errors:
            logging.warning(f'Query "{query}" resulted in error:\n\t{err}')
    else:
        status = 200
        resp = dict(data=result.data)

    return web.json_response(resp, status=status)


class InvalidCredentialsError(Exception): pass


class ExpiredCredentialsError(Exception): pass


async def startup(_app):
    await GCD_CONNECTOR.__aenter__()


async def cleanup(_app):
    await GCD_CONNECTOR.__aexit__()
    VANILLA_SESSION.close()


def run_server():
    app.on_cleanup.append(cleanup)
    app.on_startup.append(startup)
    web.run_app(app, host=BaseEnviron.SERVER_DOMAIN, port=BaseEnviron.SERVER_PORT)
