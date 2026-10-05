# AstraMusic

**English** · [Español](README.es.md)

![AstraMusic — persistent radio and music for Discord](docs/assets/banner.svg)

[![CI](https://github.com/SantiBilli/discordbot/actions/workflows/ci.yml/badge.svg)](https://github.com/SantiBilli/discordbot/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-teal.svg)](LICENSE)

A self-hosted Discord music bot built with Python. Play individual YouTube videos,
look up Spotify tracks, and keep a Radio Garden station running in your voice
channel—even when everyone leaves. Deploy it with Docker Compose or Dokploy.

## Features

- **Persistent radio:** stay connected in empty channels and restore active radio
  after normal container or VPS restarts.
- **Music over radio:** songs interrupt the station; radio resumes when the queue finishes.
- **Per-server queues:** up to 50 pending tracks per server, with independent playback state.
- **Automatic recovery:** refresh radio stream URLs and retry interruptions with
  increasing delays, capped at 60 seconds.
- **Voice controls:** only listeners in the configured voice channel can change or stop playback.
- **Docker deployment:** a non-root container, persistent radio volume, restart policy, and rotating logs.

## Quick start

You need Docker with the Compose plugin, a Discord server you can manage, and
your own bot token. Follow [Discord setup](#discord-setup) first.

```bash
git clone https://github.com/SantiBilli/discordbot.git
cd discordbot
cp .env.example .env
```

In PowerShell, use `Copy-Item .env.example .env` instead of `cp`.
Edit `.env` locally and replace the `DISCORD_TOKEN` placeholder with your token.
Never paste it into an issue, commit, screenshot, or public message.

```bash
docker compose up -d --build
docker compose logs -f --tail=100
```

Wait for `AstraMusic conectado como ...`, join a regular voice channel, and send
this in a text channel the bot can read:

```text
!radio https://radio.garden/listen/fm-aspen-102-3/eyipEP0m
!radio estado
```

Station availability depends on the provider and your server's location. No Radio
Garden API key is required. For hosting and updates, see the
[deployment guide](docs/deployment.md), also available in [Spanish](docs/deployment.es.md).

## Discord setup

1. Create an application in the [Discord Developer Portal](https://discord.com/developers/applications).
2. Open **Bot**, obtain its token, and store it in your local `.env` or deployment
   environment. Each installation should use its own application and token.
3. Enable **Message Content Intent** under **Privileged Gateway Intents**. Commands
   use the `!` prefix; member and presence intents are not required.
4. In **OAuth2 → URL Generator**, choose the **bot** scope and these permissions:
   **View Channels**, **Send Messages**, **Connect**, and **Speak**.
5. Open the generated URL and invite the bot to your server. Administrator
   permission is unnecessary. Check channel-specific permission overrides too.

## Commands

Send commands in a server text channel. Join the bot's voice channel to control
playback. Bot responses are currently in Spanish; the commands below work with
either documentation language.

| Command | Behavior |
| --- | --- |
| `!p <YouTube or Spotify track URL>` | Play a track or add it to the queue. Alias: `!play`. |
| `!radio <Radio Garden station URL>` | Enable radio or change the background station while keeping queued songs. |
| `!radio estado` or `!radio` | Show the station and playback/recovery status. |
| `!radio off` | Disable radio and keep the music queue. |
| `!skip` | Skip a song, including one still being resolved. Continuous radio cannot be skipped. |
| `!stop` | Disable radio, clear the queue, and disconnect. |
| `!help` | Show available commands. Alias: `!ayuda`. |

Use a station share link in the format `https://radio.garden/listen/name/ID`.
Radio Garden `/visit/` links point to cities and are not accepted.

## How radio behaves

| Event | Result |
| --- | --- |
| Everyone leaves the voice channel | Radio keeps playing; there is no empty-room timeout. |
| A track is added with `!p` | Radio pauses for the queue and returns after it finishes. |
| The station stream ends or fails | The bot refreshes the stream and retries after 5, 10, 20, 40, then 60 seconds. |
| A transient voice connection fails | The bot attempts to recover the connection. |
| The container or VPS restarts normally | Saved radio preferences restore playback after connecting to Discord. |
| Someone disconnects the bot from voice or removes it from the server | Radio is disabled and its saved configuration is removed; it does not intentionally rejoin. |
| The bot is moved to another regular voice channel | The new destination is saved. |
| `!radio off` is used | Radio stays disabled after restart; pending music continues. |
| `!stop` is used | Radio stays disabled after restart and all pending music is cleared. |

Without active radio, the bot disconnects after two minutes without songs.
Radio preferences persist; music queues do not survive process restarts.

## Configuration

| Variable | Required | Default / purpose |
| --- | --- | --- |
| `DISCORD_TOKEN` | Yes, to run the bot | Your own Discord bot token. Tests do not need it. |
| `RADIO_STATE_FILE` | No | `data/radio.json` locally; Compose sets `/app/data/radio.json`. |
| `RADIO_AD_KEYWORDS` | No | Comma-separated whole words; the radio is muted while the station's stream title (ICY metadata) matches one. Empty disables it. Only works for stations that label their ad breaks. |

Compose mounts the named volume `radio_data` at `/app/data`. Preserve it when
redeploying. `docker compose down` keeps it; `docker compose down -v` deletes it.
Run **one instance per token**. No incoming port, domain, or reverse proxy is
needed; Discord voice requires outbound network connectivity.

## Limitations

- Spotify links provide public track metadata through oEmbed; playback is a
  YouTube search match, not audio from Spotify. Another recording may be selected.
  Albums, playlists, and Spotify short links are unsupported.
- YouTube playback supports individual non-live videos. Provider restrictions,
  regional blocks, and unavailable videos can prevent playback.
- Radio Garden uses public endpoints without an official documented API contract.
  Changes upstream may require an update to the resolver.
- Regular voice channels are supported; Stage channels and slash commands are not.
- Continuous radio requires an available host, Discord connection, and station.
  Automatic recovery does not guarantee uninterrupted service.

## Legal use and responsibility

AstraMusic is an open-source project intended to be installed and run on your own
infrastructure. This repository distributes source code; it does not include
music recordings or grant permissions to use third-party content.

The project is independent and is not affiliated with, sponsored by, or endorsed
by Discord, YouTube, Spotify, or Radio Garden.

Anyone installing or using the software must verify that they have the necessary
permissions to access, play, or retransmit their chosen content, and comply with
applicable laws and the relevant services' terms. Content being accessible through
a link does not imply permission to retransmit it.

The software is provided as is, subject to the warranty disclaimers and limitations
of liability in the [MIT license](LICENSE), to the extent permitted by applicable
law. The authors do not control third-party installations or endorse uses that
infringe others' rights or service terms.

The MIT license covers the project's code; it does not grant licenses to music,
broadcasts, trademarks, or external services. This notice does not certify legal
compliance or replace permissions required from providers and rights holders.

Official provider references:

- [Discord Developer Terms of Service](https://support-dev.discord.com/hc/en-us/articles/8562894815383-Discord-Developer-Terms-of-Service)
- [YouTube Terms of Service](https://www.youtube.com/static?template=terms)
- [Spotify Widget Terms of Use](https://developer.spotify.com/documentation/embeds/terms)
- [Radio Garden contact](https://radio.garden/settings/contact) for questions about using the service.

## Development

Use Python 3.12. Local audio playback also needs FFmpeg, Opus, and Deno; Docker
provides them. See [Contributing](CONTRIBUTING.md) for platform-specific setup.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

The automated suite simulates voice and external providers. GitHub Actions runs
the tests, builds the Docker image, and scans Git history and tracked files for
secrets. Real audio verification requires your own Discord test server.

## Project documentation

- [Deployment and troubleshooting](docs/deployment.md)
- [Architecture and maintenance notes](docs/architecture.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE) © 2026 SantiBilli. Dependencies retain their own licenses.
