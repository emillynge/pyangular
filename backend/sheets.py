import datetime
import time
from enum import Enum
from http import HTTPStatus

import aiohttp
import udatetime
import asyncio


class RenderOption(Enum):
    FORMATTED_VALUE = "FORMATTED_VALUE"
    UNFORMATTED_VALUE = "UNFORMATTED_VALUE"
    FORMULA = "FORMULA"


def make_field_mask(fields):
    if isinstance(fields, str):
        return fields

    if isinstance(fields, list):
        return ','.join(make_field_mask(field) for field in fields)

    if isinstance(fields, dict):
        return ','.join(f'{key}({make_field_mask(value)})' for key, value in fields.items())

    return fields


class fetchCache:
    cache = dict()
    TTL = 20

    def __init__(self):
        self.lock = asyncio.Lock()
        self.fetched_at = 0
        self.result = None

    @classmethod
    async def get(cls, session: aiohttp.ClientSession, params: dict, url):
        h = (url, *sorted(params.items()))
        try:
            obj = cls.cache[h]
        except KeyError:
            obj = cls()
            cls.cache[h] = obj

        async with obj.lock:
            if (time.time() - obj.fetched_at) > cls.TTL:
                async with session.get(url, params=params) as resp:
                    if resp.status != HTTPStatus.OK:
                        d = await resp.json()
                        if d:
                            obj.result = ValueError(f'{resp.reason}: {d["error"]["message"]}')
                        else:
                            obj.result = ValueError(resp.reason)
                    else:
                        obj.result = await resp.json()

                    obj.fetched_at = time.time()

            if isinstance(obj.result, Exception):
                raise obj.result
            return obj.result


async def get_sheet_modify_time(spreadsheet_id, session: aiohttp.ClientSession):
    url = f"https://www.googleapis.com/drive/v3/files/{spreadsheet_id}"
    params = dict(fields="modifiedTime")
    data = await fetchCache.get(session, params, url)
    return udatetime.from_string(data['modifiedTime'])


async def get_sheet(spreadsheet_id, session: aiohttp.ClientSession, fields: list=None):
    url = (f'https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}')
    params = dict()
    if fields:
        params['fields'] = make_field_mask(fields)
    return await fetchCache.get(session, params, url)


async def get_sheet_values(sheet_id, session: aiohttp.ClientSession, a1notation, formula=False, render_option=RenderOption.FORMATTED_VALUE):

    render_option = RenderOption.FORMULA if formula else render_option
    url = (f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/'
           f'values/{a1notation}')

    return (await fetchCache.get(session, dict(valueRenderOption=render_option.value), url))['values']