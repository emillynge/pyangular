"""
This file provides entrypoints for scripts
"""
import aiohttp
import keyring

from .googleauth import verify_oauth2_token_simple, TokenInfo, make_refresh_authorization_grant_assertion, jwt_grant, \
    refresh_grant
from . import googleauth
import asyncio
import json
import sys
from .common import User, VANILLA_SESSION, BaseEnviron, GCD_CONNECTOR, ROOT_ACCOUNT
from .graph import GRAPHENE_SCHEMA, Caller


async def verify_oauth2_token_simple_no_exception(*args, **kwargs):
    try:
        return await verify_oauth2_token_simple(*args, **kwargs)
    except Exception as exc:
        return exc

async def refresh(refresh_token):
    with open(BaseEnviron.WEBAPP_SECRETS_PATH) as fp:
        secrets = json.load(fp)
        client_id = secrets['web']['client_id']
        client_secret = secrets['web']['client_secret']
        token_uri = secrets['web']['token_uri']

    access_token, refresh_token, expiry, response_data = await refresh_grant(VANILLA_SESSION, token_uri, refresh_token, client_id, client_secret)
    return access_token, refresh_token

class AuthSequence:
    class MultipleKeys(tuple):
        pass

    def __init__(self, email):
        refresh_token = keyring.get_password(f'kursusfordeler-token', email)
        access_token = None
        if refresh_token is None:
            refresh_token = input(f'No token found for use with {email}. please input one: ')
        else:
            refresh_token, *access_token = refresh_token.split('|')

        self.email = email
        self.data = dict(refresh_token=refresh_token)
        if access_token:
            self.data['access_token'] = access_token[0]
        self.coros = dict()


    async def auth(self):
        while True:
            try:
                token_info: TokenInfo = self.data.pop('access_token_info')
                if not isinstance(token_info, Exception):

                    if token_info.uid != self.data['user_entity'].gid:
                        print("token belongs to different user")
                        self.data.pop('refresh_token', None)
                        self.data.pop('refresh_token_info', None)

                    elif token_info.expires_in > 120:
                        keyring.set_password(f'kursusfordeler-token',
                                             self.email,
                                             f'{self.data["refresh_token"]}|{self.data["access_token"]}')

                        user_entity: User = self.data['user_entity']
                        if user_entity.refresh_token != self.data["refresh_token"] or user_entity.token != self.data["access_token"]:
                            user_entity.refresh_token = self.data["refresh_token"]
                            user_entity.token = self.data["access_token"]
                            await user_entity.put()

                        print(f'Token expiry: access - {token_info.expires_in}')

                        return Caller(user_entity.gid,
                                      user_entity,
                                      user_entity.authorized_session)

                print(f'Access_token invalid: {token_info}')
                self.data.pop('access_token', None)

            except KeyError:
                pass

            results = await asyncio.gather(*list(self.coros.values()))
            for key, result in zip(self.coros.keys(), results):
                if isinstance(key, AuthSequence.MultipleKeys):
                    for k, v in zip(key, result):
                        self.data[k] = v
                else:
                    self.data[key] = result

            self.coros.clear()

            if 'user_entity' not in self.data:
                print('get entity')
                self.coros['user_entity'] = User.filter(User.email == self.email).get_entity()

            if 'user_entity' in self.data and self.data['user_entity'] is None:
                print(f"user {email} does not exist.")
                sys.exit(1)

            if 'refresh_token' not in self.data:
                self.data['refresh_token'] = input(f'token not working. please input another one or leave empty to quit: ')
                if self.data['refresh_token'] == "":
                    sys.exit(1)

            if 'access_token' not in self.data:
                print('refresh tokens')
                self.coros[AuthSequence.MultipleKeys(['access_token', 'refresh_token'])] = refresh(self.data['refresh_token'])

                continue
            elif 'access_token_info' not in self.data:
                print('verify access token')
                self.coros['access_token_info'] = verify_oauth2_token_simple_no_exception(self.data['access_token'],
                                                                                          VANILLA_SESSION, BaseEnviron.WEBAPP_CLIENT_ID,
                                                                                          scopes=["https://www.googleapis.com/auth/drive.readonly",
                                                                                                  "https://www.googleapis.com/auth/spreadsheets"
                                                                                                  ])

async def get_caller(email):
    async with GCD_CONNECTOR:
        return await AuthSequence(email).auth()




