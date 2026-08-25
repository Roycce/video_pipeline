"""
Stream Auto Cutter — Settings Module.

Handles loading, saving, and validating application settings.
Settings are stored in a JSON file next to the application.
"""

import json
import sys
from pathlib import Path

DEFAULT_SETTINGS = {
    # --- Cutting ---
    "segment_duration_min": 16,

    # --- Intro / Outro ---
    "intro_path": "",
    "outro_path": "",
    "intro_enabled": False,
    "outro_enabled": False,

    # --- Logo ---
    "logo_enabled": False,
    "logos": [],                        # List of logo dicts


    # --- Video ---
    "resolution": "source",             # "source", "1280x720", "1920x1080", etc.
    "custom_resolution_w": 1920,
    "custom_resolution_h": 1080,
    "fps": "source",                    # "source", "24", "30", "60"
    "codec": "libx264",                 # libx264, hevc_videotoolbox, h264_nvenc, etc.

    # --- File Size ---
    "file_size_limit_enabled": False,
    "file_size_limit_mb": 650,
    "audio_bitrate": 128,               # kbps

    # --- Output ---
    "output_subfolder": "output",

    # --- VK Uploader ---
    "vk_token": "",
    "vk_group_id": "",           # пустая строка = личная страница
    "vk_titles_file": "",        # путь к файлу с названиями
    "vk_video_folder": "",       # папка с готовыми видео
    "vk_delay_sec": 10,
    "vk_max_videos": 150,
}


class Settings:
    """Application settings manager with JSON persistence."""

    def __init__(self, config_path: str | Path | None = None):
        if config_path is None:
            if getattr(sys, 'frozen', False):
                config_path = Path(sys.executable).parent / "settings.json"
            else:
                config_path = Path(__file__).parent / "settings.json"
        self._path = Path(config_path)
        self._data: dict = dict(DEFAULT_SETTINGS)
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load settings from disk, falling back to defaults for missing keys."""
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                saved = json.load(fh)
            for key in DEFAULT_SETTINGS:
                if key in saved:
                    self._data[key] = saved[key]
        except (json.JSONDecodeError, OSError):
            pass  # keep defaults

    def save(self) -> None:
        """Persist current settings to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get(self, key: str, default=None):
        """Return a single setting value."""
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        """Set a single setting and save to disk."""
        self._data[key] = value
        self.save()

    def get_all(self) -> dict:
        """Return a snapshot of all settings."""
        return dict(self._data)

    def update(self, data: dict) -> None:
        """Bulk-update settings and save to disk."""
        self._data.update(data)
        self.save()

    def reset(self) -> None:
        """Reset all settings to defaults and save."""
        self._data = dict(DEFAULT_SETTINGS)
        self.save()
