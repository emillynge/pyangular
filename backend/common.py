import asyncio
import json

import aiogcd.connector.connector
import aiohttp
import google.oauth2.credentials
import uvloop
from google.auth._default import _load_credentials_from_file

from .datastore import DemoUser as User, GoogleSheetData, NonExpireableData
from .datastore import GcdConnector, Roles
from .googleauth import ServiceAccount
from .settings import BaseEnviron, AppEnviron, load_env

if BaseEnviron.SERVICE_ACCOUNT_SECRETS_PATH is None:
    load_env(AppEnviron.ENV)

#request = google.auth.transport.requests.Request()
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
GoogleSheetData.set_connector(GCD_CONNECTOR)
NonExpireableData.set_connector(GCD_CONNECTOR)
