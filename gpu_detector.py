"""
Stream Auto Cutter — GPU Detector.

Auto-detects available hardware video encoders by performing a quick
test encode.  Results are cached for the lifetime of the process.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Dict

# Hide console window on Windows
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

# Encoders we care about, grouped by backend
_ENCODERS_TO_TEST: list[str] = [
    "h264_nvenc",
    "hevc_nvenc",
    "h264_videotoolbox",
    "hevc_videotoolbox",
]

_cache: Dict[str, bool] | None = None


def _test_encoder(encoder: str, ffmpeg_path: str = "ffmpeg") -> bool:
    """Return True if *encoder* can produce output on this machine."""
    cmd = [
        ffmpeg_path,
        "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "nullsrc=s=256x256:d=0.1",
        "-c:v", encoder,
        "-frames:v", "1",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            timeout=15,
            creationflags=_CREATION_FLAGS,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def detect_available_encoders(
    ffmpeg_path: str = "ffmpeg",
    force_refresh: bool = False,
) -> Dict[str, bool]:
    """
    Return a dict ``{encoder_name: is_available}`` for every encoder in
    ``_ENCODERS_TO_TEST``.  The first call runs actual test encodes;
    subsequent calls return the cached result unless *force_refresh* is set.
    """
    global _cache
    if _cache is not None and not force_refresh:
        return dict(_cache)

    result: Dict[str, bool] = {}
    for enc in _ENCODERS_TO_TEST:
        result[enc] = _test_encoder(enc, ffmpeg_path)

    _cache = result
    return dict(result)


def best_available_encoder(
    preferred: str = "h264_nvenc",
    ffmpeg_path: str = "ffmpeg",
) -> str:
    """
    Return the best available encoder.

    Tries *preferred* first, then falls through NVENC → VideoToolbox → CPU.
    Always returns a usable encoder string.
    """
    avail = detect_available_encoders(ffmpeg_path)

    if avail.get(preferred, False):
        return preferred

    # Priority order
    fallback_order = [
        "h264_nvenc", "hevc_nvenc",
        "h264_videotoolbox", "hevc_videotoolbox",
    ]
    for enc in fallback_order:
        if avail.get(enc, False):
            return enc

    # Ultimate fallback — CPU
    if "hevc" in preferred or "265" in preferred:
        return "libx265"
    return "libx264"
