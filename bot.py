import asyncio
import contextlib
import logging
import os
import subprocess

import discord
from discord.ext import commands
from dotenv import load_dotenv

from media import normalize_link, resolve
from nickname import NicknameManager
from radio import get_station, normalize_radio_link, resolve_stream
from state import NicknameStore, RadioStore

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("astramusic")
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None,
                   allowed_mentions=discord.AllowedMentions.none())
players = {}
locks = {}
radio_requests = {}
radio_store = RadioStore(os.getenv("RADIO_STATE_FILE", "data/radio.json"))
try:
    nickname_store = NicknameStore(radio_store.path.with_suffix(".nicknames.json"))
except RuntimeError:
    nickname_store = None
    log.error("Could not read original nicknames; automatic nicknames disabled. Repair the preserved nickname state file.")
nicknames = NicknameManager(nickname_store)
IDLE_TIMEOUT = 120
RADIO_RETRY_INITIAL = 5
RADIO_RETRY_MAX = 60
VOICE_CHECK_INTERVAL = 5


def forget_removed_radio(guild_id):
    try:
        radio_store.remove(guild_id)
        return True
    except ValueError:
        # A kick must stop playback even if the volume has become unwritable.
        radio_store.entries.pop(str(guild_id), None)
        log.error("Could not persist radio shutdown after removal for guild %s", guild_id)
        return False


class RadioVoiceClient(discord.VoiceClient):
    async def on_voice_state_update(self, data):
        # discord.py 2.7.1 sets this flag for its own disconnect/reconnect flow.
        # Read it before super consumes it; the Member event runs too late.
        external = data["channel_id"] is None and not self._connection._expecting_disconnect
        player = players.get(self.guild.id)
        if (not external or not player or player.closing
                or (player.voice is not self and self.guild.voice_client is not self)):
            await super().on_voice_state_update(data)
            return

        # Stop the worker before awaiting the library, so it cannot rejoin first.
        player.closing = True
        player.worker.cancel()
        radio_requests[self.guild.id] = radio_requests.get(self.guild.id, 0) + 1
        had_radio = bool(player.radio)
        saved = True
        async with locks.setdefault(self.guild.id, asyncio.Lock()):
            if players.get(self.guild.id) is player:
                saved = forget_removed_radio(self.guild.id)
                players.pop(self.guild.id, None)
                player.radio = None
                player.radio_status = "desactivada"
            try:
                await super().on_voice_state_update(data)
            finally:
                # The library has already disconnected and cleaned up this client.
                await player.close(disconnect=False)
        if had_radio:
            message = "📻 Radio desactivada porque me desconectaron del canal. Para volver a activarla, usá !radio <enlace>."
            if not saved:
                message += " No pude guardar la desactivación: revisá los permisos del volumen antes de reiniciar."
            await player.announce(player.radio_channel, message)


class PlaybackQueue(asyncio.Queue):
    def __init__(self, wake, **kwargs):
        super().__init__(**kwargs)
        self.wake = wake

    def put_nowait(self, item):
        super().put_nowait(item)
        self.wake.set()


