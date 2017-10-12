import datetime
import json
from functools import wraps
from typing import NamedTuple

import aiohttp
from aiogcd.connector.timestampvalue import TimestampValue
import aioauth_client

from .common import VANILLA_SESSION
from .settings import BaseEnviron
from .sheets import get_sheet_values, get_sheet
from .datastore import DemoUser as User
from .datastore import Roles
from . import datastore
import graphene
from graphene.types.datetime import DateTime
import asyncio
import traceback
import sys
import google.oauth2.credentials


class InsufficientPrivilegesException(Exception):
    """
    Signals that someone has tried to access a ressource that they did not have the right to access.
    """
    @classmethod
    def from_roles(cls, required: Roles, found: Roles):
        return cls(f'Caller does not have permission to do requested action. '
                   f'role {Roles(required)} was needed, but caller has {Roles(found)}')

class InvalidMutationValue(ValueError):
    """
    Signals that a mutation tried to set a new value that was invalid in some way.
    """
    pass


def require_role(role: Roles):
    """
    Produce a decorator that checks a that a resolver was called with sufficient privileges
    :param role:
    :return:
    """
    def decorator(resolver):
        @wraps(resolver)
        def wrapper(root, args, context, info):
            caller: Caller = context['caller']
            if caller.entity.role < role:
                raise InsufficientPrivilegesException(role, caller.entity.role)
            return resolver(root, args, context, info)
        return wrapper
    return decorator


class Caller(NamedTuple):
    """
    Object to hold information about a user that has made a request to the /graphql endpoint
    """
    # credentials: google.oauth2.credentials.Credentials
    gid: str                        # Google ID
    entity: User                    # User entity from own DB
    session: aiohttp.ClientSession  # session that is authorized with user token


class Profile(graphene.ObjectType):
    name = graphene.String()
    email = graphene.String()
    role = graphene.Int()
    gid = graphene.String()

    @classmethod
    def from_entity(cls, entity):
        return cls(**dict((field, getattr(entity, field))
                   for field in cls._meta.local_fields if hasattr(entity, field)))

async def user_has_email(user: User, email):
    """
    Check whether provided email is registered with the google user that has authorized the session
    :param session:
    :param email:
    :return:
    """
    async with user.authorized_session as session:
        async with session.get(f"GET https://www.googleapis.com/plus/v1/people/me") as resp:
            data = await resp.json()
            return email in data['emails']


