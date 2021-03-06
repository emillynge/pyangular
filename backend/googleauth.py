# Copyright 2016 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Google ID Token helpers."""
import asyncio
import json
import urllib.parse
from datetime import timedelta, datetime
from http import HTTPStatus
from typing import NamedTuple, Awaitable
import time

import aiohttp
import uvloop
from aiohttp import ClientSession, ClientResponse
from google.auth import exceptions, _helpers
from google.auth import jwt
from google.oauth2 import service_account
from google.oauth2._client import _JWT_GRANT_TYPE, _URLENCODED_CONTENT_TYPE, _handle_error_response, _parse_expiry, \
    _REFRESH_GRANT_TYPE
from google.oauth2.service_account import Credentials as _Credentials, _DEFAULT_TOKEN_LIFETIME_SECS

# The URL that provides public certificates for verifying ID tokens issued
# by Google's OAuth 2.0 authorization server.


_GOOGLE_OAUTH2_CERTS_URL = 'https://www.googleapis.com/oauth2/v1/certs'

# The URL that provides public certificates for verifying ID tokens issued
# by Firebase and the Google APIs infrastructure
_GOOGLE_APIS_CERTS_URL = (
    'https://www.googleapis.com/robot/v1/metadata/x509'
    '/securetoken@system.gserviceaccount.com')

CERTS_CACHE_TTL = timedelta(seconds=300)
CERTS_CACHE = dict()


async def _fetch_certs(session: ClientSession, certs_url):
    """Fetches certificates.
    If non-expired certificates exists in CERT_CACHE these are returned.
    Otherwise new certs are fetched from certs_url and placed into cache.

    Google-style cerificate endpoints return JSON in the format of
    ``{'key id': 'x509 certificate'}``.

    Args:
        session (aiohhtp.Session): The object used to make
            HTTP requests.
        certs_url (str): The certificate endpoint URL.

    Returns:
        Mapping[str, str]: A mapping of public key ID to x.509 certificate
            data.
    """
    try:
        certs, expiry = CERTS_CACHE[certs_url]
    except KeyError:
        pass
    else:
        if datetime.now() > expiry:
            del CERTS_CACHE[certs_url]
        else:
            return certs

    async with session.get(certs_url) as response:

        # data = await resp.json()

        if response.status != HTTPStatus.OK:
            raise exceptions.TransportError(
                'Could not fetch certificates at {}'.format(certs_url))
        certs = await response.json()
        CERTS_CACHE[certs_url] = (certs, datetime.now() + CERTS_CACHE_TTL)
        return certs


async def verify_token(id_token, session: ClientSession, audience=None,
                       certs_url=_GOOGLE_OAUTH2_CERTS_URL):
    """Verifies an ID token and returns the decoded token.

    Args:
        id_token (Union[str, bytes]): The encoded token.
        session (aiohhtp.Session): The object used to make
            HTTP requests.
        audience (str): The audience that this token is intended for. If None
            then the audience is not verified.
        certs_url (str): The URL that specifies the certificates to use to
            verify the token. This URL should return JSON in the format of
            ``{'key id': 'x509 certificate'}``.

    Returns:
        Mapping[str, Any]: The decoded token.
    """
    certs = await _fetch_certs(session, certs_url)

    return jwt.decode(id_token, certs=certs, audience=audience)


def verify_oauth2_token(id_token, session: ClientSession, audience=None):
    """Verifies an ID Token issued by Google's OAuth 2.0 authorization server.

    Args:
        id_token (Union[str, bytes]): The encoded token.
        session (aiohhtp.Session): The object used to make
            HTTP requests.
        audience (str): The audience that this token is intended for. This is
            typically your application's OAuth 2.0 client ID. If None then the
            audience is not verified.

    Returns:
        Mapping[str, Any]: The decoded token.
    """
    return verify_token(
        id_token, session, audience=audience,
        certs_url=_GOOGLE_OAUTH2_CERTS_URL)


class TokenInfo(NamedTuple):
    uid: str
    email: str
    expiry: int
    email_verified: bool
    scope: str
    aud: str
    azp: str
    offline: bool

    @property
    def expires_in(self) -> int:
        return self.expiry - time.time()


async def verify_oauth2_token_simple(token, session: ClientSession, audience, scopes: list = None) -> Awaitable[TokenInfo]:
    async with session.get('https://www.googleapis.com/oauth2/v3/tokeninfo',
                           params={'access_token': token}) as resp:
        resp: ClientResponse
        if resp.status != HTTPStatus.OK:
            c = await resp.content.read()
            raise ValueError(resp.reason)

        data = await resp.json()
        if data['aud'] != audience:
            raise ValueError('Token was not issued for this application')

        if scopes and not all(scope in data['scope'] for scope in scopes):
            raise ValueError("Token does not provide requested scopes.")

        data['expiry'] = int(data.pop('exp'))
        data['uid'] = data.pop('sub')
        data['email_verified'] = data.pop('email_verified') == 'true'
        data['offline'] = data.pop('access_type') == "offline"
        data.pop('expires_in')

        return TokenInfo(**data)


def verify_firebase_token(id_token, session: ClientSession, audience=None):
    """Verifies an ID Token issued by Firebase Authentication.

    Args:
        id_token (Union[str, bytes]): The encoded token.
        session (aiohhtp.Session): The object used to make
            HTTP requests.
        audience (str): The audience that this token is intended for. This is
            typically your Firebase application ID. If None then the audience
            is not verified.

    Returns:
        Mapping[str, Any]: The decoded token.
    """
    return verify_token(
        id_token, session, audience=audience, certs_url=_GOOGLE_APIS_CERTS_URL)


