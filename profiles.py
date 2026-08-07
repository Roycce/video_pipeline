"""
Stream Auto Cutter — Profiles Module.

Named presets of processing settings that users can save, load, and delete.
Built-in profiles are always available and cannot be deleted.
"""

import json
from pathlib import Path

BUILTIN_PROFILES: dict[str, dict] = {
    "YouTube 1080p": {
        "segment_duration_min": 16,
        "resolution": "1920x1080",
        "fps": "source",
        "codec": "h264_nvenc",
        "file_size_limit_enabled": True,
        "file_size_limit_mb": 650,
        "audio_bitrate": 128,
    },
    "YouTube 4K": {
        "segment_duration_min": 16,
        "resolution": "3840x2160",
        "fps": "source",
        "codec": "hevc_nvenc",
        "file_size_limit_enabled": False,
        "file_size_limit_mb": 2000,
        "audio_bitrate": 256,
    },
    "Быстрый 720p": {
        "segment_duration_min": 16,
        "resolution": "1280x720",
        "fps": "30",
        "codec": "h264_nvenc",
        "file_size_limit_enabled": True,
        "file_size_limit_mb": 400,
        "audio_bitrate": 128,
    },
}


class ProfileManager:
    """Manages named setting profiles with JSON persistence."""

    def __init__(self, profiles_path: str | Path | None = None):
        if profiles_path is None:
            profiles_path = Path(__file__).parent / "profiles.json"
        self._path = Path(profiles_path)
        self._user_profiles: dict[str, dict] = {}
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                self._user_profiles = json.load(fh)
        except (json.JSONDecodeError, OSError):
            self._user_profiles = {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as fh:
            json.dump(self._user_profiles, fh, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def get_all_names(self) -> list[str]:
        """Return ordered list: built-in profiles first, then user profiles."""
        names = list(BUILTIN_PROFILES.keys())
        for name in self._user_profiles:
            if name not in BUILTIN_PROFILES:
                names.append(name)
        return names

    def get_profile(self, name: str) -> dict | None:
        """Return a copy of the named profile or None."""
        if name in BUILTIN_PROFILES:
            return dict(BUILTIN_PROFILES[name])
        return self._user_profiles.get(name)

    def save_profile(self, name: str, data: dict) -> None:
        """Save (or overwrite) a user profile."""
        self._user_profiles[name] = dict(data)
        self.save()

    def delete_profile(self, name: str) -> bool:
        """Delete a user profile. Returns False if it was built-in or missing."""
        if name in self._user_profiles:
            del self._user_profiles[name]
            self.save()
            return True
        return False

    def is_builtin(self, name: str) -> bool:
        return name in BUILTIN_PROFILES
