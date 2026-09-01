import urllib.parse
import logging
from yarl import URL
from amc_peripheral.settings import GAME_SERVER_API_URL
from amc_peripheral.utils.text_utils import strip_emoji

log = logging.getLogger(__name__)


async def game_api_request(http_session, url, method="get", password="", params={}):
    req_params = {"password": password, **params}
    # pyrefly: ignore [bad-argument-type]
    params_str = urllib.parse.urlencode(req_params, quote_via=urllib.parse.quote)
    try:
        fn = getattr(http_session, method)
    except AttributeError as e:
        log.error(f"Invalid method: {e}")
        raise e

    full_url = f"{GAME_SERVER_API_URL}{url}?{params_str}"
    log.debug(f"Game API request: {method.upper()} {full_url}")
    
    async with fn(
        URL(full_url, encoded=True)
    ) as resp:
        log.debug(f"Game API response status: {resp.status}")
        if resp.status >= 400:
            text = await resp.text()
            log.error(f"Game API error {resp.status}: {text[:200]}")
            raise Exception(f"Game API error {resp.status}: {text[:100]}")
        resp_json = await resp.json()
        return resp_json


async def announce_in_game(http_session, message, type="message", color="FFFF00"):
    # In-game Motor Town chat renders Unicode emoji as blank squares, so strip
    # them at the ONE chokepoint every game-chat path funnels through
    # (knowledge/radio/utils/translation cogs all post via announce_in_game).
    # Code-enforced, mirrors the knowledge_cog._call_llm_with_tools rule (PR #34)
    # which only covered that cog's own replies — radio_cog was leaking emoji.
    message = strip_emoji(message)
    params = {"message": message, "type": type}
    if color is not None:
        params["color"] = color
    log.info(f"Announcing in game: {message[:100]}...")
    result = await game_api_request(http_session, "/chat", method="post", params=params)
    log.info(f"Announce result: {result}")
    return result
