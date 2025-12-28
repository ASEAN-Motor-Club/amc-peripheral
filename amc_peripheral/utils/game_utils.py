import urllib.parse
import logging
from yarl import URL
from amc_peripheral.settings import GAME_SERVER_API_URL

log = logging.getLogger(__name__)

async def game_api_request(http_session, url, method='get', password='', params={}):
    req_params = {'password': password, **params}
    params_str = urllib.parse.urlencode(req_params, quote_via=urllib.parse.quote)
    try:
        fn = getattr(http_session, method)
    except AttributeError as e:
        log.error(f"Invalid method: {e}")
        raise e

    async with fn(URL(f"{GAME_SERVER_API_URL}{url}?{params_str}", encoded=True)) as resp:
        resp_json = await resp.json()
        return resp_json

async def announce_in_game(http_session, message, type="message", color="FFFF00"):
    params = {'message': message, 'type': type}
    if color is not None:
        params['color'] = color
    await game_api_request(http_session, '/chat', method='post', params=params)
