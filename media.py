"""Only accept individual YouTube / Spotify tracks, never arbitrary URLs."""
import asyncio
import re
from urllib.parse import parse_qs, urlparse

import aiohttp
import yt_dlp


def normalize_link(value: str) -> tuple[str, str]:
    parsed = urlparse(value.strip().strip("<>"))
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.port:
        raise ValueError("Usá un enlace HTTPS de YouTube o Spotify.")
    host = (parsed.hostname or "").lower()
    if host == "open.spotify.com":
        match = re.fullmatch(r"/(?:intl-[a-z]+/)?track/([A-Za-z0-9]{22})/?", parsed.path)
        if match:
            return "spotify", f"https://open.spotify.com/track/{match[1]}"
        raise ValueError("Spotify: mandá el enlace de una canción, no un álbum o playlist.")
    video = None
    if host == "youtu.be":
        video = parsed.path.strip("/")
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            video = parse_qs(parsed.query).get("v", [None])[0]
        else:
            match = re.fullmatch(r"/(?:shorts|live)/([A-Za-z0-9_-]{11})/?", parsed.path)
            video = match[1] if match else None
    if video and re.fullmatch(r"[A-Za-z0-9_-]{11}", video):
        return "youtube", f"https://www.youtube.com/watch?v={video}"
    raise ValueError("Mandá un enlace de una canción de YouTube o open.spotify.com/track/…")


def extract(query: str) -> dict:
    options = {
        "format": "bestaudio/best", "noplaylist": True,
        "quiet": True, "no_warnings": True, "socket_timeout": 15,
        "retries": 2, "extractor_retries": 2,
        "js_runtimes": {"deno": {}},
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(query, download=False)
    if info and "entries" in info:
        info = next((entry for entry in info["entries"] if entry), None)
    if not info or not info.get("url"):
        raise ValueError("No encontré audio disponible para esa canción.")
    if info.get("is_live"):
        raise ValueError("Por ahora solo reproduzco canciones, no transmisiones en vivo.")
    return info


async def resolve(link: str) -> dict:
    kind, url = normalize_link(link)
    query = url
    if kind == "spotify":
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get("https://open.spotify.com/oembed", params={"url": url}) as response:
                response.raise_for_status()
                metadata = await response.json()
        title = metadata.get("title")
        if not title:
            raise ValueError("Spotify no devolvió el nombre de esa canción.")
        query = f"ytsearch1:{title} audio"
    return await asyncio.wait_for(asyncio.to_thread(extract, query), timeout=90)
