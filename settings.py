"""
Stream Auto Cutter — Settings Module.

Handles loading, saving, and validating application settings.
Settings are stored in a JSON file next to the application.
"""

import json
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
    "logo_path": "",
    "logo_enabled": False,
    "logo_type": "image",               # image, video_chromakey
    "logo_position": "top_right",       # top_left, top_right, bottom_left, bottom_right
    "logo_size": 15,                    # percent of video width (5–50)
    "logo_opacity": 80,                 # percent (0–100)
    "logo_display": "full",             # full, first_n, last_n, custom
    "logo_time_start": 0,               # seconds
    "logo_time_end": 10,                # seconds

    # --- Video ---
    "resolution": "source",             # "source", "1280x720", "1920x1080", etc.
    "custom_resolution_w": 1920,
    "custom_resolution_h": 1080,
    "fps": "source",                    # "source", "24", "30", "60"
    "codec": "libx264",                 # libx264, hevc_videotoolbox, h264_nvenc, etc.

    # --- File Size ---
    "file_size_limit_enabled": True,
    "file_size_limit_mb": 650,
    "audio_bitrate": 128,               # kbps

    # --- Output ---
    "output_subfolder": "output",
}


class Settings:
    """Application settings manager with JSON persistence."""

    def __init__(self, config_path: str | Path | None = None):
        if config_path is None:
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
