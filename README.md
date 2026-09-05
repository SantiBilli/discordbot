# 🎧 AstraMusic

Bot de música para Discord, preparado para tu VPS con Docker y Dokploy.

## Comandos

Entrá a un canal de voz y escribí en un canal de texto:

```text
!p https://www.youtube.com/watch?v=dQw4w9WgXcQ
!p https://open.spotify.com/track/ID_DE_LA_CANCION
!skip
!stop
!help
```

Usá un video normal, no una transmisión en vivo.
`!p` reproduce o agrega a la cola. `!skip` salta incluso mientras busca audio.
`!stop` vacía la cola y desconecta. Solo quienes están en el mismo canal de voz
pueden controlarlo. Cada servidor tiene su propia cola (hasta 50 pendientes).
Se desconecta después de 2 minutos sin canciones. Las colas se pierden al reiniciar.

**Spotify:** acepta enlaces públicos `open.spotify.com/track/...`, obtiene el
título usando oEmbed y busca una coincidencia en YouTube. No reproduce audio
directamente desde Spotify ni requiere cuenta Premium o claves de Spotify.
La coincidencia por título no es exacta: puede encontrar otra versión o artista.
Para elegir una grabación precisa, mandá el enlace de YouTube. No admite álbumes,
playlists, enlaces cortos de Spotify ni transmisiones en vivo.

## 1. Crear el bot e invitarlo a Discord

1. Abrí https://discord.com/developers/applications y seleccioná **New Application**.
2. Nombrala **AstraMusic**. Entrá en **Bot** y creá el bot si todavía no aparece.
3. En **Bot → Privileged Gateway Intents**, activá **Message Content Intent** y guardá.
   Es necesario para leer `!p`, `!skip` y `!stop`. No necesita los intents de miembros o presencia.
4. En **Bot → Reset Token**, obtené el token. Guardalo como un secreto: va en
   Dokploy o en `.env`, nunca en GitHub ni en un mensaje público.
5. En **OAuth2 → URL Generator**, marcá el scope **bot** y estos permisos:
   **View Channels**, **Send Messages**, **Connect** y **Speak**.
6. Abrí la URL generada, elegí tu servidor y autorizá. Necesitás poder administrar
   ese servidor. No hace falta darle permiso de Administrador al bot.
7. Revisá que los permisos específicos del canal de texto/voz no nieguen esos permisos.

El bot aparecerá conectado cuando termines el despliegue. Usá canales de voz
comunes; los escenarios (Stage Channels) no están soportados.

## 2. Desplegar con Dokploy (recomendado)

Sí, Dokploy sirve. Es un proceso permanente que se conecta a Discord: **no
necesita dominio, HTTPS propio, reverse proxy ni puertos publicados**.

1. Subí estos archivos a un repositorio de GitHub, preferentemente privado.
   No subas `.env`; ya está excluido por `.gitignore`.
2. En Dokploy, creá un proyecto y un servicio de tipo **Docker Compose**.
3. Elegí el proveedor **GitHub** (conectá tu cuenta) o **Git**, seleccioná el
   repositorio y la rama que contenga estos archivos.
4. Configurá el archivo Compose como `docker-compose.yml` en la raíz del repo.
5. En **Environment**, agregá y guardá:

   ```dotenv
   DISCORD_TOKEN=TU_TOKEN_REAL
   ```

6. Hacé **Deploy**. Docker instala Python, FFmpeg, Opus, Deno y las dependencias.
7. En los logs buscá `AstraMusic conectado como ...`.
8. Entrá al canal de voz de Discord y probá `!p` con un video musical disponible.
   Agregá otro, probá `!skip` y finalmente `!stop`.

Mantené **una sola instancia/réplica** usando este token. El contenedor reinicia
si falla y al reiniciar el VPS. La primera construcción tarda unos minutos.
El contenedor tiene un límite de 768 MB; dejá memoria adicional para Dokploy y
los demás servicios. Para varios servidores reproduciendo a la vez, aumentá el límite.

## Alternativa: Docker Compose por SSH

Con Docker y su plugin Compose instalados en el VPS, copiá esta carpeta o cloná
tu repositorio y, desde la carpeta del proyecto, ejecutá:

```bash
cp .env.example .env
nano .env
# Reemplazá el valor de DISCORD_TOKEN por el token real y guardá.
chmod 600 .env
docker compose up -d --build
docker compose logs -f --tail=100
```

Para detenerlo: `docker compose down`. Para actualizarlo después de traer
cambios: `docker compose up -d --build`.

## Problemas habituales

- **No responde a `!p`:** activá Message Content Intent y revisá View Channels /
  Send Messages. Si el token no sirve, regeneralo y actualizá el secreto en Dokploy.
- **Entra pero no se escucha:** revisá Connect / Speak y que no esté silenciado
  por el servidor. El VPS debe permitir tráfico saliente HTTPS/WebSocket y UDP
  para voz de Discord. No hace falta abrir un puerto entrante fijo para este bot.
- **YouTube no reproduce / pide iniciar sesión / bloquea IP:** algunas IP de VPS
  están restringidas. No se puede garantizar reproducción de todos los videos.
  Probá un video público, sin restricciones de edad/región. Si falla todo,
  revisá la conectividad y la IP con tu proveedor.
- **YouTube dejó de funcionar:** reconstruí sin caché para actualizar yt-dlp:
  `docker compose build --no-cache && docker compose up -d`.
  En Dokploy, usá la reconstrucción sin caché disponible para tu servicio.
- **Spotify reproduce otra versión:** el buscador utiliza el título público;
  usá un enlace directo de YouTube para seleccionar exactamente la grabación.
- **Se reinicia por memoria:** revisá los logs y aumentá `mem_limit` si es necesario.

## Desarrollo y comprobaciones

Requiere Python 3.12, FFmpeg y Deno instalados en el sistema:

```bash
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
python -m unittest discover -s tests -v
python bot.py
```

El token real y una conexión a Discord son necesarios para verificar audio de
extremo a extremo; las pruebas automáticas simulan voz y proveedores externos.

Referencias: [Dokploy Compose](https://docs.dokploy.com/docs/core/docker-compose/example),
[Discord intents](https://docs.discord.com/developers/events/gateway),
[Spotify oEmbed](https://developer.spotify.com/documentation/embeds/reference/oembed),
[yt-dlp / Deno](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
