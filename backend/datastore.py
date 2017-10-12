"""
Monkey patching of aiogcd to suit specific tastes and implementation of some datastore entities
"""
# builtin imports
import asyncio
import datetime
from enum import IntEnum
from functools import partial
from typing import Optional, Union, Dict, Awaitable, List
import json

import pytz
from json_tricks import TricksPairHook, json_date_time_hook
from udatetime import TZFixedOffset

from backend.sheets import get_project_sheets, get_sheet_modify_time

_Union = type(Union)

# pip imports
import udatetime
from aiogcd.connector import GcdConnector as _GcdConnector
from aiogcd.connector.key import Key
from aiogcd.orm import GcdModel as _GcdModel
from aiogcd.connector.connector import DATASTORE_URL
from aiogcd.connector.entity import Entity
from aiogcd.orm.filter import Filter
from aiogcd.orm.model import _ModelClass, _PropertyClass
from aiogcd.orm.properties import (KeyValue as KeyValue, DatetimeValue as _DatetimeValue,
                                   StringValue, IntegerValue, DoubleValue, BooleanValue, ArrayValue, JsonValue as _JsonValue)
from aiohttp import ClientSession

# relative imports
from .googleauth import Credentials


# Try to use ujson for speed, otherwise use standard json
try:
    import ujson
    json_serializer = ujson.dumps
except ImportError:
    import json
    json_serializer = json.dumps



class DatetimeValue(_DatetimeValue):
    def set_value(self, model, value: 'datetime.datetime'):
        if isinstance(value, datetime.datetime):
            if value.utcoffset() is None:
                offset = 0
            else:
                offset = value.utcoffset().seconds//60
            value = udatetime.to_string(value.astimezone(TZFixedOffset(offset)) + datetime.timedelta(hours=2))

        super().set_value(model, value)

    def get_value(self, model):
        value = super().get_value(model)
        return udatetime.from_string(str(value)) if value is not None else None

import json_tricks
class JsonValue(_JsonValue):
    encoder = json_tricks.TricksEncoder
    obj_encoders = [json_tricks.json_date_time_encode]
    decoder_hooks = [json_date_time_hook]

    def set_value(self, model, value):
        self.check_value(value)
        try:
            data = json_tricks.dumps(value, obj_encoders=self.obj_encoders)
        except TypeError as e:
            raise TypeError('Value for property {!r} could not be parsed: {}'
                            .format(self.name, e))
        model.__dict__['__orig__{}'.format(self.name)] = value
        super(_JsonValue, self).set_value(model, data)

    def get_value(self, model):
        key = '__orig__{}'.format(self.name)

        if key not in model.__dict__:
            try:
                model.__dict__[key] = json_tricks.loads(model.__dict__[self.name])#,
                                                        #obj_pairs_hooks=json_tricks.nonp.DEFAULT_NONP_HOOKS
                                                        #obj_pairs_hooks=[json_tricks.decoders.json_date_time_hook,
                                                        #                 json_tricks.decoders.numeric_types_hook
                                                        #                 ]
                                                        #)
            except Exception as e:
                raise Exception(
                    'Error reading property {!r} '
                    '(see above exception for more info).'
                        .format(self.name)) from e

        return model.__dict__[key]


class EntityValue(KeyValue):
    """
    New Value that holds an entity based on a passed Key
    Makes it possible to directly call an entity on another entity
    """
    def __init__(self, default=None, required=True, entity_type='GcdModel'):
        super().__init__(default=default, required=required)
        self.entity_type = entity_type
        self.entity_cache: Dict[Key, GcdModel] = dict()

    def set_value(self, model, value: 'GcdModel'):
        try:
            new_value = value.key
        except AttributeError:
            if isinstance(value, KeyValue):
                pass
            elif not isinstance(value, self.entity_type):
                raise TypeError(
                    'Expecting an value of sub-type \'GcdModel\' for property {!r} '
                    'but received type {!r}.'
                        .format(self.name, value.__class__.__name__))

        super().set_value(model, new_value)
        self.entity_cache[new_value] = value

    def get_value(self, model):
        """
        Check cache for entity, and wrap in future to be awaited.
        If not cached, return async wrapper that returns object and caches result
        :param model:
        :return:
        """
        key = super().get_value(model)
        try:
            value = self.entity_cache[key]

            async def fetch():
                return value

        except KeyError:
            async def fetch():
                value = await self.entity_type.get_by_key(key)
                self.entity_cache[key] = value
        return fetch()

    def get_value_for_serializing(self, model):
        return super().get_value(model)