class Player:
    def __init__(self, guild, voice, *, radio=None, radio_channel=None):
        self.guild = guild
        self.voice = voice
        self.wake = asyncio.Event()
        self.queue = PlaybackQueue(self.wake, maxsize=50)
        self.current = None
        self.current_kind = None
        self.closing = False
        self.reconnecting = False
        self.radio = radio
        self.radio_channel = radio_channel
        self.radio_status = "conectando" if radio else "desactivada"
        self.worker = asyncio.create_task(self.run())

    async def announce(self, channel, text):
        if channel:
            with contextlib.suppress(discord.HTTPException):
                await channel.send(text)

    def interrupt_radio(self):
        if self.current_kind == "radio" and self.current and not self.current.done():
            self.current.cancel()
        self.wake.set()

    def enqueue(self, link, channel):
        self.queue.put_nowait((link, channel))
        self.interrupt_radio()

    def set_radio(self, config, channel=None):
        self.radio = config
        self.radio_channel = channel
        self.radio_status = ("pausada por canciones" if self.current_kind == "track" else "conectando") if config else "desactivada"
        self.interrupt_radio()

    async def ensure_voice(self):
        if self.closing:
            raise asyncio.CancelledError
        if self.voice and self.voice.is_connected():
            return
        if not self.radio:
            raise ConnectionError("Voice disconnected")
        if not bot.is_ready():
            await bot.wait_until_ready()
        async with locks.setdefault(self.guild.id, asyncio.Lock()):
            if self.closing or not self.radio:
                raise asyncio.CancelledError
            if self.voice and self.voice.is_connected():
                return
            channel = self.guild.get_channel(self.radio["voice_channel_id"])
            if not isinstance(channel, discord.VoiceChannel):
                raise ValueError("Radio voice channel unavailable")
            check_permissions(channel, self.guild)
            self.reconnecting = True
            try:
                existing = self.guild.voice_client
                if existing:
                    await existing.disconnect(force=True)
                self.voice = await channel.connect(timeout=30, reconnect=True, self_deaf=True, cls=RadioVoiceClient)
            finally:
                self.reconnecting = False

    async def audio(self, info, channel=None, *, live=False):
        source = None
        voice = self.voice
        try:
            if not voice or not voice.is_connected():
                raise ConnectionError("Voice disconnected")
            finished = asyncio.Event()
            loop = asyncio.get_running_loop()
            errors = []

            def after(error):
                if error:
                    errors.append(error)
                loop.call_soon_threadsafe(finished.set)

            before = "-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -rw_timeout 15000000"
            if live:
                before += " -reconnect_at_eof 1 -reconnect_on_network_error 1 -reconnect_on_http_error 5xx"
                before += " -protocol_whitelist http,https,tcp,tls,crypto"
            source = discord.FFmpegPCMAudio(info["url"], before_options=before,
                                           options="-vn -loglevel error", stderr=subprocess.DEVNULL)
            voice.play(source, after=after)
            nicknames.show(self.guild, info.get("title"), radio=live)
            if live:
                self.radio_status = "sonando"
            else:
                title = discord.utils.escape_markdown(info.get("title", "Canción"))[:180]
                await self.announce(channel, f"🎶 Sonando: **{title}**\n{info.get('webpage_url', '')}")
            while not finished.is_set():
                try:
                    await asyncio.wait_for(finished.wait(), timeout=VOICE_CHECK_INTERVAL)
                except asyncio.TimeoutError:
                    if not voice.is_connected():
                        raise ConnectionError("Voice disconnected")
            if errors:
                raise errors[0]
        finally:
            if voice:
                voice.stop()
            if source:
                source.cleanup()

    async def play(self, link, channel):
        try:
            nicknames.show(self.guild, "Buscando audio…")
            info = await resolve(link)
            await self.ensure_voice()
            await self.audio(info, channel)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Do not expose signed stream URLs or credentials in chat/logs.
            log.warning("Playback failed: %s", type(error).__name__)
            await self.announce(channel, "⚠️ No pude reproducir esa canción. Puede estar restringida o YouTube estar bloqueando la IP del VPS. Probá otro enlace; sigo con la cola.")

    async def play_radio(self, config):
        delay = RADIO_RETRY_INITIAL
        warned = False
        while not self.closing and self.radio == config:
            started = asyncio.get_running_loop().time()
            try:
                self.radio_status = "reconectando" if warned else "conectando"
                nicknames.show(self.guild, "Reconectando…" if warned else "Conectando…", radio=True)
                await self.ensure_voice()
                url = await asyncio.wait_for(resolve_stream(config["link"]), timeout=30)
                await self.audio({"url": url, "title": config["title"]}, live=True)
                raise ConnectionError("Radio stream ended")
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning("Radio failed for guild %s: %s", self.guild.id, type(error).__name__)
                self.radio_status = "reconectando"
                nicknames.show(self.guild, "Reconectando…", radio=True)
                if not warned:
                    await self.announce(self.radio_channel, "⚠️ La radio se cortó o no está disponible. Voy a intentar reconectarla automáticamente; podés detenerla con !radio off o !stop.")
                    warned = True
                if asyncio.get_running_loop().time() - started >= 60:
                    delay = RADIO_RETRY_INITIAL
                await asyncio.sleep(delay)
                delay = min(delay * 2, RADIO_RETRY_MAX)

    async def run(self):
        try:
            while not self.closing:
                self.wake.clear()
                queued = False
                if not self.queue.empty():
                    item = self.queue.get_nowait()
                    queued = True
                    self.current_kind = "track"
                    if self.radio:
                        self.radio_status = "pausada por canciones"
                    self.current = asyncio.create_task(self.play(*item))
                elif self.radio:
                    self.current_kind = "radio"
                    self.current = asyncio.create_task(self.play_radio(dict(self.radio)))
                else:
                    nicknames.restore(self.guild)
                    try:
                        await asyncio.wait_for(self.wake.wait(), timeout=IDLE_TIMEOUT)
                    except asyncio.TimeoutError:
                        async with locks.setdefault(self.guild.id, asyncio.Lock()):
                            if not self.queue.empty() or self.radio:
                                continue
                            self.closing = True
                            if self.voice:
                                await self.voice.disconnect(force=True)
                            if players.get(self.guild.id) is self:
                                players.pop(self.guild.id, None)
                        return
                    continue
                try:
                    await self.current
                except asyncio.CancelledError:
                    if self.closing:
                        return
                finally:
                    self.current = None
                    self.current_kind = None
                    if queued:
                        self.queue.task_done()
        finally:
            if self.voice:
                self.voice.stop()
            nicknames.restore(self.guild)

    async def close(self, *, disconnect=True):
        self.closing = True
        self.worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.worker
        while not self.queue.empty():
            self.queue.get_nowait()
            self.queue.task_done()
        if disconnect and self.voice:
            await self.voice.disconnect(force=True)


