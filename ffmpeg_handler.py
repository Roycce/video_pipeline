
"""
Stream Auto Cutter — FFmpeg Handler.

Low-level wrapper around FFmpeg / FFprobe: building commands, running
processes with real-time progress parsing, and bitrate calculations.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

# Hide console window on Windows
_CREATION_FLAGS = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


class FFmpegError(RuntimeError):
    """Raised when an FFmpeg process exits with a non-zero code."""


class CancelledError(RuntimeError):
    """Raised when the user cancels processing."""


class FFmpegHandler:
    """Builds and executes FFmpeg / FFprobe commands."""

    # ------------------------------------------------------------------
    # Probing
    # ------------------------------------------------------------------

    def probe_video(self, path: str | Path) -> dict:
        """
        Return metadata for a media file.

        Keys returned:
            duration   – float, seconds
            width      – int
            height     – int
            fps        – float
            has_audio  – bool
            video_codec – str
        """
        cmd = [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            creationflags=_CREATION_FLAGS,
        )
        if result.returncode != 0:
            raise FFmpegError(f"ffprobe failed for {path}:\n{result.stderr[:1000]}")

        data = json.loads(result.stdout)

        # --- video stream ---
        video = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
            None,
        )
        if video is None:
            raise FFmpegError(f"No video stream found in {path}")

        width = int(video.get("width", 0))
        height = int(video.get("height", 0))
        video_codec = video.get("codec_name", "unknown")

        # fps
        fps = 0.0
        r_frame_rate = video.get("r_frame_rate", "0/1")
        if "/" in r_frame_rate:
            num, den = r_frame_rate.split("/")
            if int(den) > 0:
                fps = round(int(num) / int(den), 3)

        # duration — prefer format.duration, fall back to stream
        duration = float(data.get("format", {}).get("duration", 0))
        if duration == 0:
            duration = float(video.get("duration", 0))

        # --- audio stream ---
        audio = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
            None,
        )

        return {
            "duration": duration,
            "width": width,
            "height": height,
            "fps": fps,
            "has_audio": audio is not None,
            "video_codec": video_codec,
        }

    # ------------------------------------------------------------------
    # Bitrate calculation
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_bitrate(
        target_size_mb: float,
        duration_sec: float,
        audio_bitrate_kbps: int = 128,
    ) -> int:
        """
        Return video bitrate (kbps) required to hit *target_size_mb*
        for the given duration and audio bitrate.
        """
        target_bits = target_size_mb * 1024 * 1024 * 8          # MB → bits
        audio_bits = audio_bitrate_kbps * 1000 * duration_sec   # kbps → bits
        video_bits = target_bits - audio_bits
        if video_bits <= 0:
            video_bits = target_bits * 0.85                     # safety floor
        return max(500, int(video_bits / duration_sec / 1000))

    # ------------------------------------------------------------------
    # Command builders
    # ------------------------------------------------------------------

    def build_split_command(
        self,
        input_path: str,
        start_sec: float,
        duration_sec: float,
        output_path: str,
    ) -> list[str]:
        """Stream-copy split (instant, keyframe-aligned)."""
        return [
            "ffmpeg", "-y",
            "-ss", f"{start_sec:.3f}",
            "-i", str(input_path),
            "-t", f"{duration_sec:.3f}",
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            str(output_path),
        ]

    def build_processing_command(
        self,
        *,
        segment_path: str,
        output_path: str,
        settings: dict,
        intro_path: str | None = None,
        outro_path: str | None = None,
        segment_duration: float = 960.0,
        target_w: int = 1920,
        target_h: int = 1080,
        target_fps: str | None = None,
        intro_duration: float = 0.0,
        outro_duration: float = 0.0,
    ) -> list[str]:
        """
        Build a single FFmpeg command that combines:
        concat (intro + segment + outro) → scale/fps → logo overlay → encode.
        """
        # ---- inputs ----
        inputs: list[str] = []
        idx = 0
        indices: dict[str, int] = {}

        if intro_path:
            inputs += ["-i", str(intro_path)]
            indices["intro"] = idx
            idx += 1

        inputs += ["-i", str(segment_path)]
        indices["segment"] = idx
        idx += 1

        if outro_path:
            inputs += ["-i", str(outro_path)]
            indices["outro"] = idx
            idx += 1

        logos = []
        if settings.get("logo_enabled", False):
            logos = settings.get("logos", [])
        
        logo_indices = []
        for logo in logos:
            path = logo.get("path")
            if path:
                if logo.get("type") == "video_chromakey":
                    inputs += ["-stream_loop", "-1"]
                inputs += ["-i", str(path)]
                logo_indices.append(idx)
                idx += 1

        needs_concat = "intro" in indices or "outro" in indices
        needs_logo = len(logo_indices) > 0
        needs_scale = settings.get("resolution", "source") != "source"
        needs_fps = target_fps is not None
        needs_filter = needs_concat or needs_logo or needs_scale or needs_fps

        # ---- total output duration (for bitrate calc) ----
        total_output_duration = segment_duration + intro_duration + outro_duration

        # ---- simple path (no filtergraph) ----
        if not needs_filter:
            cmd = ["ffmpeg", "-y"] + inputs
            cmd += self._encoding_args(settings, total_output_duration)
            cmd.append(str(output_path))
            return cmd

        # ---- complex filtergraph ----
        filters: list[str] = []
        video_out = ""
        audio_out = ""
        audio_labeled = False

        # build fps suffix
        fps_suffix = f",fps={target_fps}" if needs_fps else ""

        if needs_concat:
            # normalise every concat input to identical resolution / fps / pixfmt
            concat_v_labels = []
            concat_a_labels = []
            for key in ("intro", "segment", "outro"):
                if key not in indices:
                    continue
                i = indices[key]
                vl = f"v{key}"
                al = f"a{key}"
                filters.append(
                    f"[{i}:v]scale={target_w}:{target_h}"
                    f":force_original_aspect_ratio=decrease,"
                    f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
                    f"format=yuv420p,setsar=1{fps_suffix}[{vl}]"
                )
                filters.append(
                    f"[{i}:a]aresample=44100,"
                    f"aformat=sample_fmts=fltp:channel_layouts=stereo[{al}]"
                )
                concat_v_labels.append(vl)
                concat_a_labels.append(al)

            n = len(concat_v_labels)
            interleaved = "".join(
                f"[{v}][{a}]"
                for v, a in zip(concat_v_labels, concat_a_labels)
            )
            filters.append(
                f"{interleaved}concat=n={n}:v=1:a=1[concatv][concata]"
            )
            video_out = "concatv"
            audio_out = "concata"
            audio_labeled = True
        else:
            # single segment — optional scale / fps
            si = indices["segment"]
            if needs_scale or needs_fps:
                filters.append(
                    f"[{si}:v]scale={target_w}:{target_h}"
                    f":force_original_aspect_ratio=decrease,"
                    f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,"
                    f"format=yuv420p,setsar=1{fps_suffix}[vprocessed]"
                )
                video_out = "vprocessed"
            else:
                video_out = f"{si}:v"
            audio_out = f"{si}:a"
            audio_labeled = False

        # ---- logo overlay ----
        if needs_logo:
            # if video_out is a direct reference, wrap it with null so we can chain
            if ":" in video_out:
                filters.append(f"[{video_out}]null[vbase]")
                video_out = "vbase"

            for i, (logo, li) in enumerate(zip(logos, logo_indices)):
                if not logo.get("path"):
                    continue
                    
                logo_size_pct = logo.get("size", 15) / 100.0
                logo_opacity = logo.get("opacity", 80) / 100.0
                position = logo.get("position", "top_right")
                display = logo.get("display", "full")

                margin = 20
                pos_map = {
                    "top_left": (str(margin), str(margin)),
                    "top_right": (f"W-w-{margin}", str(margin)),
                    "bottom_left": (str(margin), f"H-h-{margin}"),
                    "bottom_right": (f"W-w-{margin}", f"H-h-{margin}"),
                    "center": (f"(W-w)/2", f"(H-h)/2"),
                }
                ox, oy = pos_map.get(position, pos_map["top_right"])

                # enable expression
                enable = ""
                if display == "first_n":
                    t = logo.get("time_end", 10)
                    enable = f":enable='between(t,0,{t})'"
                elif display == "last_n":
                    t = logo.get("time_start", 10)
                    start_t = max(0, total_output_duration - t)
                    enable = f":enable='gte(t,{start_t:.1f})'"
                elif display == "custom":
                    ts = logo.get("time_start", 0)
                    te = logo.get("time_end", 10)
                    enable = f":enable='between(t,{ts},{te})'"

                logo_w = max(32, int(target_w * logo_size_pct))
                logo_lbl = f"logo{i}"
                
                angle = logo.get("angle", 0)
                rotate_filter = f"rotate={angle}*PI/180:c=none," if angle != 0 else ""

                if logo.get("type") == "video_chromakey":
                    color_str = logo.get("color", "Green")
                    if "Blue" in color_str:
                        ckey = "0x0000FF"
                    elif "Black" in color_str:
                        ckey = "0x000000"
                    else:
                        ckey = "0x00FF00"
                        
                    filters.append(
                        f"[{li}:v]colorkey={ckey}:0.3:0.15,format=rgba,"
                        f"scale={logo_w}:-1,{rotate_filter}"
                        f"colorchannelmixer=aa={logo_opacity:.2f}[{logo_lbl}]"
                    )
                else:
                    filters.append(
                        f"[{li}:v]format=rgba,"
                        f"scale={logo_w}:-1,{rotate_filter}"
                        f"colorchannelmixer=aa={logo_opacity:.2f}[{logo_lbl}]"
                    )

                next_out = f"outv{i}"
                is_last = (i == len(logo_indices) - 1)
                fmt = ",format=yuv420p" if is_last else ""
                
                filters.append(
                    f"[{video_out}][{logo_lbl}]overlay={ox}:{oy}:eof_action=pass{enable}{fmt}[{next_out}]"
                )
                video_out = next_out
        else:
            # no logo, but we might still need to ensure yuv420p if other filters were used
            if ":" not in video_out:
                filters.append(f"[{video_out}]format=yuv420p[outv]")
                video_out = "outv"

        # ---- assemble command ----
        cmd = ["ffmpeg", "-y"] + inputs
        cmd += ["-filter_complex", ";".join(filters)]

        # map video
        if ":" in video_out:
            cmd += ["-map", video_out]
        else:
            cmd += ["-map", f"[{video_out}]"]

        # map audio
        if audio_labeled:
            cmd += ["-map", f"[{audio_out}]"]
        else:
            cmd += ["-map", audio_out]

        cmd += self._encoding_args(settings, total_output_duration)
        cmd.append(str(output_path))
        return cmd

    # ------------------------------------------------------------------
    # Encoding helpers
    # ------------------------------------------------------------------

    def _encoding_args(self, settings: dict, duration: float) -> list[str]:
        """Return the encoding portion of an FFmpeg command."""
        args: list[str] = []
        codec = settings.get("codec", "h264_nvenc")
        args += ["-c:v", codec]

        if settings.get("file_size_limit_enabled") and settings.get("file_size_limit_mb"):
            br = self.calculate_bitrate(
                settings["file_size_limit_mb"],
                duration,
                settings.get("audio_bitrate", 128),
            )
            if "videotoolbox" in codec:
                args += ["-b:v", f"{br}k"]
            else:
                args += ["-b:v", f"{br}k",
                         "-maxrate", f"{int(br * 1.5)}k",
                         "-bufsize", f"{int(br * 2)}k"]
        else:
            if "nvenc" in codec:
                args += ["-preset", "p4", "-tune", "hq",
                         "-cq", "23"]
            elif "videotoolbox" in codec:
                args += ["-q:v", "65", "-tag:v", "hvc1"]
            else:
                args += ["-crf", "18", "-preset", "slow"]

        audio_br = settings.get("audio_bitrate", 128)
        args += ["-c:a", "aac", "-b:a", f"{audio_br}k"]
        return args

    # ------------------------------------------------------------------
    # Runner
    # ------------------------------------------------------------------

    def run_command(
        self,
        cmd: list[str],
        total_duration: float | None = None,
        progress_callback: Callable[[float], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """
        Execute an FFmpeg command.

        If *total_duration* and *progress_callback* are provided the method
        uses ``-progress pipe:1`` to report real-time progress (0–100 %).
        """
        cmd = list(cmd)  # copy
        use_progress = bool(progress_callback and total_duration and total_duration > 0)
        if use_progress:
            # insert progress flags right after the binary name
            cmd = [cmd[0], "-progress", "pipe:1", "-nostats"] + cmd[1:]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_CREATION_FLAGS,
        )

        # drain stderr in a background thread to avoid deadlocks
        stderr_lines: list[str] = []

        def _drain_stderr():
            assert process.stderr is not None
            for raw_line in iter(process.stderr.readline, b""):
                stderr_lines.append(raw_line.decode("utf-8", errors="replace"))

        err_thread = threading.Thread(target=_drain_stderr, daemon=True)
        err_thread.start()

        try:
            if use_progress:
                assert process.stdout is not None
                for raw_line in iter(process.stdout.readline, b""):
                    # cancellation check
                    if cancel_event and cancel_event.is_set():
                        process.terminate()
                        process.wait(timeout=10)
                        raise CancelledError("Обработка отменена пользователем")

                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if line.startswith("out_time="):
                        time_str = line.split("=", 1)[1]
                        current = self._parse_time(time_str)
                        if current is not None and total_duration > 0:
                            pct = min(100.0, current / total_duration * 100)
                            progress_callback(pct)
            else:
                if process.stdout:
                    process.stdout.read()

            process.wait()
        except CancelledError:
            raise
        except Exception:
            process.kill()
            process.wait()
            raise
        finally:
            err_thread.join(timeout=5)

        if process.returncode != 0:
            tail = "".join(stderr_lines[-30:])
            raise FFmpegError(
                f"FFmpeg exited with code {process.returncode}:\n{tail}"
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_time(time_str: str) -> float | None:
        """Parse ``HH:MM:SS.micro`` into seconds."""
        m = re.match(r"(\d+):(\d+):(\d+\.?\d*)", time_str)
        if not m:
            return None
        h, mi, s = m.groups()
        return int(h) * 3600 + int(mi) * 60 + float(s)