async def _token_endpoint_request(session: ClientSession, token_uri, body):
    """Makes a request to the OAuth 2.0 authorization server's token endpoint.

    Args:
        request (google.auth.transport.Request): A callable used to make
            HTTP requests.
        token_uri (str): The OAuth 2.0 authorizations server's token endpoint
            URI.
        body (Mapping[str, str]): The parameters to send in the request body.

    Returns:
        Mapping[str, str]: The JSON-decoded response data.

    Raises:
        google.auth.exceptions.RefreshError: If the token endpoint returned
            an error.
    """
    body = urllib.parse.urlencode(body)
    headers = {
        'content-type': _URLENCODED_CONTENT_TYPE,
    }

    async with session.post(url=token_uri, headers=headers, data=body) as response:
        response_body = await response.content.read()

    if response.status != HTTPStatus.OK:
        _handle_error_response(response_body)

    response_data = json.loads(response_body)

    return response_data



async def jwt_grant(session: ClientSession, token_uri, assertion):
    """Implements the JWT Profile for OAuth 2.0 Authorization Grants.

    For more details, see `rfc7523 section 4`_.

    Args:
        request (google.auth.transport.Request): A callable used to make
            HTTP requests.
        token_uri (str): The OAuth 2.0 authorizations server's token endpoint
            URI.
        assertion (str): The OAuth 2.0 assertion.

    Returns:
        Tuple[str, Optional[datetime], Mapping[str, str]]: The access token,
            expiration, and additional data returned by the token endpoint.

    Raises:
        google.auth.exceptions.RefreshError: If the token endpoint returned
            an error.

    .. _rfc7523 section 4: https://tools.ietf.org/html/rfc7523#section-4
    """
    body = {
        'assertion': assertion,
        'grant_type': _JWT_GRANT_TYPE,
    }

    response_data = await _token_endpoint_request(session, token_uri, body)

    try:
        access_token = response_data['access_token']
    except KeyError:
        raise exceptions.RefreshError(
            'No access token in response.', response_data)

    expiry = _parse_expiry(response_data)

    return access_token, expiry, response_data


class Credentials(_Credentials):
    async def refresh(self, session: ClientSession):
        assertion = self._make_authorization_grant_assertion()
        access_token, expiry, _ = await jwt_grant(
            session, self._token_uri, assertion)
        self.token = access_token
        self.expiry = expiry


class ServiceAccount(NamedTuple):
    credentials: service_account.Credentials
    project_name: str

    async def sub_credentials_coro(self, scopes, session: aiohttp.ClientSession):
        creds = Credentials(
            self.credentials._signer,
            service_account_email=self.credentials._service_account_email,
            scopes=scopes,
            token_uri=self.credentials._token_uri,
            subject=self.credentials._subject,
            additional_claims=self.credentials._additional_claims.copy())
        await creds.refresh(session)
        return creds

    def sub_credentials(self, *list_of_scopes):
        async def coro():
            async with aiohttp.ClientSession() as session:
                return await asyncio.gather(*(self.sub_credentials_coro(scopes, session) for scopes in list_of_scopes))

        loop = uvloop.new_event_loop()
        return loop.run_until_complete(coro())



def make_refresh_authorization_grant_assertion(token_info: TokenInfo, service_accout: ServiceAccount):
    """Create the OAuth 2.0 assertion.

    This assertion is used during the OAuth 2.0 grant to acquire an
    access token.

    Returns:
        bytes: The authorization grant assertion.
    """
    now = _helpers.utcnow()
    lifetime = timedelta(seconds=_DEFAULT_TOKEN_LIFETIME_SECS)
    expiry = now + lifetime

    payload = {
        'iat': _helpers.datetime_to_secs(now),
        'exp': _helpers.datetime_to_secs(expiry),
        # The issuer must be the service account email.
        'iss': service_accout.credentials.service_account_email,
        # The audience must be the auth token endpoint's URI
        'aud': token_info.aud,
        'scope': token_info.scope,
    }

    # The subject can be a user email for domain-wide delegation.
    payload.setdefault('sub', token_info.uid)

    token = jwt.encode(service_accout.credentials._signer, payload)

    return token

async def refresh_grant(session: ClientSession, token_uri, refresh_token, client_id, client_secret):
    """Implements the OAuth 2.0 refresh token grant.

    For more details, see `rfc678 section 6`_.

    Args:
        request (google.auth.transport.Request): A callable used to make
            HTTP requests.
        token_uri (str): The OAuth 2.0 authorizations server's token endpoint
            URI.
        refresh_token (str): The refresh token to use to get a new access
            token.
        client_id (str): The OAuth 2.0 application's client ID.
        client_secret (str): The Oauth 2.0 appliaction's client secret.

    Returns:
        Tuple[str, Optional[str], Optional[datetime], Mapping[str, str]]: The
            access token, new refresh token, expiration, and additional data
            returned by the token endpoint.

    Raises:
        google.auth.exceptions.RefreshError: If the token endpoint returned
            an error.

    .. _rfc6748 section 6: https://tools.ietf.org/html/rfc6749#section-6
    """
    body = {
        'grant_type': _REFRESH_GRANT_TYPE,
        'client_id': client_id,
        'client_secret': client_secret,
        'refresh_token': refresh_token,
    }

    response_data = await _token_endpoint_request(session, token_uri, body)

    try:
        access_token = response_data['access_token']
    except KeyError:
        raise exceptions.RefreshError(
            'No access token in response.', response_data)

    refresh_token = response_data.get('refresh_token', refresh_token)
    expiry = _parse_expiry(response_data)

    return access_token, refresh_token, expiry, response_data