def author_channel(ctx):
    voice = getattr(ctx.author, "voice", None)
    if not voice or not voice.channel:
        raise commands.CheckFailure("Entrá a un canal de voz primero.")
    if isinstance(voice.channel, discord.StageChannel):
        raise commands.CheckFailure("Usá un canal de voz común, no un escenario.")
    player = players.get(ctx.guild.id)
    config = player.radio if player and player.radio else radio_store.get(ctx.guild.id)
    if config and voice.channel.id != config["voice_channel_id"]:
        raise commands.CheckFailure("Tenés que estar en el canal de voz configurado para la radio.")
    if ctx.voice_client and ctx.voice_client.channel != voice.channel:
        raise commands.CheckFailure("Tenés que estar en el mismo canal de voz que yo.")
    return voice.channel


def check_permissions(channel, guild):
    permissions = channel.permissions_for(guild.me)
    if not permissions.connect or not permissions.speak:
        raise commands.CheckFailure("Necesito permisos Conectar y Hablar en ese canal.")


@bot.command(name="p", aliases=["play"])
@commands.guild_only()
@commands.cooldown(1, 3, commands.BucketType.user)
async def play_command(ctx, *, link: str):
    """Enqueue a track; extraction happens in the player, so stop remains responsive."""
    _, link = normalize_link(link)
    async with locks.setdefault(ctx.guild.id, asyncio.Lock()):
        channel = author_channel(ctx)
        player = players.get(ctx.guild.id)
        if player and not player.radio and (not player.voice or not player.voice.is_connected()):
            await player.close()
            players.pop(ctx.guild.id, None)
            player = None
        if not player:
            check_permissions(channel, ctx.guild)
            try:
                voice = await channel.connect(timeout=30, reconnect=True, self_deaf=True, cls=RadioVoiceClient)
            except Exception:
                if ctx.voice_client:
                    await ctx.voice_client.disconnect(force=True)
                raise
            player = players[ctx.guild.id] = Player(ctx.guild, voice)
        if player.queue.full():
            await ctx.send("La cola está llena (50 canciones). Esperá o usá !skip.")
            return
        player.enqueue(link, ctx.channel)
        await ctx.send("🎧 Agregada a la cola. Buscando audio…" if not player.current else "🎧 Agregada a la cola.")


