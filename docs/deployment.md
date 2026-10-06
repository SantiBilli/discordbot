# Deployment

**English** · [Español](deployment.es.md) · [README](../README.md)

Create your own Discord application/token and enable Message Content Intent as
described in the README. Run one bot instance per token.

Enable **Change Nickname** on a role assigned to the bot in **Server Settings →
Roles** for the playback nickname. For future installations, include this
permission in **OAuth2 → URL Generator** as well. Changing the generated invite
alone does not grant the permission in an existing server. Nicknames need no
additional privileged intents or environment variables.

## Docker Compose

Install Docker and its Compose plugin on your host, clone the repository, and run:

```bash
cp .env.example .env
```

In PowerShell, use `Copy-Item .env.example .env`. Edit `.env` locally to set
`DISCORD_TOKEN`. On Linux, restrict access with `chmod 600 .env`.

```bash
docker compose up -d --build
docker compose logs -f --tail=100
```

Docker installs Python 3.12, FFmpeg, Opus, Deno, and the Python dependencies. Look
for `AstraMusic conectado como ...` in the logs. No incoming ports, domain,
HTTPS endpoint, or reverse proxy are required. Allow outbound HTTPS/WebSocket
and Discord voice UDP traffic.

The service has a 768 MB memory limit. Leave additional memory for your host
and deployment platform; adjust the limit based on actual concurrent usage.
Logs rotate at 10 MB, keeping three files.

## Dokploy

1. Create a project and a **Docker Compose** service.
2. Connect GitHub or a Git provider and select the repository and `main` branch.
3. Set the Compose path to `docker-compose.yml` in the repository root.
4. Add `DISCORD_TOKEN` in the service's **Environment** configuration and save it.
   Keep the real value out of GitHub.
5. Deploy and inspect logs for the connection message.
6. Keep one instance and preserve the Compose `radio_data` volume on redeploys.
7. Enable automatic deployment if you want pushes to the selected branch to
   trigger rebuilds. Otherwise deploy manually after pushing changes.

A public repository still needs its token configured privately in Dokploy.
Changing GitHub visibility does not require another Discord application.
If you rename the repository, verify the Git source URL and webhook in Dokploy.

## Persistence and updates

The named volume `radio_data` mounts at `/app/data`; Compose sets
`RADIO_STATE_FILE=/app/data/radio.json`. It stores the station share link and
server/voice/text channel preferences, not expiring stream URLs or song queues.
Original server nicknames are stored in `/app/data/radio.nicknames.json` in the
same volume, allowing restoration after a restart. Preserve both files.

```bash
git pull --ff-only
docker compose up -d --build
```

`docker compose down` preserves the volume. **`docker compose down -v` deletes
saved radio preferences and original nicknames.** Keep the Compose project/service identity stable when
redeploying, and back up the volume if you need to migrate to another host.

To refresh yt-dlp when YouTube behavior changes:

```bash
docker compose build --no-cache
docker compose up -d
```

In Dokploy, use its rebuild-without-cache option. This refreshes dependencies
within the constraints in `requirements.txt`; review upgrades before deploying.

## Manual verification

Use your own test token/server and a station available from the host's region.

1. Join a voice channel and send `!radio <station URL>`; confirm audible audio
   and `!radio estado` reports playback.
2. Leave the channel empty; confirm the bot stays connected and radio continues
   when you return.
3. Add a song with `!p`; confirm the nickname shows the song, then returns to the
   station name when radio resumes. Allow for Discord's nickname update delays.
4. Restart the container normally; confirm radio returns without another command.
5. Use `!stop`; confirm the original nickname returns, then restart and confirm
   radio remains disabled.
6. Enable radio again and disconnect the bot using Discord; confirm it does not
   rejoin, including after restart.

Automated tests mock voice and providers. A passing Docker build does not verify
real Discord audio or station availability.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Commands do not respond | Message Content Intent, View Channels/Send Messages, and the `!` prefix. |
| Connected without sound | Connect/Speak, server mute, outbound UDP, and regular voice channel type. |
| Invalid token | Reset it in Discord and replace the private environment value. |
| YouTube fails | Public non-live video, age/region restrictions, provider IP blocks, and yt-dlp version. |
| Spotify selects another recording | Send the exact YouTube URL instead of relying on title search. |
| Radio keeps reconnecting | A `/listen/` link, an available station, and outbound access from the host. |
| Radio settings fail to save | Persistent volume mounted at `/app/data`, writable by container user `bot`. |
| Radio does not restore | Preserved volume, existing channel, and Connect/Speak permissions. |
| Nickname does not update or restore | Change Nickname on the bot's server role, Discord update delays, and a writable state volume. Check logs for a preserved corrupt nickname file. |
| Memory-related restarts | Deployment logs and a memory limit appropriate to concurrent playback. |

Official references: [Dokploy Compose](https://docs.dokploy.com/docs/core/docker-compose/example),
[Dokploy auto deploy](https://docs.dokploy.com/docs/core/auto-deploy),
[Discord gateway intents](https://docs.discord.com/developers/events/gateway),
[yt-dlp JavaScript runtime](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
