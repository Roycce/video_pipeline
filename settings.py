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

    # --- Shorts ---
    "shorts_enabled": False,
    "shorts_resolution": "1080x1920",   # "1080x1920" or "720x1280"
    "shorts_fit": "blur_sides",         # "crop_center", "blur_sides", "black_bars"

    # --- Sound Overlay ---
    "sound_overlay_enabled": False,
    "sound_overlays": [],               # list of overlay dicts

    # --- VK Uploader ---
    "vk_token": "",
    "vk_group_id": "",           # пустая строка = личная страница
    "vk_titles_file": "",        # путь к файлу с названиями
    "vk_video_folder": "",       # папка с готовыми видео
    "vk_delay_sec": 10,
    "vk_max_videos": 150,

    # --- Presets ---
    "presets": {},               # {name: {setting_key: value, ...}}
    "active_preset": None,       # имя активного пресета или None
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

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    # Keys that belong to a preset (processing settings, not VK account).
    PRESET_KEYS = (
        "segment_duration_min",
        "intro_path", "intro_enabled",
        "outro_path", "outro_enabled",
        "logo_enabled", "logos",
        "resolution", "custom_resolution_w", "custom_resolution_h",
        "fps", "codec",
        "file_size_limit_enabled", "file_size_limit_mb", "audio_bitrate",
        "output_subfolder",
        "shorts_enabled", "shorts_resolution", "shorts_fit",
        "sound_overlay_enabled", "sound_overlays",
    )

    def get_preset_names(self) -> list:
        """Return sorted list of saved preset names."""
        return sorted(self._data.get("presets", {}).keys())

    def save_preset(self, name: str, data: dict | None = None) -> None:
        """Save current settings (or *data*) as a named preset."""
        if data is None:
            data = {k: self._data[k] for k in self.PRESET_KEYS if k in self._data}
        presets = self._data.setdefault("presets", {})
        presets[name] = data
        self._data["active_preset"] = name
        self.save()

    def load_preset(self, name: str) -> dict | None:
        """Return the data dict for a preset, or None if not found."""
        return self._data.get("presets", {}).get(name)

    def delete_preset(self, name: str) -> None:
        """Delete a preset by name."""
        presets = self._data.get("presets", {})
        presets.pop(name, None)
        if self._data.get("active_preset") == name:
            self._data["active_preset"] = None
        self.save()

    def rename_preset(self, old_name: str, new_name: str) -> None:
        """Rename a preset."""
        presets = self._data.get("presets", {})
        if old_name not in presets:
            return
        presets[new_name] = presets.pop(old_name)
        if self._data.get("active_preset") == old_name:
            self._data["active_preset"] = new_name
        self.save()

    def set_active_preset(self, name) -> None:
        """Remember which preset is currently selected."""
        self._data["active_preset"] = name
        self.save()
