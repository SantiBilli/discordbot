"""Persist radio preferences, never expiring stream URLs or the music queue."""
import json
import os
from pathlib import Path

from radio import normalize_radio_link


class RadioStore:
    def __init__(self, path):
        self.path = Path(path)
        self.entries = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Invalid radio state")
                for guild_id, config in data.items():
                    if not guild_id.isdecimal() or int(guild_id) <= 0 or not isinstance(config, dict):
                        raise ValueError("Invalid guild")
                    _, link = normalize_radio_link(config["link"])
                    if (link != config["link"] or not isinstance(config["title"], str)
                            or not config["title"].strip() or len(config["title"]) > 180
                            or any(type(config[key]) is not int or config[key] <= 0
                                   for key in ("voice_channel_id", "text_channel_id"))):
                        raise ValueError("Invalid radio configuration")
                self.entries = data
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise RuntimeError("No pude leer la configuración de radio. Revisá RADIO_STATE_FILE; conservé el archivo.") from error

    def get(self, guild_id):
        config = self.entries.get(str(guild_id))
        return dict(config) if config else None

    def set(self, guild_id, config):
        updated = dict(self.entries)
        updated[str(guild_id)] = dict(config)
        self._save(updated)

    def remove(self, guild_id):
        if str(guild_id) in self.entries:
            updated = dict(self.entries)
            updated.pop(str(guild_id))
            self._save(updated)

    def _save(self, updated):
        temporary = self.path.with_name(self.path.name + ".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as output:
                json.dump(updated, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        except OSError as error:
            raise ValueError("No pude guardar la radio. Revisá los permisos de RADIO_STATE_FILE y el volumen de Docker.") from error
        self.entries = updated
