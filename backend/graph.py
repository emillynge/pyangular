from functools import wraps
from typing import NamedTuple

import aiohttp

from .datastore import DemoUser as User
from .datastore import Roles
import graphene

import google.oauth2.credentials


class InsufficientPrivilegesException(Exception):
    @classmethod
    def from_roles(cls, required: Roles, found: Roles):
        return cls(f'Caller does not have permission to do requested action. '
                   f'role {Roles(required)} was needed, but caller has {Roles(found)}')


def require_role(role: Roles):
    def decorator(fun):
        @wraps(fun)
        def wrapper(root, args, context, info):
            caller: Caller = context['caller']
            if caller.entity.role < role:
                raise InsufficientPrivilegesException(role, caller.entity.role)

            return fun(root, args, context, info)

        return wrapper

    return decorator


class Caller(NamedTuple):
    # credentials: google.oauth2.credentials.Credentials
    id: int
    entity: User
    session: aiohttp.ClientSession


class Profile(graphene.ObjectType):
    name = graphene.String()
    email = graphene.String()
    role = graphene.Int()
    gid = graphene.String()

    @classmethod
    def from_entity(cls, entity: User):
        return cls(**dict((field, getattr(entity, field)) for field in cls._meta.local_fields))


class ProfileUpdate(graphene.Mutation):
    class Input:
        gid = graphene.String()
        email = graphene.String()
        name = graphene.String()
        role = graphene.Int()

    ok = graphene.Boolean()
    user = graphene.Field(lambda: Profile)

    @staticmethod
    @require_role(Roles.UNREGISTERED)
    async def mutate(root, args, context, info):
        caller: Caller = context['caller']
        user: User = await User.filter(User.gid == args['gid']).get_entity()
        if user is None:
            raise Exception(f'No user found with gid {args["gid"]}')

        if caller.id != user.gid and caller.entity.role < Roles.ADMIN:
            raise InsufficientPrivilegesException('Only admin can update other peoples profiles')

        if args['role'] != user.role and caller.entity.role < Roles.ADMIN:
            raise InsufficientPrivilegesException('Only admin can change user roles')

        changes = False
        for field, new_value in args.items():
            if getattr(user, field) != new_value:
                setattr(user, field, new_value)
                changes = True

        if changes:
            await user.put()
        ok = True

        return ProfileUpdate(user=Profile.from_entity(user), ok=ok)


class GrapheneQuery(graphene.ObjectType):
    current_profile = graphene.Field(Profile)

    def resolve_current_profile(self, args, context, info):
        user_entity = context['caller'].entity
        return Profile.from_entity(user_entity)


class GrapheneMutation(graphene.ObjectType):
    profile_update = ProfileUpdate.Field()


GRAPHENE_SCHEMA = graphene.Schema(query=GrapheneQuery, mutation=GrapheneMutation)
