import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import discord

import bot
from nickname import NicknameManager, playback_nickname
from state import NicknameStore, RadioStore


def member(nickname="Mi bot", *, permission=True):
    return SimpleNamespace(nick=nickname, edit=AsyncMock(),
                           guild_permissions=SimpleNamespace(change_nickname=permission))


async def wait_for(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.001)


class NicknameFormatTests(unittest.TestCase):
    def test_titles_remain_readable_without_markdown_escaping_or_control_characters(self):
        self.assertEqual(playback_nickname("  AC/DC\n\tBack\u200b in Black  "), "🎵 AC/DC Back in Black")
        self.assertEqual(playback_nickname("FM Aspen 102.3", radio=True), "📻 FM Aspen 102.3")
        self.assertEqual(playback_nickname(None), "🎵 Canción")

    def test_long_unicode_titles_fit_discord_and_keep_an_ellipsis(self):
        for title in ("Long song name " * 10, "🎸" * 40, "é" * 40):
            with self.subTest(title=title):
                nickname = playback_nickname(title)
                self.assertTrue(nickname.endswith("…"))
                self.assertLessEqual(len(nickname), 32)
                self.assertLessEqual(len(nickname.encode("utf-16-le")), 64)


class NicknameStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "nicknames.json"
        self.store = NicknameStore(self.path)

    def test_original_custom_and_absent_nicknames_survive_restart(self):
        self.store.remember(123, "Mi bot")
        self.store.remember(124, None)
        self.store.remember(123, "🎵 Later song")
        self.assertEqual(NicknameStore(self.path).entries, {"123": "Mi bot", "124": None})
        self.store.remove(123)
        self.assertEqual(NicknameStore(self.path).entries, {"124": None})

    def test_failed_atomic_write_preserves_previous_originals(self):
        self.store.remember(123, None)
        with patch("state.os.replace", side_effect=PermissionError):
            with self.assertRaisesRegex(ValueError, "apodos originales"):
                self.store.remember(124, "Other bot")
        self.assertEqual(self.store.entries, {"123": None})
        self.assertEqual(NicknameStore(self.path).entries, {"123": None})

    def test_invalid_state_is_preserved_for_repair(self):
        for data in ("{broken", json.dumps({"123": 12}), json.dumps({"0": None})):
            with self.subTest(data=data):
                self.path.write_text(data, encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "conservé"):
                    NicknameStore(self.path)
                self.assertEqual(self.path.read_text(encoding="utf-8"), data)


class NicknameManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "nicknames.json"
        self.store = NicknameStore(self.path)
        self.member = member()
        self.guild = SimpleNamespace(id=123, me=self.member)
        self.manager = NicknameManager(self.store, interval=0, retry=0.01)

    async def asyncTearDown(self):
        await self.manager.close()
        self.temp.cleanup()

    async def drained(self):
        await wait_for(lambda: not self.manager.pending and not self.manager.tasks)

    async def test_restores_original_even_when_gateway_cache_is_stale(self):
        self.manager.show(self.guild, "Song")
        await self.drained()
        self.assertEqual(self.store.entries, {"123": "Mi bot"})
        self.manager.restore(self.guild)
        await self.drained()
        self.assertEqual([call.kwargs["nick"] for call in self.member.edit.await_args_list],
                         ["🎵 Song", "Mi bot"])
        self.assertEqual(NicknameStore(self.path).entries, {})

    async def test_restores_none_when_the_bot_had_no_server_nickname(self):
        self.member.nick = None
        self.manager.show(self.guild, "Radio", radio=True)
        await self.drained()
        self.manager.restore(self.guild)
        await self.drained()
        self.assertIsNone(self.member.edit.await_args.kwargs["nick"])
        self.assertNotIn("123", self.store.entries)

    async def test_slow_edit_coalesces_skips_and_keeps_the_latest_title(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def edit(**kwargs):
            if kwargs["nick"] == "🎵 First":
                started.set()
                await release.wait()

        self.member.edit.side_effect = edit
        self.manager.show(self.guild, "First")
        await asyncio.wait_for(started.wait(), 1)
        self.manager.show(self.guild, "Skipped")
        self.manager.show(self.guild, "Last")
        release.set()
        await self.drained()
        self.assertEqual([call.kwargs["nick"] for call in self.member.edit.await_args_list],
                         ["🎵 First", "🎵 Last"])
        self.assertEqual(self.store.entries["123"], "Mi bot")

    async def test_stop_during_inflight_edit_restores_instead_of_leaving_song_title(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def edit(**kwargs):
            if kwargs["nick"] == "🎵 Song":
                started.set()
                await release.wait()

        self.member.edit.side_effect = edit
        self.manager.show(self.guild, "Song")
        await asyncio.wait_for(started.wait(), 1)
        self.manager.restore(self.guild)
        release.set()
        await self.drained()
        self.assertEqual(self.member.edit.await_args.kwargs["nick"], "Mi bot")
        self.assertEqual(self.store.entries, {})

    async def test_new_song_during_restoration_keeps_original_for_next_stop(self):
        self.manager.show(self.guild, "First")
        await self.drained()
        started, release = asyncio.Event(), asyncio.Event()

        async def edit(**kwargs):
            if kwargs["nick"] == "Mi bot":
                started.set()
                await release.wait()

        self.member.edit.side_effect = edit
        self.manager.restore(self.guild)
        await asyncio.wait_for(started.wait(), 1)
        self.manager.show(self.guild, "Second")
        release.set()
        await self.drained()
        self.assertEqual(self.member.edit.await_args.kwargs["nick"], "🎵 Second")
        self.assertEqual(self.store.entries["123"], "Mi bot")
        self.manager.restore(self.guild)
        await self.drained()
        self.assertEqual(self.member.edit.await_args.kwargs["nick"], "Mi bot")

    async def test_permission_added_later_applies_current_title_without_new_command(self):
        self.member.guild_permissions.change_nickname = False
        self.manager.show(self.guild, "Song")
        await wait_for(lambda: 123 in self.manager.failures)
        self.member.edit.assert_not_awaited()
        self.assertEqual(self.store.entries, {})
        self.member.guild_permissions.change_nickname = True
        await self.drained()
        self.assertEqual(self.member.edit.await_args.kwargs["nick"], "🎵 Song")

    async def test_http_failure_retries_without_losing_original(self):
        error = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "No permission")
        self.member.edit.side_effect = error
        self.manager.show(self.guild, "Song")
        await wait_for(lambda: 123 in self.manager.failures)
        self.assertEqual(self.store.entries["123"], "Mi bot")
        self.member.edit.side_effect = None
        await self.drained()
        self.assertEqual(self.manager.applied[123], "🎵 Song")

    async def test_storage_failure_never_changes_nickname_without_a_saved_original(self):
        with patch.object(self.store, "remember", side_effect=ValueError("Unwritable volume")):
            self.manager.show(self.guild, "Song")
            await wait_for(lambda: 123 in self.manager.failures)
            self.member.edit.assert_not_awaited()
        await self.drained()
        self.assertEqual(NicknameStore(self.path).entries["123"], "Mi bot")

    async def test_restart_restores_inactive_guild_and_preserves_active_radio_original(self):
        self.store.remember(123, "Mi bot")
        self.member.nick = "📻 Test Radio"
        active_member = member("📻 Other Radio")
        active_guild = SimpleNamespace(id=124, me=active_member)
        self.store.remember(124, None)
        await self.manager.close()
        self.manager = NicknameManager(NicknameStore(self.path), interval=0, retry=0.01)
        self.manager.restore_inactive([self.guild, active_guild], {124})
        await self.drained()
        self.assertEqual(self.member.edit.await_args.kwargs["nick"], "Mi bot")
        active_member.edit.assert_not_awaited()
        self.manager.show(active_guild, "Other Radio", radio=True)
        await self.drained()
        self.assertEqual(self.manager.store.entries, {"124": None})
        self.manager.restore(active_guild)
        await self.drained()
        self.assertIsNone(active_member.edit.await_args.kwargs["nick"])

    async def test_servers_have_independent_titles_and_originals(self):
        other_member = member(None)
        other_guild = SimpleNamespace(id=124, me=other_member)
        self.manager.show(self.guild, "Song")
        self.manager.show(other_guild, "Station", radio=True)
        await self.drained()
        self.manager.restore(self.guild)
        await self.drained()
        self.assertEqual(other_member.edit.await_args.kwargs["nick"], "📻 Station")
        self.assertEqual(self.store.entries, {"124": None})

    async def test_duplicate_titles_do_not_make_extra_requests(self):
        self.manager.show(self.guild, "Song")
        await self.drained()
        self.manager.show(self.guild, "Song")
        await self.drained()
        self.assertEqual(self.member.edit.await_count, 1)

    async def test_throttle_uses_newest_title_after_waiting(self):
        self.manager.interval = 0.03
        self.manager.show(self.guild, "First")
        await self.drained()
        self.manager.show(self.guild, "Skipped")
        await asyncio.sleep(0)
        self.manager.show(self.guild, "Last")
        await self.drained()
        self.assertEqual([call.kwargs["nick"] for call in self.member.edit.await_args_list],
                         ["🎵 First", "🎵 Last"])

    async def test_manual_base_nickname_change_between_sessions_is_preserved(self):
        self.manager.show(self.guild, "First")
        await self.drained()
        self.manager.restore(self.guild)
        await self.drained()
        self.member.nick = "Nuevo apodo"
        self.manager.observe(123)
        self.manager.show(self.guild, "Second")
        await self.drained()
        self.assertEqual(self.store.entries["123"], "Nuevo apodo")

    async def test_server_removal_cancels_pending_updates_and_removes_original(self):
        started = asyncio.Event()

        async def edit(**kwargs):
            started.set()
            await asyncio.Event().wait()

        self.member.edit.side_effect = edit
        self.manager.show(self.guild, "Song")
        await asyncio.wait_for(started.wait(), 1)
        await self.manager.forget(123)
        self.assertEqual(self.manager.pending, {})
        self.assertEqual(self.manager.tasks, {})
        self.assertEqual(NicknameStore(self.path).entries, {})


class PlaybackNicknameTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = NicknameStore(Path(self.temp.name) / "nicknames.json")
        self.manager = NicknameManager(self.store, interval=0, retry=0.01)
        self.nickname_patch = patch.object(bot, "nicknames", self.manager)
        self.nickname_patch.start()
        self.radio_patch = patch.object(bot, "radio_store", RadioStore(Path(self.temp.name) / "radio.json"))
        self.radio_patch.start()
        self.member = member()
        self.voice = MagicMock()
        self.voice.is_connected.return_value = True
        self.voice.disconnect = AsyncMock()
        self.voice.channel = SimpleNamespace(id=456)
        self.guild = SimpleNamespace(id=123, me=self.member, voice_client=self.voice)
        self.channel = SimpleNamespace(id=789, send=AsyncMock())
        self.player = None
        bot.locks[123] = asyncio.Lock()

    async def asyncTearDown(self):
        if self.player:
            await self.player.close()
        await self.manager.close()
        bot.players.clear()
        bot.locks.clear()
        bot.radio_requests.clear()
        self.radio_patch.stop()
        self.nickname_patch.stop()
        self.temp.cleanup()

    async def test_radio_song_radio_and_off_update_the_nickname_at_actual_playback(self):
        callbacks = []
        self.voice.play.side_effect = lambda source, after: callbacks.append(after)
        config = {"title": "Test Radio", "link": "https://radio.garden/listen/test/ABCD1234"}
        with patch.object(bot, "resolve_stream", new=AsyncMock(return_value="https://station.example/live")), \
                patch.object(bot, "resolve", new=AsyncMock(return_value={"title": "Actual Song", "url": "https://example.test/audio"})), \
                patch.object(bot.discord, "FFmpegPCMAudio"):
            self.player = bot.Player(self.guild, self.voice, radio=config)
            await wait_for(lambda: self.manager.applied.get(123) == "📻 Test Radio")
            self.player.enqueue("song", self.channel)
            await wait_for(lambda: self.manager.applied.get(123) == "🎵 Actual Song")
            callbacks[1](None)
            await wait_for(lambda: len(callbacks) == 3 and self.manager.applied.get(123) == "📻 Test Radio")
            self.assertEqual(self.store.entries["123"], "Mi bot")
            self.player.set_radio(None)
            await wait_for(lambda: not self.manager.pending and not self.store.entries)
            self.assertEqual(self.member.edit.await_args.kwargs["nick"], "Mi bot")

    async def test_stop_and_audio_do_not_wait_for_a_slow_nickname_request(self):
        started = asyncio.Event()

        async def edit(**kwargs):
            started.set()
            await asyncio.Event().wait()

        self.member.edit.side_effect = edit
        with patch.object(bot, "resolve", new=AsyncMock(return_value={"title": "Song", "url": "https://example.test/audio"})), \
                patch.object(bot.discord, "FFmpegPCMAudio"):
            self.player = bot.Player(self.guild, self.voice)
            bot.players[123] = self.player
            self.player.enqueue("song", self.channel)
            await asyncio.wait_for(started.wait(), 1)
            self.voice.play.assert_called_once()
            ctx = SimpleNamespace(guild=self.guild, voice_client=self.voice, send=AsyncMock(),
                                  author=SimpleNamespace(voice=SimpleNamespace(channel=self.voice.channel)))
            await asyncio.wait_for(bot.stop_command.callback(ctx), 0.2)
            self.voice.disconnect.assert_awaited_once()
            self.assertTrue(self.player.worker.done())
            self.assertEqual(self.manager.pending[123][1], None)

    async def test_missing_nickname_permission_does_not_interrupt_music(self):
        self.member.guild_permissions.change_nickname = False
        callbacks = []
        self.voice.play.side_effect = lambda source, after: callbacks.append(after)
        with patch.object(bot, "resolve", new=AsyncMock(return_value={"title": "Song", "url": "https://example.test/audio"})), \
                patch.object(bot.discord, "FFmpegPCMAudio"):
            self.player = bot.Player(self.guild, self.voice)
            self.player.enqueue("song", self.channel)
            await wait_for(lambda: len(callbacks) == 1 and 123 in self.manager.failures)
            self.member.edit.assert_not_awaited()
            callbacks[0](None)
            await asyncio.wait_for(self.player.queue.join(), 1)
            self.voice.disconnect.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
