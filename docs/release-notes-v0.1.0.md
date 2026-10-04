# AstraMusic v0.1.0

First public release of AstraMusic, a self-hosted Discord music bot built with
Python and deployed with Docker Compose or Dokploy.

## Included

- YouTube playback and Spotify track lookup through YouTube search.
- Independent music queues per Discord server.
- Persistent Radio Garden playback, including empty voice channels.
- Automatic radio resumption after queued songs and recovery after interruptions.
- Radio configuration restoration after normal restarts.
- Radio shutdown after external voice/server removal.
- English/Spanish setup documentation, MIT license, and contribution guidelines.
- Automated unit tests, Docker build checks, and redacted secret scanning.

## Installation

Follow the [README](https://github.com/SantiBilli/discordbot#quick-start) and use
your own Discord bot token. Existing deployments should preserve `radio_data`.

## Known limitations

Commands use the `!` prefix and bot messages are in Spanish. Spotify playback
uses a YouTube match; it does not stream from Spotify. Music queues are temporary.
Radio Garden endpoints and media provider availability can change. Regular voice
channels are supported; Stage channels are not.

Continuous playback requires an available host, Discord connection, and station.
Automated tests simulate providers and voice; validate real audio on your host.
