"""
Handle import of environment variables and set variables from files

also holds objects for easy access to variables used by the app
"""
import os
import pathlib
from dotenv import load_dotenv


class StaticProperty:
    __slots__ = ('fget', 'value')

    def __init__(self, getter):
        self.fget = getter
        self.value = None

    def __get__(self, cls, owner):
        value = self.fget(self)
        if value is None:
            return self.value
        return value

    def __set__(self, instance, value):
        self.value = value


class EnvironMeta(type):
    @classmethod
    def make_getter(cls, field, typ, default):
        if typ is pathlib.Path:
            def typ(val):
                if val[0] in './':
                    path = pathlib.Path(val)
                else:
                    path = pathlib.Path(__file__).parent.joinpath(val)

                return path

        def getter(self):
            val = os.environ.get(field)
            if val is None:
                return default
            return typ(val)

        return getter

    def __new__(cls, name, bases, attrs, **_):
        for field, typ in attrs.get('__annotations__', dict()).items():
            default = attrs.get(field, None)
            attrs[field] = StaticProperty(cls.make_getter(field, typ, default))

        def raise_init(*_):
            raise Exception('Should not be instantiated')

        attrs['__init__'] = raise_init
        return super().__new__(cls, name,  bases, attrs, **_)


class AppEnviron(metaclass=EnvironMeta):
    APP_NAME: str


class BaseEnviron(metaclass=EnvironMeta):
    SERVICE_ACCOUNT_SECRETS_PATH: pathlib.Path
    WEBAPP_SECRETS_PATH: pathlib.Path
    SERVER_PORT: int
    SERVER_DOMAIN: str
    WEBAPP_CLIENT_ID: str
    ANGULAR_BUNDLE_PATH: pathlib.Path = pathlib.Path(__file__).parent.joinpath('js')


def load_env(env='prod'):
    if env[0] in './':
        dotenv_path = pathlib.Path(env)
    else:
        dotenv_path = pathlib.Path(__file__).parent.joinpath(f'.{env}.env')
    load_dotenv(dotenv_path)
