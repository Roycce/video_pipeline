"""
Stream Auto Cutter — Video Processor.

High-level processing pipeline for a single stream:
probe → split into segments → for each segment: concat + overlay + encode.
"""

from __future__ import annotations

import math
import shutil
import threading
from pathlib import Path
from typing import Callable

from ffmpeg_handler import FFmpegHandler


class VideoProcessor:
    """
    Processes one stream file through the full pipeline.

    This is a plain class (not a QObject) — the caller (QueueManager)
    provides callbacks for progress, logging, and cancellation.
    """

    def __init__(self, ffmpeg: FFmpegHandler):
        self._ffmpeg = ffmpeg
        # caches for intro / outro probes (same files across segments)
        self._intro_info: dict | None = None
        self._outro_info: dict | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_stream(
        self,
        stream_path: str,
        settings: dict,
        progress_callback: Callable[[int, float], None] | None = None,
        cancel_event: threading.Event | None = None,
        pause_check: Callable[[], bool] | None = None,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        """
        Full pipeline for *stream_path*.

        Parameters
        ----------
        progress_callback(segment_idx, percent)
            Called repeatedly during encoding with current segment index
            and 0-100 % progress for that segment.
        cancel_event
            A ``threading.Event`` — if set, processing stops ASAP.
        pause_check()
            Returns ``True`` while paused. Checked between segments.
        log_callback(message)
            Receives human-readable log messages.
        """

        def _log(msg: str) -> None:
            if log_callback:
                log_callback(msg)

        # 1. Probe source
        _log(f"Анализ: {Path(stream_path).name}")
        source_info = self._ffmpeg.probe_video(stream_path)
        total_duration = source_info["duration"]
        _log(
            f"  Длительность: {self._fmt_time(total_duration)}, "
            f"{source_info['width']}×{source_info['height']}, "
            f"{source_info['fps']} fps"
        )

        # 2. Resolve intro / outro
        intro_path = self._resolve_asset(settings, "intro")
        outro_path = self._resolve_asset(settings, "outro")

        intro_dur = 0.0
        outro_dur = 0.0
        if intro_path:
            self._intro_info = self._ffmpeg.probe_video(intro_path)
            intro_dur = self._intro_info["duration"]
            _log(f"  Интро: {intro_dur:.1f} сек")
        if outro_path:
            self._outro_info = self._ffmpeg.probe_video(outro_path)
            outro_dur = self._outro_info["duration"]
            _log(f"  Аутро: {outro_dur:.1f} сек")

        # 3. Calculate segments
        seg_min = settings.get("segment_duration_min", 16)
        seg_sec = seg_min * 60
        segments = self.calculate_segments(total_duration, seg_sec)
        n_segments = len(segments)
        _log(f"  Нарезка на {n_segments} частей по ~{seg_min} мин")

        # 4. Resolve target resolution / fps
        target_w, target_h = self._resolve_resolution(settings, source_info)
        target_fps = self._resolve_fps(settings, source_info)

        # 5. Prepare output directory
        source_dir = Path(stream_path).parent
        output_dir = source_dir / settings.get("output_subfolder", "output")
        output_dir.mkdir(parents=True, exist_ok=True)

        temp_dir = output_dir / ".temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        stem = Path(stream_path).stem

        # 6. Process each segment
        try:
            for seg_idx, (start, dur) in enumerate(segments):
                # ---- pause / cancel ----
                self._wait_if_paused(pause_check, cancel_event)
                if cancel_event and cancel_event.is_set():
                    _log("⏹ Обработка отменена")
                    return

                _log(f"▶ Сегмент {seg_idx + 1}/{n_segments}  "
                     f"[{self._fmt_time(start)} → {self._fmt_time(start + dur)}]")

                # ---- split (stream copy) ----
                temp_path = temp_dir / f"{stem}_seg{seg_idx + 1:03d}.mp4"
                split_cmd = self._ffmpeg.build_split_command(
                    str(stream_path), start, dur, str(temp_path),
                )
                self._ffmpeg.run_command(split_cmd, cancel_event=cancel_event)

                # ---- build & run processing command ----
                part_num = seg_idx + 1
                out_path = output_dir / f"{stem}_part{part_num:02d}.mp4"

                total_out_dur = dur + intro_dur + outro_dur

                proc_cmd = self._ffmpeg.build_processing_command(
                    segment_path=str(temp_path),
                    output_path=str(out_path),
                    settings=settings,
                    intro_path=intro_path,
                    outro_path=outro_path,
                    segment_duration=dur,
                    target_w=target_w,
                    target_h=target_h,
                    target_fps=str(target_fps) if target_fps else None,
                    intro_duration=intro_dur,
                    outro_duration=outro_dur,
                )

                def _on_progress(pct: float, _si=seg_idx):
                    if progress_callback:
                        progress_callback(_si, pct)

                self._ffmpeg.run_command(
                    proc_cmd,
                    total_duration=total_out_dur,
                    progress_callback=_on_progress,
                    cancel_event=cancel_event,
                )

                # cleanup temp segment
                temp_path.unlink(missing_ok=True)
                _log(f"  ✓ Часть {part_num} готова → {out_path.name}")

        finally:
            # cleanup temp dir (if empty)
            try:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except OSError:
                pass

        _log(f"✅ {Path(stream_path).name} — обработка завершена "
             f"({n_segments} частей)")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def calculate_segments(
        total_duration: float, segment_duration: float
    ) -> list[tuple[float, float]]:
        """
        Return list of (start_sec, duration_sec) for each segment.
        If the last segment is shorter than segment_duration, its start
        time is shifted backwards to overlap, ensuring all segments are
        exactly segment_duration (unless total_duration < segment_duration).
        """
        if segment_duration <= 0:
            segment_duration = 960
            
        if total_duration <= segment_duration:
            return [(0.0, total_duration)]
            
        n = max(1, math.ceil(total_duration / segment_duration))
        segments = []
        for i in range(n):
            start = i * segment_duration
            dur = min(segment_duration, total_duration - start)
            
            # overlap last segment to make it exactly segment_duration
            if i == n - 1 and dur < segment_duration:
                start = max(0.0, total_duration - segment_duration)
                dur = segment_duration
                
            if dur > 0:
                segments.append((start, dur))
        return segments

    @staticmethod
    def _resolve_resolution(settings: dict, info: dict) -> tuple[int, int]:
        res = settings.get("resolution", "source")
        if res == "source":
            return info["width"], info["height"]
        if res == "custom":
            return (
                settings.get("custom_resolution_w", 1920),
                settings.get("custom_resolution_h", 1080),
            )
        parts = res.split("x")
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
        return info["width"], info["height"]

    @staticmethod
    def _resolve_fps(settings: dict, info: dict) -> float | None:
        fps = settings.get("fps", "source")
        if fps == "source":
            return None
        try:
            return float(fps)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _resolve_asset(settings: dict, kind: str) -> str | None:
        """Return path to intro/outro/logo if enabled and file exists."""
        enabled = settings.get(f"{kind}_enabled", False)
        path = settings.get(f"{kind}_path", "")
        if enabled and path and Path(path).is_file():
            return path
        return None

    @staticmethod
    def _wait_if_paused(
        pause_check: Callable[[], bool] | None,
        cancel_event: threading.Event | None,
    ) -> None:
        """Block while paused, checking for cancellation."""
        if not pause_check:
            return
        import time
        while pause_check():
            if cancel_event and cancel_event.is_set():
                return
            time.sleep(0.2)

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"
