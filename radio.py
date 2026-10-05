"""Radio Garden links and streams. Its API is public but not documented officially."""
import asyncio
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import aiohttp

API_BASE = "https://radio.garden/api/ara/content"
REDIRECTS = {301, 302, 303, 307, 308}
TIMEOUT = aiohttp.ClientTimeout(total=20, sock_connect=10, sock_read=10)


def normalize_radio_link(value: str) -> tuple[str, str]:
    parsed = urlparse(value.strip().strip("<>"))
    if (parsed.scheme != "https" or parsed.hostname not in {"radio.garden", "www.radio.garden"}
            or parsed.username or parsed.password or parsed.port):
        raise ValueError("Mandá un enlace HTTPS de una emisora de Radio Garden.")
    match = re.fullmatch(r"/listen/([A-Za-z0-9_-]+)/([A-Za-z0-9]{8})/?", parsed.path)
    if not match:
        raise ValueError("Usá el enlace de una emisora: https://radio.garden/listen/nombre/ID. Los enlaces /visit/ son ciudades.")
    return match[2], f"https://radio.garden/listen/{match[1]}/{match[2]}"


async def get_station(link: str) -> dict:
    station_id, canonical = normalize_radio_link(link)
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{API_BASE}/channel/{station_id}", allow_redirects=False) as response:
                response.raise_for_status()
                if response.status != 200:
                    raise ValueError("Respuesta inesperada de Radio Garden.")
                data = (await response.json())["data"]
        if not isinstance(data, dict) or not isinstance(data.get("title"), str) or not data["title"].strip():
            raise ValueError("La emisora no tiene un nombre válido.")
        return {"link": canonical, "title": data["title"].strip()[:180]}
    except (aiohttp.ClientError, TimeoutError, KeyError, TypeError, ValueError) as error:
        raise ValueError("No pude obtener esa emisora de Radio Garden. Revisá el enlace e intentá otra vez.") from error


async def validate_stream_url(url: str) -> None:
    """Do not let an external redirect select files, credentials or private hosts."""
    parsed = urlparse(url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password):
        raise ValueError("La emisora devolvió un enlace de audio inválido.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    addresses = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError("El stream debe estar alojado en una dirección pública.")


DEFAULT_AD_KEYWORDS = "publicidad,comercial,comerciales,spot,anuncio,tanda,advertisement,advertising,commercial"
MAX_ICY_INTERVAL = 1 << 20


def ad_pattern(keywords: str) -> re.Pattern | None:
    """Whole-word, case-insensitive matcher for stream titles; None disables detection."""
    words = [word.strip() for word in keywords.split(",") if word.strip()]
    if not words:
        return None
    return re.compile(r"(?<!\w)(?:" + "|".join(map(re.escape, words)) + r")(?!\w)", re.IGNORECASE)


async def icy_titles(url: str):
    """Yield each new in-band ICY StreamTitle. Ends quietly if the station sends no metadata."""
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, headers={"Icy-MetaData": "1"}, allow_redirects=False) as response:
            response.raise_for_status()
            try:
                interval = int(response.headers.get("icy-metaint", 0))
            except ValueError:
                return
            if not 0 < interval <= MAX_ICY_INTERVAL:
                return
            while True:
                await response.content.readexactly(interval)
                length = (await response.content.readexactly(1))[0] * 16
                if not length:
                    continue
                block = await response.content.readexactly(length)
                match = re.search(rb"StreamTitle='(.*?)';", block, re.DOTALL)
                if match:
                    yield match[1].decode("utf-8", "replace").strip()[:200]


async def resolve_stream(link: str) -> str:
    """Follow redirects ourselves and close the live response after reading headers."""
    station_id, _ = normalize_radio_link(link)
    url = f"{API_BASE}/listen/{station_id}/channel.mp3"
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        for hop in range(6):
            if hop:
                await validate_stream_url(url)
            async with session.get(url, allow_redirects=False) as response:
                if response.status in REDIRECTS:
                    location = response.headers.get("Location")
                    if not location:
                        raise ValueError("Radio Garden no devolvió el stream de la emisora.")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
                if not hop or content_type in {"text/html", "application/json"}:
                    raise ValueError("La emisora no devolvió un stream de audio.")
                return url
    raise ValueError("El stream redirige demasiadas veces.")
