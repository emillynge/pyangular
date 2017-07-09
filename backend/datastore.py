import asyncio
from enum import IntEnum
from functools import partial
from uvloop import loop

import aiogcd
from aiogcd.connector import GcdConnector as _GcdConnector
from aiogcd.connector.key import Key
from aiogcd.orm import GcdModel as _GcdModel
from aiogcd.connector.connector import DATASTORE_URL
from aiogcd.connector.entity import Entity
from aiogcd.orm.filter import Filter
from aiogcd.orm.model import _ModelClass, _PropertyClass
from aiogcd.orm.properties import KeyValue as KeyValue
from aiogcd.orm.properties import StringValue, IntegerValue, DoubleValue, BooleanValue, ArrayValue, JsonValue
from aiohttp import ClientSession
from typing import Optional, Union, Dict, Awaitable

_Union = type(Union)

try:
    import ujson

    json_serializer = ujson.dumps

except ImportError:
    import json

    json_serializer = json.dumps

from .googleauth import Credentials


class Token:
    def __init__(self, parent: 'GcdConnector', credentials: Credentials):
        self.parent = parent
        self.credentials = credentials
        self._lock = asyncio.Lock()

    async def get(self):
        """Returns the access token. If _refresh_ts is passed, the token will
    be refreshed. A lock is used to prevent refreshing the token twice.

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
    def __init__(
            self,
            project_id,
            credentials: Credentials
    ):

        self.project_id = project_id
        self._token = Token(
            self,
            credentials
        )
        self._session: ClientSession = None

        self._run_query_url = DATASTORE_URL.format(
            project_id=self.project_id,
            method='runQuery')

        self._commit_url = DATASTORE_URL.format(
            project_id=self.project_id,
            method='commit')

    async def get_session(self):
        if not self._token.valid:
            self._session._default_headers.update(**(await self._get_headers()))
        return self._session

    async def __aenter__(self):
        self._session = ClientSession(headers=await self._get_headers(), json_serialize=json_serializer)
        return self

    async def __aexit__(self, *args):
        await self._session.close()

    async def commit(self, mutations):
        """Commit mutations.

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

    :param data: see the following link for the data format:
        https://cloud.google.com/datastore/docs/reference/rest/
            v1/projects/runQuery
    :return: list containing Entity objects.
    """

        results = list()
        async for result in self.run_query(data):
            results.append(Entity(result['entity']))

        return results


class GcdModelMeta(_ModelClass):
    annotation2gcd_type = {
        int: IntegerValue,
        str: StringValue,
        float: DoubleValue,
        bool: BooleanValue,
        list: ArrayValue,
        dict: JsonValue,

    }

    def __prepare__(metacls, *_):
        return dict()

    def __new__(cls, klass_name, bases, namespace: dict, **kwds):
        if klass_name == 'GcdModel':
            return type.__new__(cls, klass_name, bases, dict(namespace))

        new_namespace = _PropertyClass()

        for name, annotation in namespace.get('__annotations__', dict()).items():
            extra = dict()
            required = True
            if isinstance(annotation, _Union) and annotation.__args__[-1] is type(None):
                annotation = annotation.__args__[0]
                required = False
                annotation = annotation

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

            try:
                default = namespace.pop(name)
                required = False
            except KeyError:
                default = None

            value = property_type(default=default, required=required, **extra)
            if not hasattr(value, 'get_value_for_serializing'):
                setattr(value, 'get_value_for_serializing', value.get_value)

            new_namespace[name] = value

        new_namespace.update(**namespace)
        new_namespace['__kind__'] = kwds.pop('kind', klass_name)

        return super().__new__(cls, klass_name, bases, new_namespace, **kwds)


class PopulatedFilter:
    def __init__(self, connector: GcdConnector, filter: Filter):
        self._connector = connector
        self._filter = filter

    def __getattr__(self, item):
        fun = getattr(self._filter, item)
        return partial(fun, self._connector)


class GcdModel(_GcdModel, metaclass=GcdModelMeta):
    connector: GcdConnector = None

    @classmethod
    def set_connector(cls, connector: GcdConnector):
        cls.connector = connector

    def __init__(self, *args, key=None, **kwargs):
        if args or 'entity' in kwargs:
            super().__init__(*args, key=key, **kwargs)
            return

        if key:
            if isinstance(key, Key):
                pass
            elif isinstance(key, int):
                key = Key(self.__kind__, key, project_id=self.connector.project_id)
            elif isinstance(key, str):
                key = Key(ks=key)
            else:
                raise TypeError(f'Unknown type for key: {type(key)}')
        else:
            try:
                key = Key(self.__kind__, None, project_id=self.connector.project_id)
            except AttributeError:
                key = Key(self.__kind__, None, project_id=kwargs['project_id'])

        super().__init__(key=key, **kwargs)

    async def put(self):
        try:
            await self.connector.upsert_entity(self)
        except AttributeError as exc:
            raise ValueError('Connector not set. In order to use put, you must call set_connector first!') from exc

    @classmethod
    def filter(cls, *filters, has_ancestor=None, key=None) -> Filter:
        return PopulatedFilter(cls.connector,
                               super().filter(*filters, has_ancestor=has_ancestor, key=None))

    @classmethod
    async def get_by_key(cls, key: Key):
        return await cls.filter(key=key).get_entity()

    def serializable_dict(self, key_as=None):
        data = {
            prop.name: self._serialize_value(prop.get_value_for_serializing(self))
            for prop in self.model_props.values()
            if prop.get_value_for_serializing(self) is not None
        }

        if isinstance(key_as, str):
            data[key_as] = self.key.ks

        return data


class EntityValue(KeyValue):
    def __init__(self, default=None, required=True, entity_type=GcdModel):
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


def entity(klass):
    setattr(klass, '__kind__', klass.__name__)
    return klass


class Roles(IntEnum):
    ADMIN = 10
    REGISTERED = 5
    UNREGISTERED = 1
    SIGNED_OUT = 0


class DemoUser(GcdModel):
    name: Optional[str]
    email: str
    gid: str
    token: str
    role: int

    @property
    def role_as_enum(self):
        return Roles(self.role)

    @classmethod
    async def get_by_auth_session(cls, session: ClientSession):
        async with session.get(f"GET https://www.googleapis.com/plus/v1/people/me") as resp:
            data = await resp.json()
            return cls(name=data['displayName'],
                       gid=data['id'],
                       email=data['emails'][0],
                       token="",
                       role=Roles.UNREGISTERED)
