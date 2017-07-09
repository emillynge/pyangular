from argparse import ArgumentParser
from .settings import load_env, AppEnviron

load_env('app')

parser = ArgumentParser(AppEnviron.APP_NAME)

parser.add_argument('-e', '--environment', default='prod')


def main(*args):
    args = args or None
    options = parser.parse_args(args)
    load_env(options.environment)
    from .server import run_server
    run_server()






