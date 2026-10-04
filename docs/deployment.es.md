# Despliegue

[English](deployment.md) · **Español** · [README](../README.es.md)

Creá tu propia aplicación y token de Discord y activá Message Content Intent
como explica el README. Ejecutá una sola instancia del bot por token.

## Docker Compose

Instalá Docker y su plugin Compose en el host, cloná el repositorio y ejecutá:

```bash
cp .env.example .env
```

En PowerShell, usá `Copy-Item .env.example .env`. Editá `.env` localmente para
configurar `DISCORD_TOKEN`. En Linux, restringí el acceso con `chmod 600 .env`.

```bash
docker compose up -d --build
docker compose logs -f --tail=100
```

Docker instala Python 3.12, FFmpeg, Opus, Deno y las dependencias de Python.
Buscá `AstraMusic conectado como ...` en los logs. No hacen falta puertos
entrantes, dominio, endpoint HTTPS ni reverse proxy. Permití tráfico saliente
HTTPS/WebSocket y UDP para la voz de Discord.

El servicio tiene un límite de 768 MB. Dejá memoria adicional para el host y la
plataforma de despliegue; ajustá el límite según el uso simultáneo real.
Los logs rotan a los 10 MB y conservan tres archivos.

## Dokploy

1. Creá un proyecto y un servicio **Docker Compose**.
2. Conectá GitHub o un proveedor Git y elegí el repositorio y la rama `main`.
3. Configurá el archivo Compose como `docker-compose.yml` en la raíz del repo.
4. Agregá `DISCORD_TOKEN` en **Environment** y guardá. El valor real debe quedar
   fuera de GitHub.
5. Desplegá y buscá el mensaje de conexión en los logs.
6. Mantené una sola instancia y conservá el volumen `radio_data` al redesplegar.
7. Activá el despliegue automático si querés que los pushes a la rama elegida
   disparen reconstrucciones. En caso contrario, desplegá manualmente después
   de pushear.

Un repositorio público sigue necesitando su token configurado de forma privada
en Dokploy. Cambiar la visibilidad de GitHub no requiere otra aplicación de
Discord. Si renombrás el repositorio, revisá la URL de origen y el webhook en Dokploy.

## Persistencia y actualizaciones

El volumen `radio_data` se monta en `/app/data`; Compose configura
`RADIO_STATE_FILE=/app/data/radio.json`. Guarda el enlace de emisora y los
identificadores del servidor y canales de voz/texto. No guarda enlaces de
transmisión que vencen ni colas de canciones.

```bash
git pull --ff-only
docker compose up -d --build
```

`docker compose down` conserva el volumen. **`docker compose down -v` elimina
las preferencias de radio.** Mantené estable la identidad del proyecto/servicio
Compose al redesplegar y respaldá el volumen si migrás a otro host.

Para actualizar yt-dlp cuando cambie el comportamiento de YouTube:

```bash
docker compose build --no-cache
docker compose up -d
```

En Dokploy, usá la reconstrucción sin caché. Esto actualiza dependencias dentro
de las restricciones de `requirements.txt`; revisá los cambios antes de desplegar.

## Verificación manual

Usá tu token y servidor de pruebas y una emisora disponible desde la región del host.

1. Entrá al canal de voz y mandá `!radio <enlace>`; confirmá que hay audio y que
   `!radio estado` indica reproducción.
2. Dejá el canal vacío; confirmá que el bot permanece y la radio continúa al volver.
3. Agregá una canción con `!p`; confirmá que la radio vuelve al terminar la cola.
4. Reiniciá el contenedor normalmente; debe retomar la radio sin otro comando.
5. Usá `!stop` y reiniciá; la radio debe seguir desactivada.
6. Activá la radio otra vez y desconectá al bot desde Discord; no debe volver a
   entrar, incluso después de reiniciar.

Las pruebas automáticas simulan voz y proveedores. Una construcción Docker
exitosa no verifica el audio real de Discord ni la disponibilidad de la emisora.

## Solución de problemas

| Síntoma | Qué revisar |
| --- | --- |
| Los comandos no responden | Message Content Intent, View Channels/Send Messages y prefijo `!`. |
| Se conecta sin audio | Connect/Speak, mute del servidor, UDP saliente y tipo de canal de voz común. |
| Token inválido | Regeneralo en Discord y reemplazá el valor privado del entorno. |
| YouTube falla | Video público que no sea en vivo, restricciones de edad/región, bloqueo de IP y versión de yt-dlp. |
| Spotify elige otra grabación | Mandá el enlace exacto de YouTube en lugar de depender de la búsqueda por título. |
| La radio sigue reconectando | Enlace `/listen/`, emisora disponible y acceso saliente desde el host. |
| No guarda la radio | Volumen persistente en `/app/data` con escritura para el usuario `bot`. |
| No retoma la radio | Volumen conservado, canal existente y permisos Connect/Speak. |
| Reinicia por memoria | Logs del despliegue y límite de memoria apropiado para el uso simultáneo. |

Referencias oficiales: [Dokploy Compose](https://docs.dokploy.com/docs/core/docker-compose/example),
[Dokploy auto deploy](https://docs.dokploy.com/docs/core/auto-deploy),
[Discord gateway intents](https://docs.discord.com/developers/events/gateway),
[yt-dlp y JavaScript](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