class Token:
    """
    Wrapper around Credentials to replace aiogcd Token
    """
    def __init__(self, parent: 'GcdConnector', credentials: Credentials):
        self.parent = parent
        self.credentials = credentials
        self._lock = asyncio.Lock()

    async def get(self):
        """Returns the access token. check for validity, else try to refres token
    :return: Access token (string)
    """

        async with self._lock:
            if not self.credentials.valid:
                await self.credentials.refresh(self.parent._session)
            return self.credentials.token

    @property
    def valid(self):
        return self.credentials.valid


class GcdConnector(_GcdConnector):
    """
    Monkeypatch aiogcd implementation to suit taste
    """

    def __init__(
            self,
            project_id,
            credentials: Credentials
    ):
        """
        only take project as credentials as input. rest can be derived
        :param project_id:
        :param credentials:
        """

        self.project_id = project_id
        # wrap creds in token
        self._token = Token(
            self,
            credentials
        )

        # init empty session. Must use __aenter__ to get a session.
        self._session: ClientSession = None

        self._run_query_url = DATASTORE_URL.format(
            project_id=self.project_id,
            method='runQuery')

        self._commit_url = DATASTORE_URL.format(
            project_id=self.project_id,
            method='commit')

    async def get_session(self):
        """
        return a session that is already authorized by credentials
        :return:
        """
        if not self._token.valid:
            self._session._default_headers.update(**(await self._get_headers()))
        return self._session

    async def __aenter__(self):
        self._session = ClientSession(headers=await self._get_headers())#, json_serializer=json_serializer)
        return self

    async def __aexit__(self, *args):
        self._session.close()

    async def commit(self, mutations):
        """Commit mutations.
        reimplementation with shared session

    The only supported commit mode is NON_TRANSACTIONAL.

    See the link below for information for a description of a mutation:

    https://cloud.google.com/datastore/docs/reference/
            rest/v1/projects/commit#Mutation

    :param mutations: List or tuple with mutations
    :return: tuple containing mutation results
    """
        data = {
            'mode': 'NON_TRANSACTIONAL',
            'mutations': mutations
        }
        session = await self.get_session()
        async with session.post(
                self._commit_url,
                json=data,
        ) as resp:
            content = await resp.json()

            if resp.status == 200:
                return tuple(content.get('mutationResults', tuple()))

            raise ValueError(
                'Error while committing to the datastore: {} ({})'
                    .format(
                    content.get('error', 'unknown'),
                    resp.status
                ))

    async def run_query(self, data):
        """Return entities by given query data.
        Reimplementation with shared session, and as an async generator

    :param data: see the following link for the data format:
        https://cloud.google.com/datastore/docs/reference/rest/
            v1/projects/runQuery
    :return: list containing Entity objects.
    """
        start_cursor = None
        while True:
            if start_cursor is not None:
                data['query']['startCursor'] = start_cursor

            async with (await self.get_session()).post(
                    self._run_query_url,
                    json=data,
            ) as resp:

                content = await resp.json()

                if resp.status == 200:

                    entity_results = \
                        content['batch'].get('entityResults', [])

                    for result in entity_results:
                        yield result

                    more_results = content['batch']['moreResults']

                    if more_results in (
                            'NO_MORE_RESULTS',
                            'MORE_RESULTS_AFTER_LIMIT',
                            'MORE_RESULTS_AFTER_CURSOR'):
                        return

                    if more_results == 'NOT_FINISHED':
                        start_cursor = content['batch']['endCursor']
                        continue

                    raise ValueError(
                        'Unexpected value for "moreResults": {}'
                            .format(more_results))

                raise ValueError(
                    'Error while query the datastore: {} ({})'
                        .format(
                        content.get('error', 'unknown'),
                        resp.status
                    )
                )

    async def get_entity_by_key(self, key):
        """Returns an entity object for the given key or None in case no
    entity is found.

    Reimplementation with shared session.
    :param key: Key object
    :return: Entity object or None.
    """
        data = {
            'query': {
                'filter': {
                    'propertyFilter': {
                        'property': {
                            'name': '__key__'
                        },
                        'op': 'EQUAL',
                        'value': {
                            'keyValue': key.get_dict()
                        }
                    }
                }
            }
        }

        async with (await self.get_session()).post(
                self._run_query_url,
                json=data,
        ) as resp:

            content = await resp.json()

            try:
                res = content['batch']['entityResults']
            except KeyError:
                return None

            entity_res = res.pop()

            assert len(res) == 0, \
                'Expecting zero or one entity but found {} results' \
                    .format(len(res))

            return Entity(entity_res['entity'])


    async def get_entities(self, data):
        """Return entities by given query data.

        Reimplement to use async generator

    :param data: see the following link for the data format:
        https://cloud.google.com/datastore/docs/reference/rest/
            v1/projects/runQuery
    :return: list containing Entity objects.
    """

        results = list()
        async for result in self.run_query(data):
            results.append(Entity(result['entity']))

        return results

    async def get_entities_gen(self, data):
        """Return entities by given query data.

        Reimplement as async generator

    :param data: see the following link for the data format:
        https://cloud.google.com/datastore/docs/reference/rest/
            v1/projects/runQuery
    :return: list containing Entity objects.
    """

        results = list()
        async for result in self.run_query(data):
            yield results.append(Entity(result['entity']))


