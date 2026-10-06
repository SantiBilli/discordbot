"""Persist radio preferences and original nicknames with atomic JSON writes."""
import json
import os
from pathlib import Path

from radio import normalize_radio_link


def write_json(path, updated):
    temporary = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(updated, output, ensure_ascii=False, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


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
        try:
            write_json(self.path, updated)
        except OSError as error:
            raise ValueError("No pude guardar la radio. Revisá los permisos de RADIO_STATE_FILE y el volumen de Docker.") from error
        self.entries = updated


class NicknameStore:
    """Remember a custom nickname or None (no server nickname) before editing it."""

    def __init__(self, path):
        self.path = Path(path)
        self.entries = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("Invalid nickname state")
                for guild_id, nickname in data.items():
                    if (not guild_id.isdecimal() or int(guild_id) <= 0
                            or (nickname is not None and
                                (not isinstance(nickname, str) or not 1 <= len(nickname) <= 32))):
                        raise ValueError("Invalid original nickname")
                self.entries = data
            except (OSError, ValueError, TypeError) as error:
                raise RuntimeError("No pude leer los apodos originales; conservé el archivo.") from error

    def remember(self, guild_id, nickname):
        if str(guild_id) not in self.entries:
            updated = {**self.entries, str(guild_id): nickname}
            self._save(updated)

    def remove(self, guild_id):
        if str(guild_id) in self.entries:
            updated = dict(self.entries)
            updated.pop(str(guild_id))
            self._save(updated)

    def _save(self, updated):
        try:
            write_json(self.path, updated)
        except OSError as error:
            raise ValueError("No pude guardar los apodos originales. Revisá los permisos del volumen de Docker.") from error
        self.entries = updated
