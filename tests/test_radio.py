import asyncio
import json
import socket
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import discord

import bot
import radio
from state import RadioStore

LINK = "https://radio.garden/listen/test-radio/ABCD1234"
CONFIG = {"link": LINK, "title": "Test Radio", "voice_channel_id": 456, "text_channel_id": 789}


async def blocked_stream(link):
    await asyncio.Event().wait()


def response(status=200, *, data=None, headers=None):
    result = MagicMock()
    result.__aenter__.return_value = result
    result.status = status
    result.headers = headers or {}
    result.json = AsyncMock(return_value=data)
    if status >= 400:
        result.raise_for_status.side_effect = aiohttp.ClientError("unavailable")
    return result


def session_with(*responses):
    session = MagicMock()
    session.__aenter__.return_value = session
    session.get.side_effect = responses
    return session


class RadioLinkTests(unittest.TestCase):
    def test_normalizes_shared_station_link(self):
        self.assertEqual(radio.normalize_radio_link("<https://www.radio.garden/listen/test-radio/ABCD1234/?r=1>"),
                         ("ABCD1234", LINK))

    def test_rejects_other_hosts_and_city_links(self):
        for value in ["http://radio.garden/listen/test/ABCD1234",
                      "https://radio.garden.evil.test/listen/test/ABCD1234",
                      "https://user@radio.garden/listen/test/ABCD1234",
                      "https://radio.garden:443/listen/test/ABCD1234",
                      "https://radio.garden/visit/city/ABCD1234",
                      "https://radio.garden/listen/test/../../ABCD1234",
                      "file:///radio.mp3", "https://localhost/radio.mp3"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                radio.normalize_radio_link(value)


class RadioResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetches_station_metadata_from_fixed_api(self):
        session = session_with(response(data={"data": {"title": " Radio Name "}}))
        with patch.object(radio.aiohttp, "ClientSession", return_value=session):
            self.assertEqual(await radio.get_station(LINK), {"link": LINK, "title": "Radio Name"})
        session.get.assert_called_once_with(radio.API_BASE + "/channel/ABCD1234", allow_redirects=False)

    async def test_unavailable_or_invalid_metadata_is_a_friendly_error(self):
        for result in [response(404), response(data={"error": "Not found"}),
                       response(data={"data": {"title": None}})]:
            with patch.object(radio.aiohttp, "ClientSession", return_value=session_with(result)):
                with self.assertRaisesRegex(ValueError, "No pude obtener"):
                    await radio.get_station(LINK)

    async def test_follows_redirect_and_releases_live_response(self):
        stream = "https://station.example/live.mp3?temporary=1"
        final = response(headers={"Content-Type": "audio/mpeg"})
        session = session_with(response(302, headers={"Location": stream}), final)
        with patch.object(radio.aiohttp, "ClientSession", return_value=session), \
                patch.object(radio, "validate_stream_url", new=AsyncMock()) as validator:
            self.assertEqual(await radio.resolve_stream(LINK), stream)
        validator.assert_awaited_once_with(stream)
        final.__aexit__.assert_awaited_once()
        final.json.assert_not_awaited()

    async def test_does_not_accept_html_as_audio(self):
        session = session_with(response(302, headers={"Location": "https://station.example/"}),
                               response(headers={"Content-Type": "text/html; charset=utf-8"}))
        with patch.object(radio.aiohttp, "ClientSession", return_value=session), \
                patch.object(radio, "validate_stream_url", new=AsyncMock()):
            with self.assertRaisesRegex(ValueError, "stream de audio"):
                await radio.resolve_stream(LINK)

    async def test_redirects_have_a_limit(self):
        session = session_with(*(response(302, headers={"Location": "https://station.example/loop"})
                                 for _ in range(6)))
        with patch.object(radio.aiohttp, "ClientSession", return_value=session), \
                patch.object(radio, "validate_stream_url", new=AsyncMock()):
            with self.assertRaisesRegex(ValueError, "demasiadas"):
                await radio.resolve_stream(LINK)

    async def test_rejects_private_destinations_and_unsafe_protocols(self):
        loop = asyncio.get_running_loop()
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 8000))]
        with patch.object(loop, "getaddrinfo", new=AsyncMock(return_value=addresses)):
            with self.assertRaisesRegex(ValueError, "pública"):
                await radio.validate_stream_url("http://station.example:8000/live.mp3")
        for url in ["file:///etc/passwd", "ftp://station.example/live",
                    "https://user:pass@station.example/live"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                await radio.validate_stream_url(url)


class RadioStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "data" / "radio.json"
        self.store = RadioStore(self.path)

    def test_restores_preferences_after_restart_and_isolates_guilds(self):
        self.store.set(123, CONFIG)
        self.store.set(124, {**CONFIG, "voice_channel_id": 999})
        restored = RadioStore(self.path)
        self.assertEqual(restored.get(123), CONFIG)
        restored.remove(123)
        self.assertIsNone(RadioStore(self.path).get(123))
        self.assertEqual(RadioStore(self.path).get(124)["voice_channel_id"], 999)
        self.assertNotIn("url", json.loads(self.path.read_text())["124"])

    def test_failed_atomic_write_preserves_previous_configuration(self):
        self.store.set(123, CONFIG)
        with patch("state.os.replace", side_effect=PermissionError):
            with self.assertRaisesRegex(ValueError, "volumen de Docker"):
                self.store.set(123, {**CONFIG, "title": "Replacement"})
        self.assertEqual(self.store.get(123), CONFIG)
        self.assertEqual(RadioStore(self.path).get(123), CONFIG)

    def test_corrupt_state_is_preserved_for_repair(self):
        self.path.parent.mkdir()
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "conservé"):
            RadioStore(self.path)
        self.assertEqual(self.path.read_text(), "{broken")


class RadioPlayerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RadioStore(Path(self.temp.name) / "radio.json")
        self.store_patch = patch.object(bot, "radio_store", self.store)
        self.store_patch.start()
        self.voice = MagicMock()
        self.voice.is_connected.return_value = True
        self.voice.disconnect = AsyncMock()
        self.voice_channel = MagicMock(spec=discord.VoiceChannel)
        self.voice_channel.id = 456
        self.voice_channel.connect = AsyncMock(return_value=self.voice)
        self.voice_channel.permissions_for.return_value = SimpleNamespace(connect=True, speak=True)
        self.voice.channel = self.voice_channel
        self.text = SimpleNamespace(id=789, send=AsyncMock())
        self.guild = SimpleNamespace(id=123, me=object(), voice_client=self.voice,
                                     get_channel=lambda channel_id: self.voice_channel if channel_id == 456 else self.text)
        self.ctx = SimpleNamespace(guild=self.guild, channel=self.text, voice_client=self.voice,
                                   author=SimpleNamespace(voice=SimpleNamespace(channel=self.voice_channel)),
                                   send=self.text.send)
        self.created = []
        bot.locks[123] = asyncio.Lock()

    async def asyncTearDown(self):
        for player in set(self.created + list(bot.players.values())):
            await player.close()
        bot.players.clear()
        bot.locks.clear()
        bot.radio_requests.clear()
        self.store_patch.stop()
        self.temp.cleanup()

    def player(self, *, radio_config=CONFIG, voice=None):
        player = bot.Player(self.guild, voice or self.voice, radio=dict(radio_config) if radio_config else None,
                            radio_channel=self.text)
        self.created.append(player)
        bot.players[123] = player
        return player

    def protocol(self, *, expected_disconnect=False):
        # Exercise our real protocol hook without starting sockets or Discord.
        client = object.__new__(bot.RadioVoiceClient)
        client.channel = self.voice_channel
        self.voice_channel.guild = self.guild
        client._player = None
        client._connection = MagicMock()
        client._connection._expecting_disconnect = expected_disconnect
        client._connection.is_connected.return_value = True
        client._connection.voice_state_update = AsyncMock()
        client.disconnect = AsyncMock()
        return client

    async def wait_for(self, predicate):
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(0.001)

    async def test_song_interrupts_radio_and_radio_returns_after_queue(self):
        calls = []

        async def audio(_player, info, channel=None, *, live=False):
            calls.append("radio" if live else info["title"])
            if live:
                await asyncio.Event().wait()

        with patch.object(bot, "resolve_stream", new=AsyncMock(return_value="https://station.example/live")), \
                patch.object(bot, "resolve", new=AsyncMock(side_effect=lambda link: {"title": link})), \
                patch.object(bot.Player, "audio", new=audio):
            player = self.player()
            await self.wait_for(lambda: calls == ["radio"])
            player.enqueue("first", self.text)
            player.enqueue("second", self.text)
            await self.wait_for(lambda: calls == ["radio", "first", "second", "radio"])
            await asyncio.wait_for(player.queue.join(), 1)
            self.assertFalse(player.closing)
            self.voice.disconnect.assert_not_awaited()

    async def test_retries_clean_eof_and_audio_failure_without_chat_spam(self):
        plays = []

        def play(source, after):
            plays.append(source)
            if len(plays) == 1:
                after(None)
            elif len(plays) == 2:
                after(RuntimeError("audio failure"))

        self.voice.play.side_effect = play
        with patch.object(bot, "RADIO_RETRY_INITIAL", 0.005), patch.object(bot, "RADIO_RETRY_MAX", 0.01), \
                patch.object(bot, "resolve_stream", new=AsyncMock(return_value="https://station.example/live")) as resolver, \
                patch.object(bot.discord, "FFmpegPCMAudio") as source:
            player = self.player()
            await self.wait_for(lambda: len(plays) == 3)
            self.assertEqual(resolver.await_count, 3)
            self.assertEqual(self.text.send.await_count, 1)
            self.assertEqual(player.radio_status, "sonando")
            self.assertGreaterEqual(source.return_value.cleanup.call_count, 2)
            self.assertIn("-reconnect_at_eof 1", source.call_args.kwargs["before_options"])

    async def test_music_interrupts_retry_wait_immediately(self):
        calls = []

        async def audio(_player, info, channel=None, *, live=False):
            calls.append("radio" if live else "song")
            if live:
                await asyncio.Event().wait()

        with patch.object(bot, "RADIO_RETRY_INITIAL", 60), \
                patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=[ConnectionError(), "https://station.example/live"])), \
                patch.object(bot, "resolve", new=AsyncMock(return_value={"title": "Song"})), \
                patch.object(bot.Player, "audio", new=audio):
            player = self.player()
            await self.wait_for(lambda: player.radio_status == "reconectando")
            player.enqueue("song", self.text)
            await self.wait_for(lambda: calls == ["song", "radio"])

    async def test_disabling_radio_keeps_pending_tracks_and_persistence_disabled(self):
        calls = []

        async def audio(_player, info, channel=None, *, live=False):
            calls.append("radio" if live else "song")
            await asyncio.Event().wait()

        self.store.set(123, CONFIG)
        with patch.object(bot, "resolve_stream", new=AsyncMock(return_value="https://station.example/live")), \
                patch.object(bot, "resolve", new=AsyncMock(return_value={"title": "Song"})), \
                patch.object(bot.Player, "audio", new=audio):
            player = self.player()
            await self.wait_for(lambda: calls == ["radio"])
            player.enqueue("first", self.text)
            player.enqueue("second", self.text)
            await self.wait_for(lambda: calls == ["radio", "song"])
            await bot.radio_command.callback(self.ctx, value="off")
            self.assertIsNone(player.radio)
            self.assertEqual(player.current_kind, "track")
            self.assertEqual(player.queue.qsize(), 1)
            self.assertIsNone(RadioStore(self.store.path).get(123))

    async def test_stop_disables_saved_radio_and_cancels_resolution(self):
        self.store.set(123, CONFIG)
        with patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)) as resolver:
            player = self.player()
            await self.wait_for(lambda: resolver.await_count == 1)
            player.queue.put_nowait(("pending", self.text))
            await asyncio.wait_for(bot.stop_command.callback(self.ctx), 1)
            self.assertTrue(player.worker.done())
            self.assertTrue(player.queue.empty())
            self.assertIsNone(RadioStore(self.store.path).get(123))
            self.assertNotIn(123, bot.players)
            self.voice.disconnect.assert_awaited()

    async def test_late_metadata_does_not_reenable_after_stop(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def station(link):
            started.set()
            await release.wait()
            return {"link": LINK, "title": "Test Radio"}

        with patch.object(bot, "get_station", side_effect=station):
            request = asyncio.create_task(bot.radio_command.callback(self.ctx, value=LINK))
            try:
                await asyncio.wait_for(started.wait(), 1)
                await bot.stop_command.callback(self.ctx)
                release.set()
                await asyncio.wait_for(request, 1)
            finally:
                request.cancel()
            self.assertIsNone(self.store.get(123))
            self.assertNotIn(123, bot.players)

    async def test_reconnects_voice_and_restores_only_once_on_repeated_ready(self):
        self.store.set(123, CONFIG)
        self.guild.voice_client = None
        with patch.object(bot.bot, "get_guild", return_value=self.guild), \
                patch.object(bot.bot, "is_ready", return_value=True), \
                patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)):
            await bot.on_ready()
            first = bot.players[123]
            await self.wait_for(lambda: self.voice_channel.connect.await_count == 1)
            await bot.on_ready()
            self.assertIs(bot.players[123], first)
            self.voice_channel.connect.assert_awaited_once_with(timeout=30, reconnect=True, self_deaf=True,
                                                               cls=bot.RadioVoiceClient)

    async def test_reconnect_failure_can_be_stopped_without_deadlock(self):
        self.store.set(123, CONFIG)
        self.voice.is_connected.return_value = False
        self.voice_channel.connect.side_effect = TimeoutError
        with patch.object(bot.bot, "is_ready", return_value=True), patch.object(bot, "RADIO_RETRY_INITIAL", 60):
            player = self.player()
            await self.wait_for(lambda: self.voice_channel.connect.await_count == 1)
            await asyncio.wait_for(bot.stop_command.callback(self.ctx), 1)
            self.assertTrue(player.worker.done())
            self.assertNotIn(123, bot.players)
            self.assertIsNone(self.store.get(123))

    async def test_radio_bypasses_idle_timeout_and_tracks_still_disconnect(self):
        with patch.object(bot, "IDLE_TIMEOUT", 0.02), \
                patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)) as resolver:
            player = self.player()
            await self.wait_for(lambda: resolver.await_count == 1)
            await asyncio.sleep(0.04)
            self.voice.disconnect.assert_not_awaited()
            player.set_radio(None)
            await self.wait_for(lambda: player.worker.done())
            self.voice.disconnect.assert_awaited_once()

    async def test_controls_require_configured_voice_channel(self):
        self.store.set(123, CONFIG)
        self.ctx.author.voice.channel = SimpleNamespace(id=999)
        with self.assertRaisesRegex(bot.commands.CheckFailure, "canal de voz configurado"):
            await bot.radio_command.callback(self.ctx, value="off")
        self.assertEqual(self.store.get(123), CONFIG)

    async def test_enable_radio_wakes_idle_player_and_saves_configuration(self):
        with patch.object(bot, "get_station", new=AsyncMock(return_value={"link": LINK, "title": "Test Radio"})), \
                patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)) as resolver:
            player = self.player(radio_config=None)
            await asyncio.sleep(0)
            await bot.radio_command.callback(self.ctx, value=LINK)
            await self.wait_for(lambda: resolver.await_count == 1)
            self.assertIs(bot.players[123], player)
            self.assertEqual(RadioStore(self.store.path).get(123), CONFIG)

    async def test_station_change_preserves_current_song_and_queue(self):
        replacement = {"link": "https://radio.garden/listen/another-radio/WXYZ5678", "title": "Another Radio"}
        self.store.set(123, CONFIG)
        with patch.object(bot, "get_station", new=AsyncMock(return_value=replacement)), \
                patch.object(bot, "resolve", new=AsyncMock(side_effect=blocked_stream)) as resolver:
            player = self.player()
            player.enqueue("first", self.text)
            player.enqueue("second", self.text)
            await self.wait_for(lambda: resolver.await_count == 1)
            current = player.current
            await bot.radio_command.callback(self.ctx, value=replacement["link"])
            self.assertIs(player.current, current)
            self.assertFalse(current.cancelled())
            self.assertEqual(player.queue.qsize(), 1)
            self.assertEqual(player.radio["title"], "Another Radio")
            self.assertEqual(player.radio_status, "pausada por canciones")
            self.assertEqual(RadioStore(self.store.path).get(123)["link"], replacement["link"])

    async def test_transient_voice_failure_recovers_without_losing_radio(self):
        self.store.set(123, CONFIG)
        new_voice = MagicMock()
        new_voice.is_connected.return_value = True
        new_voice.disconnect = AsyncMock()
        self.voice_channel.connect.return_value = new_voice
        with patch.object(bot.bot, "is_ready", return_value=True), \
                patch.object(bot, "VOICE_CHECK_INTERVAL", 0.005), patch.object(bot, "RADIO_RETRY_INITIAL", 0.005), \
                patch.object(bot, "resolve_stream", new=AsyncMock(return_value="https://station.example/live")), \
                patch.object(bot.discord, "FFmpegPCMAudio"):
            player = self.player()
            await self.wait_for(lambda: self.voice.play.call_count == 1)
            self.voice.is_connected.return_value = False
            await self.wait_for(lambda: new_voice.play.call_count == 1)
            self.assertIs(bot.players[123], player)
            self.assertIs(player.voice, new_voice)
            self.assertEqual(player.radio_status, "sonando")
            self.assertEqual(self.store.get(123), CONFIG)

    async def test_voice_move_updates_persistent_destination(self):
        self.store.set(123, CONFIG)
        moved = MagicMock(spec=discord.VoiceChannel)
        moved.id = 999
        connection = MagicMock(user=SimpleNamespace(id=1000))
        with patch.object(bot.bot, "_connection", connection), \
                patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)):
            player = self.player()
            await bot.on_voice_state_update(SimpleNamespace(id=1000, guild=self.guild),
                                            SimpleNamespace(channel=self.voice_channel), SimpleNamespace(channel=moved))
            self.assertEqual(player.radio["voice_channel_id"], 999)
            self.assertEqual(RadioStore(self.store.path).get(123)["voice_channel_id"], 999)

    async def test_skip_does_not_stop_continuous_radio(self):
        with patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)) as resolver:
            player = self.player()
            await self.wait_for(lambda: resolver.await_count == 1)
            current = player.current
            await bot.skip_command.callback(self.ctx)
            self.assertIs(player.current, current)
            self.assertFalse(current.cancelled())
            self.assertIsNotNone(player.radio)

    async def test_last_listener_leaving_keeps_radio_playing_past_idle_timeout(self):
        self.store.set(123, CONFIG)
        connection = MagicMock(user=SimpleNamespace(id=999))
        with patch.object(bot.bot, "_connection", connection), patch.object(bot, "IDLE_TIMEOUT", 0.01), \
                patch.object(bot, "resolve_stream", new=AsyncMock(return_value="https://station.example/live")), \
                patch.object(bot.discord, "FFmpegPCMAudio") as source:
            player = self.player()
            await self.wait_for(lambda: self.voice.play.call_count == 1)
            self.voice_channel.members = []
            await bot.on_voice_state_update(SimpleNamespace(id=1000, guild=self.guild),
                                            SimpleNamespace(channel=self.voice_channel), SimpleNamespace(channel=None))
            await asyncio.sleep(0.04)
            self.assertEqual(player.radio_status, "sonando")
            self.assertFalse(player.closing)
            self.assertEqual(self.store.get(123), CONFIG)
            self.voice.disconnect.assert_not_awaited()
            source.return_value.cleanup.assert_not_called()

    async def test_external_kick_stops_worker_and_disables_radio_after_restart(self):
        self.store.set(123, CONFIG)
        protocol = self.protocol()
        self.guild.voice_client = protocol
        with patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)) as resolver, \
                patch.object(bot.bot, "get_guild", return_value=self.guild):
            player = self.player(voice=protocol)
            await self.wait_for(lambda: resolver.await_count == 1)
            await asyncio.wait_for(protocol.on_voice_state_update({"channel_id": None}), 1)
            self.assertTrue(player.worker.done())
            self.assertIsNone(player.radio)
            self.assertNotIn(123, bot.players)
            self.assertIsNone(RadioStore(self.store.path).get(123))
            await bot.on_ready()
            self.assertNotIn(123, bot.players)
            self.voice_channel.connect.assert_not_awaited()
            protocol.disconnect.assert_not_awaited()
            protocol._connection.voice_state_update.assert_awaited_once_with({"channel_id": None})

    async def test_internal_voice_disconnect_preserves_active_radio(self):
        self.store.set(123, CONFIG)
        protocol = self.protocol(expected_disconnect=True)
        self.guild.voice_client = protocol
        with patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)) as resolver:
            player = self.player(voice=protocol)
            await self.wait_for(lambda: resolver.await_count == 1)
            await protocol.on_voice_state_update({"channel_id": None})
            self.assertFalse(player.closing)
            self.assertIs(bot.players[123], player)
            self.assertEqual(self.store.get(123), CONFIG)
            protocol._connection.voice_state_update.assert_awaited_once()

    async def test_old_voice_client_cannot_disable_new_radio_session(self):
        self.store.set(123, CONFIG)
        old = self.protocol()
        with patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)):
            player = self.player()
            await old.on_voice_state_update({"channel_id": None})
            self.assertFalse(player.closing)
            self.assertIs(bot.players[123], player)
            self.assertEqual(self.store.get(123), CONFIG)

    async def test_kick_cancels_pending_radio_request(self):
        self.store.set(123, CONFIG)
        protocol = self.protocol()
        self.guild.voice_client = protocol
        started, release = asyncio.Event(), asyncio.Event()

        async def station(link):
            started.set()
            await release.wait()
            return {"link": LINK, "title": "Test Radio"}

        with patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)), \
                patch.object(bot, "get_station", side_effect=station):
            player = self.player(voice=protocol)
            request = asyncio.create_task(bot.radio_command.callback(self.ctx, value=LINK))
            try:
                await asyncio.wait_for(started.wait(), 1)
                await asyncio.wait_for(protocol.on_voice_state_update({"channel_id": None}), 1)
                release.set()
                await asyncio.wait_for(request, 1)
            finally:
                request.cancel()
            self.assertTrue(player.worker.done())
            self.assertNotIn(123, bot.players)
            self.assertIsNone(self.store.get(123))

    async def test_kick_during_reconnection_does_not_deadlock_or_rejoin(self):
        self.store.set(123, CONFIG)
        protocol = self.protocol()
        self.voice.is_connected.return_value = False
        connecting = asyncio.Event()

        async def connect(**kwargs):
            self.guild.voice_client = protocol
            connecting.set()
            await asyncio.Event().wait()

        self.voice_channel.connect.side_effect = connect
        with patch.object(bot.bot, "is_ready", return_value=True):
            player = self.player()
            await asyncio.wait_for(connecting.wait(), 1)
            await asyncio.wait_for(protocol.on_voice_state_update({"channel_id": None}), 1)
            self.assertTrue(player.worker.done())
            self.assertNotIn(123, bot.players)
            self.assertIsNone(self.store.get(123))
            self.assertEqual(self.voice_channel.connect.await_count, 1)

    async def test_kick_stops_playback_even_if_persistence_fails(self):
        self.store.set(123, CONFIG)
        protocol = self.protocol()
        self.guild.voice_client = protocol
        with patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)), \
                patch.object(self.store, "remove", side_effect=ValueError("unwritable")):
            player = self.player(voice=protocol)
            await protocol.on_voice_state_update({"channel_id": None})
            self.assertTrue(player.worker.done())
            self.assertNotIn(123, bot.players)
            self.assertIsNone(self.store.get(123))
            self.assertIn("No pude guardar", self.text.send.call_args.args[0])

    async def test_removal_from_server_disables_saved_radio(self):
        self.store.set(123, CONFIG)
        with patch.object(bot, "resolve_stream", new=AsyncMock(side_effect=blocked_stream)):
            player = self.player()
            await bot.on_guild_remove(self.guild)
            self.assertTrue(player.worker.done())
            self.assertNotIn(123, bot.players)
            self.assertIsNone(RadioStore(self.store.path).get(123))
            self.voice.disconnect.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