class GcdModelMeta(_ModelClass):
    annotation2gcd_type = {
        int: IntegerValue,
        str: StringValue,
        float: DoubleValue,
        bool: BooleanValue,
        list: ArrayValue,
        dict: JsonValue,
        Dict: JsonValue,
        datetime.datetime: DatetimeValue,
    }

    def __prepare__(metacls, *_):
        return dict()

    def __new__(cls, klass_name, bases, namespace: dict, **kwds):
        if klass_name == 'GcdModel':  # pass baseclass thorugh with no meddling
            return type.__new__(cls, klass_name, bases, dict(namespace))

        # rebuild namespace from scratch to match what _ModelClass expects
        new_namespace = _PropertyClass()

        for name, annotation in namespace.get('__annotations__', dict()).items():
            extra = dict()
            required = True
            if isinstance(annotation, _Union) and annotation.__args__[-1] is type(None):
                annotation = annotation.__args__[0]
                required = False
                annotation = annotation

            try:
                default = namespace.pop(name)
                if callable(default):  # it is a function!
                    new_namespace[name] = default
                    continue

                required = False
            except KeyError:
                default = None

            try:
                property_type = cls.annotation2gcd_type[annotation]
            except KeyError:
                if issubclass(annotation, Awaitable):
                    annotation = annotation.__args__[0]

                if issubclass(annotation, GcdModel):
                    property_type = EntityValue
                    extra['entity_type'] = annotation

                else:
                    for annotation_base, _property_type in cls.annotation2gcd_type.items():
                        if issubclass(annotation, annotation_base):
                            property_type = _property_type
                            break
                    else:
                        continue



            value = property_type(default=default, required=required, **extra)
            if not hasattr(value, 'get_value_for_serializing'):
                setattr(value, 'get_value_for_serializing', value.get_value)

            new_namespace[name] = value

        new_namespace.update(**namespace)
        new_namespace['__kind__'] = kwds.pop('kind', klass_name)

        return super().__new__(cls, klass_name, bases, new_namespace, **kwds)


class PopulatedFilter:
    """
    Wrapper around a filter such that any method called on filter is prepopulated with a connector as first arg
    """
    def __init__(self, connector: GcdConnector, filter: Filter):
        self._connector = connector
        self._filter = filter

    def __getattr__(self, item):
        fun = getattr(self._filter, item)
        return partial(fun, self._connector)


