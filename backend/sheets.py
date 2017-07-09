import aiohttp
from aiohttp import web
from aiohttp.web_request import Request


async def get_sheet_values(sheet_id, sheet_name, session: aiohttp.ClientSession, a1notation, formula=False):
    render_option = "FORMULA" if formula else "FORMATTED_VALUE"
    url = (f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/'
           f'values/{sheet_name}!{a1notation}?valueRenderOption={render_option}')
    async with session.get(url) as resp:
        try:
            return (await resp.json())['values']
        except KeyError:
            return


async def api(request: Request, session: aiohttp.ClientSession):
    sheet_id = '1lG46UkIICJ2fZAX2EUoxHvHUtoTeuFGRex3OI7sZ4PU'
    async with session.get(f'https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}') as resp:
        r: aiohttp.ClientResponse = resp
        data = await r.json()

        tasks = [get_sheet_values(sheet['properties']['title'],
                                  sheet_id,
                                  session) for sheet in data['sheets']
                 if sheet['properties']['title'] != 'SpejlSkabelon']
        await aiohttp.asyncio.gather(*tasks)

    return web.Response(text=f'Called! with {token}')
