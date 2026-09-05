import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import bot
from media import normalize_link, resolve


class LinkTests(unittest.TestCase):
    def test_youtube(self):
        for link in ["https://youtu.be/dQw4w9WgXcQ?si=test", "https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=anything"]:
            self.assertEqual(normalize_link(link), ("youtube", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"))

    def test_spotify(self):
        self.assertEqual(normalize_link("https://open.spotify.com/intl-es/track/1234567890123456789012?si=test"),
                         ("spotify", "https://open.spotify.com/track/1234567890123456789012"))

    def test_reject_untrusted_urls_and_playlists(self):
        for link in ["http://localhost", "https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ", "file:///etc/passwd", "https://youtube.com/playlist?list=test", "https://open.spotify.com/album/123", "https://user@youtube.com/watch?v=dQw4w9WgXcQ"]:
            with self.subTest(link=link), self.assertRaises(ValueError):
                normalize_link(link)


class PlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.guild = SimpleNamespace(id=123)
        bot.locks[123] = asyncio.Lock()
        self.voice = MagicMock()
        self.voice.disconnect = AsyncMock()
        self.channel = SimpleNamespace(send=AsyncMock())
        self.player = bot.Player(self.guild, self.voice)
        bot.players[123] = self.player

    async def asyncTearDown(self):
        await self.player.close()
        bot.players.clear()
        bot.locks.clear()

    async def wait_for(self, predicate):
        async with asyncio.timeout(2):
            while not predicate():
                await asyncio.sleep(0.001)

    async def test_skip_during_resolution_advances_queue(self):
        calls = []

        async def fake_resolve(link):
            calls.append(link)
            await asyncio.Event().wait()

        with patch.object(bot, "resolve", side_effect=fake_resolve):
            self.player.queue.put_nowait(("first", self.channel))
            self.player.queue.put_nowait(("second", self.channel))
            await self.wait_for(lambda: calls == ["first"])
            self.player.current.cancel()
            await self.wait_for(lambda: calls == ["first", "second"])

    async def test_stop_cancels_resolution_and_disconnects(self):
        started = asyncio.Event()

        async def fake_resolve(link):
            started.set()
            await asyncio.Event().wait()

        with patch.object(bot, "resolve", side_effect=fake_resolve):
            self.player.queue.put_nowait(("first", self.channel))
            self.player.queue.put_nowait(("second", self.channel))
            await asyncio.wait_for(started.wait(), 2)
            await asyncio.wait_for(self.player.close(), 2)
            self.assertTrue(self.player.worker.done())
            self.voice.disconnect.assert_awaited()
            self.voice.play.assert_not_called()

    async def test_failed_track_does_not_block_next(self):
        with patch.object(bot, "resolve", side_effect=ValueError("unavailable")) as resolver:
            self.player.queue.put_nowait(("first", self.channel))
            self.player.queue.put_nowait(("second", self.channel))
            await asyncio.wait_for(self.player.queue.join(), 2)
            self.assertEqual(resolver.await_count, 2)

    async def test_completion_advances_and_cleans_audio(self):
        info = {"title": "Song", "url": "https://example.test/audio"}
        self.voice.play.side_effect = lambda source, after: after(None)
        with patch.object(bot, "resolve", new=AsyncMock(return_value=info)), patch.object(bot.discord, "FFmpegPCMAudio") as audio:
            self.player.queue.put_nowait(("first", self.channel))
            self.player.queue.put_nowait(("second", self.channel))
            await asyncio.wait_for(self.player.queue.join(), 2)
            self.assertEqual(self.voice.play.call_count, 2)
            self.assertEqual(audio.return_value.cleanup.call_count, 2)


if __name__ == "__main__":
    unittest.main()