class MyOAuthClient(aioauth_client.OAuth2Client):
    def request(self, method, url, params=None, headers=None, timeout=10, loop=None, **aio_kwargs):
        """Request OAuth2 resource."""
        url = self._get_url(url)
        params = params or {}

        if self.access_token:
            params[self.access_token_key] = self.access_token

        headers = headers or {
            'Accept': 'application/json',
            'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        }
        return VANILLA_SESSION.request(method, url, params=params, headers=headers, **aio_kwargs)



class TokenRefresh(graphene.Mutation):
    class Input:
        code = graphene.String(required=True)

    user = graphene.Field(lambda: Profile)
    ok = graphene.Boolean()

    @staticmethod
    @require_role(Roles.UNREGISTERED)
    async def mutate(root, args, context, info):
        print(args['code'])
        with open(BaseEnviron.WEBAPP_SECRETS_PATH) as fp:
            secrets = json.load(fp)
            client_id = secrets['web']['client_id']
            client_secret = secrets['web']['client_secret']
            token_uri = secrets['web']['token_uri']
            auth_uri = secrets['web']['auth_uri']

        client = MyOAuthClient(client_id=client_id, client_secret=client_secret,
                                    authorize_url=auth_uri, access_token_url=token_uri)
        try:
            token, data = await client.get_access_token(args['code'], redirect_uri='http://localhost:8080')
        except Exception as exc:
            traceback.print_exception(*sys.exc_info())
            raise

        caller: Caller = context['caller']
        caller.entity.refresh_token = data['refresh_token']
        caller.entity.token = token
        await caller.entity.put()
        return TokenRefresh(user=Profile.from_entity(caller.entity), ok=True)


class ProfileUpdate(graphene.Mutation):
    """
    Mutation used for changing user profile information
    """
    class Input:
        gid = graphene.String(required=True)
        email = graphene.String()
        name = graphene.String()
        role = graphene.Int()

    ok = graphene.Boolean()
    user = graphene.Field(lambda: Profile)

    @staticmethod
    @require_role(Roles.UNREGISTERED)
    async def mutate(root, args, context, info):
        caller: Caller = context['caller']

        # We can only mutate existing entities
        user: User = await User.filter(User.gid == args['gid']).get_entity()
        if user is None:
            raise Exception(f'No user found with gid {args["gid"]}')

        # edit own user, or be admin
        if caller.gid != user.gid and caller.entity.role < Roles.ADMIN:
            raise InsufficientPrivilegesException('Only admin can update other peoples profiles')

        # specific checks on the fields if they are changed
        changes = False
        for field, new_value in args.items():
            if getattr(user, field) != new_value:

                # emails should always be an emails connected to users google account
                if field == 'email':
                    if not await user_has_email(user, new_value):
                        raise InvalidMutationValue(f'Cannot set new email to {new_value} since it is not '
                                                   f'registered to users google account.')

                # id should NEVER be changed
                elif field == 'id':
                    raise InvalidMutationValue(f'Cannot change the google ID of a user profile.')

                # changing roles is for admins
                elif field == 'role':
                    if caller.entity.role < Roles.ADMIN:
                        raise InsufficientPrivilegesException('Only admin can change user roles')

                # set new value and note that a change ocurred
                setattr(user, field, new_value)
                changes = True

        # do not bother updating entity if no data changed
        if changes:
            await user.put()
        ok = True

        return ProfileUpdate(user=Profile.from_entity(user), ok=ok)


class GoogleSheet(graphene.ObjectType):
    gid = graphene.Int()
    parent_id = graphene.String()
    name = graphene.String()
    link = graphene.String()

    def resolve_link(self, args: dict, context, info):
        return f'https://docs.google.com/spreadsheets/d/{self.parent_id}/edit#gid={self.gid}'

    async def resolve_name(self, args: dict, context, info):
        d = await get_sheet(self.parent_id, context['caller'].session, fields=[{'sheets': {'properties': ['sheetId', 'title']}}])
        for sheet in d['sheets']:
            if sheet['properties']['sheetId'] == self.gid:
                return sheet['properties']['title']


class GoogleSpreadsheet(graphene.ObjectType):
    id = graphene.String()
    sheets = graphene.List(GoogleSheet)
    name = graphene.String()
    link = graphene.String()

    def resolve_link(self, args: dict, context, info):
        return f'https://docs.google.com/spreadsheets/d/{self.id}/edit'

    async def resolve_name(self, args: dict, context, info):
        return (await get_sheet(self.id, context['caller'].session, fields=[{'properties': 'title'}]))['properties']['title']

    async def resolve_sheets(self, args: dict, context, info):
        d = await get_sheet(self.id, context['caller'].session, fields=[{'sheets': {'properties': 'sheetId'}}])
        return [GoogleSheet(gid=sheet['properties']['sheetId'], parent_id=self.id) for sheet in d['sheets']]


# Query and Mutation endpoints
class GrapheneQuery(graphene.ObjectType):
    current_profile = graphene.Field(Profile)

    def resolve_current_profile(self, args, context, info):
        user_entity = context['caller'].entity
        return Profile.from_entity(user_entity)

class GrapheneMutation(graphene.ObjectType):
    profile_update = ProfileUpdate.Field()
    token_refresh = TokenRefresh.Field()


# 'compile' in to schema
GRAPHENE_SCHEMA = graphene.Schema(query=GrapheneQuery, mutation=GrapheneMutation)
