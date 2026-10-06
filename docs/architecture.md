# Architecture

AstraMusic is a single-process asyncio application. One Discord bot instance
can maintain separate players for multiple servers; deployment uses one process
per token. This is not a distributed queue or a multi-replica design.

```mermaid
flowchart LR
    Commands[Discord text commands] --> Bot[bot.py: per-server player]
    Bot --> Queue[Temporary music queue]
    Queue --> Media[media.py: YouTube / Spotify lookup]
    Bot --> Radio[radio.py: Radio Garden resolver]
    Bot --> Nickname[nickname.py: background server nicknames]
    Bot <--> State[state.py: persistent radio preferences]
    Nickname <--> State
    Media --> Audio[FFmpeg / Discord voice]
    Radio --> Audio
    State <--> Volume[Docker radio_data volume]
```

| File | Responsibility |
| --- | --- |
| `bot.py` | Commands, per-server locks/queues, worker lifecycle, cancellation, voice recovery, and radio restoration. |
| `media.py` | Music URL normalization, Spotify oEmbed lookup, and yt-dlp extraction. |
| `radio.py` | Station link normalization, metadata, stream redirects, and public destination checks. |
| `nickname.py` | Per-server nickname updates, coalescing, permission recovery, and original nickname restoration. |
| `state.py` | Validated radio settings, original nicknames, and atomic JSON persistence. |
| `tests/test_bot.py` | Music link and queue/cancellation behavior. |
| `tests/test_radio.py` | Resolution, persistence, radio/music transitions, recovery, and external removal. |
| `tests/test_nickname.py` | Nickname persistence, asynchronous races, permissions, and playback integration. |

## Playback lifecycle

Each server has a player and an independent queue. Pending tracks take priority
over configured radio. When no tracks remain, the player returns to radio. With
neither tracks nor radio, it disconnects after the idle timeout.

Radio recovery refreshes the stream URL and uses an interruptible retry wait.
Commands can stop playback or interrupt resolution without waiting for the next
retry. Transient voice failures preserve radio; external removal disables it.

Nickname requests are synchronous signals to an independent per-server task;
playback never awaits the nickname HTTP request. Each task applies the latest
requested title, combines rapid transitions, and lets discord.py handle actual
API rate limits. Missing permissions and temporary HTTP/storage failures retry
without blocking audio. Idle/closed players request restoration; server removal
cancels outstanding nickname work.

## Persistence

RadioStore records the canonical station share link, title, and destination
server/channel IDs. Writes use a temporary file, synchronization, and atomic
replacement. Expiring stream URLs and the music queue are not persisted.

NicknameStore saves the original nickname, including `null` when there was no
server nickname, before the first edit. It uses a separate file derived from
`RADIO_STATE_FILE` with a `.nicknames.json` suffix. Restoration removes that
record only after success. Startup restores inactive servers while active radios
reuse their saved originals. A corrupt nickname file disables only automatic
nicknames and is preserved for repair.

The configured file must be writable and its containing directory persistent.
A corrupt state file is preserved and reported rather than silently replaced.
If storage fails during external removal, playback stops, but an old on-disk
setting may remain; repair storage before restarting.

## Maintenance considerations

- `RadioVoiceClient` uses `VoiceClient._connection._expecting_disconnect`, a
  private discord.py 2.7.1 flag, to distinguish internal recovery from external
  removal. Keep the version pin until compatibility is reviewed. Exercise the
  kick/internal-disconnect regression tests when changing it.
- yt-dlp and Radio Garden behavior depend on external services. Python dependency
  ranges allow updates at rebuild time; builds are not fully locked. Review
  updates, run CI, and test actual audio before deployment.
- Unit tests simulate providers and voice. They verify control flow and
  persistence, not provider uptime, voice quality, or resource capacity.
- Container execution uses a non-root user. The radio volume must remain writable
  by that user and must not be committed to Git.