@bot.command(name="radio")
@commands.guild_only()
async def radio_command(ctx, *, value: str = "estado"):
    action = value.strip().lower()
    if action in {"estado", "status"}:
        player = players.get(ctx.guild.id)
        config = player.radio if player and player.radio else radio_store.get(ctx.guild.id)
        if not config:
            await ctx.send("📻 Radio desactivada. Uso: `!radio <enlace de Radio Garden>`.")
            return
        title = discord.utils.escape_markdown(config["title"])
        status = player.radio_status if player and player.radio else "pendiente de reconexión"
        await ctx.send(f"📻 **{title}** — {status}. Modo 24/7 activo.\n{config['link']}")
        return
    if action == "off":
        async with locks.setdefault(ctx.guild.id, asyncio.Lock()):
            author_channel(ctx)
            radio_requests[ctx.guild.id] = radio_requests.get(ctx.guild.id, 0) + 1
            radio_store.remove(ctx.guild.id)
            player = players.get(ctx.guild.id)
            if player:
                player.set_radio(None)
            else:
                nicknames.restore(ctx.guild)
            await ctx.send("📻 Radio desactivada. La cola de canciones continúa; no retomaré la radio al reiniciar.")
        return

    _, link = normalize_radio_link(value)
    async with locks.setdefault(ctx.guild.id, asyncio.Lock()):
        voice_channel = author_channel(ctx)
        check_permissions(voice_channel, ctx.guild)
        request = radio_requests[ctx.guild.id] = radio_requests.get(ctx.guild.id, 0) + 1
    station = await get_station(link)
    async with locks.setdefault(ctx.guild.id, asyncio.Lock()):
        if radio_requests.get(ctx.guild.id) != request:
            await ctx.send("La solicitud de radio quedó cancelada por un comando posterior.")
            return
        voice_channel = author_channel(ctx)
        check_permissions(voice_channel, ctx.guild)
        config = {**station, "voice_channel_id": voice_channel.id, "text_channel_id": ctx.channel.id}
        radio_store.set(ctx.guild.id, config)
        player = players.get(ctx.guild.id)
        if player:
            player.set_radio(config, ctx.channel)
        else:
            players[ctx.guild.id] = Player(ctx.guild, ctx.voice_client, radio=config, radio_channel=ctx.channel)
        title = discord.utils.escape_markdown(station["title"])
        await ctx.send(f"📻 Radio 24/7 activada: **{title}**. Me quedo conectado aunque el canal quede vacío; la radio vuelve al terminar la cola.\n{station['link']}")


@bot.command(name="skip")
@commands.guild_only()
async def skip_command(ctx):
    async with locks.setdefault(ctx.guild.id, asyncio.Lock()):
        author_channel(ctx)
        player = players.get(ctx.guild.id)
        if player and player.current_kind == "radio":
            await ctx.send("La radio es una transmisión continua. Para apagarla, usá !radio off o !stop.")
            return
        if not player or not player.current or player.current.done():
            await ctx.send("No hay ninguna canción sonando.")
            return
        player.current.cancel()
        await ctx.send("⏭️ Pasando a la siguiente.")


@bot.command(name="stop")
@commands.guild_only()
async def stop_command(ctx):
    async with locks.setdefault(ctx.guild.id, asyncio.Lock()):
        author_channel(ctx)
        radio_requests[ctx.guild.id] = radio_requests.get(ctx.guild.id, 0) + 1
        radio_store.remove(ctx.guild.id)
        player = players.pop(ctx.guild.id, None)
        if player:
            await player.close()
        elif ctx.voice_client:
            await ctx.voice_client.disconnect(force=True)
        nicknames.restore(ctx.guild)
        await ctx.send("⏹️ Detenido: desactivé la radio, vacié la cola y salí del canal.")


