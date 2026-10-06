"""Update each server's bot nickname without delaying audio or voice commands."""
import asyncio
import contextlib
import logging
import unicodedata

import discord


log = logging.getLogger("astramusic.nickname")


def playback_nickname(title, *, radio=False):
    title = title if isinstance(title, str) else ""
    title = unicodedata.normalize("NFC", " ".join(title.split()))
    title = "".join(character for character in title
                    if not unicodedata.category(character).startswith("C"))
    title = title.strip() or ("Radio" if radio else "Canción")
    nickname = f"{'📻' if radio else '🎵'} {title}"
    # A conservative UTF-16 budget also fits clients that count emoji as two units.
    if len(nickname.encode("utf-16-le")) <= 64:
        return nickname
    shortened, units = [], 0
    for character in nickname:
        width = 2 if ord(character) > 0xFFFF else 1
        if units + width > 31:
            break
        shortened.append(character)
        units += width
    return "".join(shortened).rstrip() + "…"


class NicknameManager:
    def __init__(self, store, *, interval=5, retry=30):
        self.store = store
        self.interval = interval
        self.retry = retry
        self.pending = {}
        self.tasks = {}
        self.wakes = {}
        self.last_edit = {}
        self.applied = {}
        self.failures = {}

    def show(self, guild, title, *, radio=False):
        self._request(guild, playback_nickname(title, radio=radio))

    def restore(self, guild):
        if self.store and (str(guild.id) in self.store.entries or guild.id in self.pending):
            self._request(guild, None)

    def restore_inactive(self, guilds, active_ids):
        for guild in guilds:
            if guild.id not in active_ids:
                self.restore(guild)

    def observe(self, guild_id):
        # An administrator may set a different base nickname between sessions.
        if guild_id not in self.pending:
            self.applied.pop(guild_id, None)

    def _request(self, guild, nickname):
        if self.store is None:
            return
        self.pending[guild.id] = (guild, nickname)
        self.wakes.setdefault(guild.id, asyncio.Event()).set()
        task = self.tasks.get(guild.id)
        if not task or task.done():
            self.tasks[guild.id] = asyncio.create_task(self._run(guild.id))

    async def _retry(self, guild_id, reason):
        if self.failures.get(guild_id) != reason:
            log.warning("Nickname update unavailable for guild %s: %s", guild_id, reason)
            self.failures[guild_id] = reason
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self.wakes[guild_id].wait(), timeout=self.retry)

    async def _run(self, guild_id):
        loop = asyncio.get_running_loop()
        try:
            while guild_id in self.pending:
                self.wakes[guild_id].clear()
                remaining = self.interval - (loop.time() - self.last_edit.get(guild_id, float("-inf")))
                if remaining > 0:
                    await asyncio.sleep(remaining)
                # Always read the newest request after waiting or a slow HTTP edit.
                request = self.pending[guild_id]
                guild, target = request
                key = str(guild_id)
                if target is None and key not in self.store.entries:
                    if self.pending.get(guild_id) == request:
                        self.pending.pop(guild_id)
                    continue
                member = guild.me
                if member is None:
                    await self._retry(guild_id, "bot member unavailable")
                    continue
                nickname = self.store.entries[key] if target is None else target
                # The Gateway member cache can lag behind a successful REST edit.
                current = self.applied.get(guild_id, member.nick)
                try:
                    if current != nickname:
                        if not member.guild_permissions.change_nickname:
                            await self._retry(guild_id, "missing Change Nickname permission")
                            continue
                        if target is not None:
                            self.store.remember(guild_id, current)
                        try:
                            await member.edit(nick=nickname, reason="AstraMusic playback display")
                        finally:
                            self.last_edit[guild_id] = loop.time()
                        self.applied[guild_id] = nickname
                    if target is None and self.pending.get(guild_id) == request:
                        self.store.remove(guild_id)
                except (discord.HTTPException, ValueError) as error:
                    # Never expose titles, provider URLs, or HTTP response details.
                    await self._retry(guild_id, type(error).__name__)
                    continue
                self.failures.pop(guild_id, None)
                if self.pending.get(guild_id) == request:
                    self.pending.pop(guild_id)
        finally:
            if self.tasks.get(guild_id) is asyncio.current_task():
                self.tasks.pop(guild_id, None)

    async def forget(self, guild_id):
        self.pending.pop(guild_id, None)
        task = self.tasks.get(guild_id)
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for values in (self.wakes, self.last_edit, self.applied, self.failures):
            values.pop(guild_id, None)
        if self.store:
            try:
                self.store.remove(guild_id)
            except ValueError:
                self.store.entries.pop(str(guild_id), None)
                log.error("Could not remove nickname state for guild %s", guild_id)

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.pending.clear()
