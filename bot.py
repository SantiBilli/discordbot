import asyncio
import contextlib
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from media import normalize_link, resolve

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("riffito")
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None,
                   allowed_mentions=discord.AllowedMentions.none())
players = {}
locks = {}


class Player:
    def __init__(self, guild, voice):
        self.guild = guild
        self.voice = voice
        self.queue = asyncio.Queue(maxsize=50)
        self.current = None
        self.closing = False
        self.worker = asyncio.create_task(self.run())

    async def announce(self, channel, text):
        with contextlib.suppress(discord.HTTPException):
            await channel.send(text)

    async def play(self, link, channel):
        source = None
        try:
            info = await resolve(link)
            if not self.voice.is_connected():
                raise RuntimeError("Voice disconnected")
            finished = asyncio.Event()
            loop = asyncio.get_running_loop()
            errors = []

            def after(error):
                if error:
                    errors.append(error)
                loop.call_soon_threadsafe(finished.set)

            source = discord.FFmpegPCMAudio(
                info["url"],
                before_options="-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -rw_timeout 15000000",
                options="-vn -loglevel error",
            )
            self.voice.play(source, after=after)
            title = discord.utils.escape_markdown(info.get("title", "Canción"))[:180]
            await self.announce(channel, f"🎶 Sonando: **{title}**\n{info.get('webpage_url', '')}")
            await finished.wait()
            if errors:
                raise errors[0]
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Do not expose signed stream URLs or credentials in chat/logs.
            log.warning("Playback failed: %s", type(error).__name__)
            await self.announce(channel, "⚠️ No pude reproducir esa canción. Puede estar restringida o YouTube estar bloqueando la IP del VPS. Probá otro enlace; sigo con la cola.")
        finally:
            self.voice.stop()
            if source:
                source.cleanup()

    async def run(self):
        try:
            while not self.closing:
                try:
                    item = await asyncio.wait_for(self.queue.get(), timeout=120)
                except asyncio.TimeoutError:
                    async with locks[self.guild.id]:
                        if not self.queue.empty():
                            continue
                        self.closing = True
                        await self.voice.disconnect(force=True)
                        if players.get(self.guild.id) is self:
                            players.pop(self.guild.id, None)
                    return
                self.current = asyncio.create_task(self.play(*item))
                try:
                    await self.current
                except asyncio.CancelledError:
                    if self.closing:
                        return
                finally:
                    self.current = None
                    self.queue.task_done()
        finally:
            self.voice.stop()

    async def close(self):
        self.closing = True
        self.worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.worker
        await self.voice.disconnect(force=True)


def author_channel(ctx):
    voice = getattr(ctx.author, "voice", None)
    if not voice or not voice.channel:
        raise commands.CheckFailure("Entrá a un canal de voz primero.")
    if isinstance(voice.channel, discord.StageChannel):
        raise commands.CheckFailure("Usá un canal de voz común, no un escenario.")
    if ctx.voice_client and ctx.voice_client.channel != voice.channel:
        raise commands.CheckFailure("Tenés que estar en el mismo canal de voz que yo.")
    return voice.channel


@bot.command(name="p", aliases=["play"])
@commands.guild_only()
@commands.cooldown(1, 3, commands.BucketType.user)
async def play_command(ctx, *, link: str):
    """Enqueue a track; extraction happens in the player, so stop remains responsive."""
    _, link = normalize_link(link)
    lock = locks.setdefault(ctx.guild.id, asyncio.Lock())
    async with lock:
        channel = author_channel(ctx)
        player = players.get(ctx.guild.id)
        if player and not player.voice.is_connected():
            await player.close()
            players.pop(ctx.guild.id, None)
            player = None
        if not player:
            permissions = channel.permissions_for(ctx.guild.me)
            if not permissions.connect or not permissions.speak:
                raise commands.CheckFailure("Necesito permisos Conectar y Hablar en ese canal.")
            try:
                voice = await channel.connect(timeout=30, self_deaf=True)
            except Exception:
                if ctx.voice_client:
                    await ctx.voice_client.disconnect(force=True)
                raise
            player = players[ctx.guild.id] = Player(ctx.guild, voice)
        if player.queue.full():
            await ctx.send("La cola está llena (50 canciones). Esperá o usá !skip.")
            return
        player.queue.put_nowait((link, ctx.channel))
        await ctx.send("🎧 Agregada a la cola. Buscando audio…" if not player.current else "🎧 Agregada a la cola.")


@bot.command(name="skip")
@commands.guild_only()
async def skip_command(ctx):
    async with locks.setdefault(ctx.guild.id, asyncio.Lock()):
        author_channel(ctx)
        player = players.get(ctx.guild.id)
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
        player = players.pop(ctx.guild.id, None)
        if player:
            await player.close()
        elif ctx.voice_client:
            await ctx.voice_client.disconnect(force=True)
        await ctx.send("⏹️ Detenido: vacié la cola y salí del canal.")


@bot.command(name="help", aliases=["ayuda"])
async def help_command(ctx):
    await ctx.send("🎧 **Riffito**\n`!p <link>` — reproduce o agrega a la cola (YouTube/Spotify).\n`!skip` — siguiente canción.\n`!stop` — vacía la cola y desconecta.\nSpotify busca una coincidencia en YouTube; solo canciones individuales. Me desconecto tras 2 minutos sin música.")


@bot.event
async def on_ready():
    log.info("Riffito conectado como %s", bot.user)


@bot.event
async def on_voice_state_update(member, before, after):
    if bot.user and member.id == bot.user.id and before.channel and not after.channel:
        async with locks.setdefault(member.guild.id, asyncio.Lock()):
            player = players.get(member.guild.id)
            if player and not player.voice.is_connected():
                players.pop(member.guild.id, None)
                await player.close()


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    original = getattr(error, "original", error)
    if isinstance(original, commands.MissingRequiredArgument):
        message = "Uso: `!p <link de YouTube o Spotify>`."
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