class GcdModel(_GcdModel, metaclass=GcdModelMeta):
    """
    Subclass aiogcd GcdModel to get more functionality

    primarily this consist of using a shared connector that is set on the class,
    rather than passing one with every method call
    """
    connector: GcdConnector = None

    @classmethod
    def set_connector(cls, connector: GcdConnector):
        """
        Set a connector to be used for all requests made by instances of this class
        :param connector:
        :return:
        """
        cls.connector = connector

    def __init__(self, *args, key=None, **kwargs):
        """
        Attempt to produce a key for the object before sending arguments to superclass
        :param args:
        :param key:
        :param kwargs:
        """
        if args or 'entity' in kwargs:
            super().__init__(*args, key=key, **kwargs)
            return

        if key:
            if isinstance(key, Key):
                pass
            elif isinstance(key, int):
                key = Key(self.__kind__, key, project_id=self.connector.project_id)
            elif isinstance(key, str):
                # string key is assumed to be a keystring (ks)
                key = Key(ks=key)
            else:
                raise TypeError(f'Unknown type for key: {type(key)}')
        else:
            try:
                # assume that a project_id can be found in class connector
                key = Key(self.__kind__, None, project_id=self.connector.project_id)
            except AttributeError:
                # not connector found, get project_id from kwargs. If it fails let it throw exception
                # since we cannot instantiate without key
                key = Key(self.__kind__, None, project_id=kwargs['project_id'])

        super().__init__(key=key, **kwargs)

    async def put(self):
        # API taken from ndb where put is called when you want to save stuff in an entity
        try:
            await self.connector.upsert_entity(self)
        except AttributeError as exc:
            raise ValueError('Connector not set. In order to use put, you must call set_connector first!') from exc

    def __contains__(self, item):
        return item in self._properties

    @classmethod
    def filter(cls, *filters, has_ancestor=None, key=None) -> Filter:
        """
        Wrap filter method such that is comes prepopulated with a connector
        :param filters:
        :param has_ancestor:
        :param key:
        :return:
        """
        return PopulatedFilter(cls.connector,
                               super().filter(*filters, has_ancestor=has_ancestor, key=None))

    @classmethod
    async def get_by_key(cls, key: Key):
        """
        Get a entity based on a key
        :param key:
        :return:
        """
        return await cls.filter(key=key).get_entity()

    def serializable_dict(self, key_as=None):
        """
        Reimplement to use get_value_for_serializing, to ensure json decodeable objects
        :param key_as:
        :return:
        """
        data = {
            prop.name: self._serialize_value(prop.get_value_for_serializing(self))
            for prop in self.model_props.values()
            if prop.get_value_for_serializing(self) is not None
        }

        if isinstance(key_as, str):
            data[key_as] = self.key.ks

        return data



class Roles(IntEnum):
    """
    Enumaration of possible roles (access levels)
    """
    ADMIN = 10
    REGISTERED = 5
    UNREGISTERED = 1
    SIGNED_OUT = 0


class DemoUser(GcdModel):
    """
    A simple user entity with google access_token, a google id, name, email and a role within the system.
    """
    name: Optional[str]
    email: str
    gid: str
    token: str
    refresh_token: Optional[str]
    role: int

    @property
    def role_as_enum(self):
        """
        Return the role in terms of the Roles enumaration
        :return:
        """
        return Roles(self.role)

    @classmethod
    async def new_from_authorized_session(cls, session: ClientSession):
        """
        get a new User Entity from a session authorized with a google user token.
        :param session:
        :return:
        """

        # ask google who this token belongs to
        async with session.get(f"GET https://www.googleapis.com/plus/v1/people/me") as resp:
            data = await resp.json()
            return cls(name=data['displayName'],
                       gid=data['id'],
                       email=data['emails'][0],
                       token=session._default_headers['Authorization'].split('Bearer ')[-1],
                       role=Roles.UNREGISTERED)

    @property
    def authorized_session(self):
        return ClientSession(headers={'Authorization': 'Bearer {}'.format(self.token),
                                      'Content-Type': 'application/json'})


class NonExpireableData(GcdModel):
    data: Optional[dict]
    last_modified: Optional[datetime.datetime]
    name: str
    id: str

    async def is_expired(self, session: ClientSession):
        return False


class GoogleSheetData(GcdModel):
    data: Optional[dict]
    spreadsheet_id: str
    sheet_id: Optional[int]
    last_modified: Optional[datetime.datetime]
    name: str

    async def is_expired(self, session: ClientSession):
        if 'last_modified' not in self:
            return True

        modified = await get_sheet_modify_time(self.spreadsheet_id, session)
        return self.last_modified < modified