@bot.command(name="help", aliases=["ayuda"])
async def help_command(ctx):
    await ctx.send("🎧 **AstraMusic**\n`!p <link>` — reproduce o agrega a la cola (YouTube/Spotify).\n`!radio <enlace de Radio Garden>` — radio 24/7 de fondo; vuelve al terminar la cola.\n`!radio estado` — emisora y estado.\n`!radio off` — desactiva la radio y conserva la cola.\n`!skip` — siguiente canción.\n`!stop` — desactiva la radio, vacía la cola y desconecta.\nSpotify busca una coincidencia en YouTube; solo canciones individuales. Sin radio, me desconecto tras 2 minutos sin música.")


@bot.event
async def on_ready():
    log.info("AstraMusic conectado como %s", bot.user)
    for guild_id in list(radio_store.entries):
        guild_id = int(guild_id)
        async with locks.setdefault(guild_id, asyncio.Lock()):
            config = radio_store.get(guild_id)
            guild = bot.get_guild(guild_id)
            if not config or not guild or guild_id in players:
                continue
            channel = guild.get_channel(config["voice_channel_id"])
            if not isinstance(channel, discord.VoiceChannel):
                log.warning("Saved radio voice channel unavailable for guild %s", guild_id)
                continue
            text_channel = guild.get_channel(config["text_channel_id"])
            players[guild_id] = Player(guild, guild.voice_client, radio=config, radio_channel=text_channel)
            log.info("Restoring radio for guild %s", guild_id)
    nicknames.restore_inactive(bot.guilds, players)


@bot.event
async def on_member_update(before, after):
    if bot.user and after.id == bot.user.id and before.nick != after.nick:
        nicknames.observe(after.guild.id)


@bot.event
async def on_voice_state_update(member, before, after):
    if not bot.user or member.id != bot.user.id:
        return
    if before.channel and after.channel and before.channel.id != after.channel.id:
        async with locks.setdefault(member.guild.id, asyncio.Lock()):
            player = players.get(member.guild.id)
            if player and player.radio and isinstance(after.channel, discord.VoiceChannel):
                config = {**player.radio, "voice_channel_id": after.channel.id}
                radio_store.set(member.guild.id, config)
                player.radio = config
    elif before.channel and not after.channel:
        async with locks.setdefault(member.guild.id, asyncio.Lock()):
            player = players.get(member.guild.id)
            if player and not player.closing and not player.reconnecting and (not player.voice or not player.voice.is_connected()):
                if player.radio:
                    player.radio_status = "reconectando"
                    if player.current_kind == "track" and player.current:
                        player.current.cancel()
                    player.wake.set()
                else:
                    players.pop(member.guild.id, None)
                    await player.close()


@bot.event
async def on_guild_remove(guild):
    async with locks.setdefault(guild.id, asyncio.Lock()):
        radio_requests[guild.id] = radio_requests.get(guild.id, 0) + 1
        forget_removed_radio(guild.id)
        player = players.pop(guild.id, None)
        if player:
            player.radio = None
            await player.close()
        await nicknames.forget(guild.id)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    original = getattr(error, "original", error)
    if isinstance(original, commands.MissingRequiredArgument):
        message = "Uso: `!p <link de YouTube o Spotify>` o `!radio <enlace de Radio Garden>`."
    elif isinstance(original, commands.CommandOnCooldown):
        message = "Esperá unos segundos antes de agregar otra canción."
    elif isinstance(original, commands.NoPrivateMessage):
        message = "Usá los comandos dentro de tu servidor."
    elif isinstance(original, (commands.CheckFailure, ValueError)):
        message = str(original)
    else:
        log.warning("Command failed: %s", type(original).__name__)
        message = "No pude completar el comando. Revisá permisos y conexión de voz, e intentá otra vez."
    with contextlib.suppress(discord.HTTPException):
        await ctx.send(message)


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token or token == "pega_el_token_del_bot_aca":
        raise SystemExit("Falta DISCORD_TOKEN. Configuralo en Dokploy o en .env.")
    bot.run(token, log_handler=None)
