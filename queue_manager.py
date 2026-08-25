"""
Stream Auto Cutter — Queue Manager.

Runs the processing queue in a background QThread, emitting Qt signals
for the GUI to stay responsive.
"""

from __future__ import annotations

import threading
import time
from enum import Enum
from pathlib import Path
from typing import Any

from PySide6.QtCore import QThread, Signal

from ffmpeg_handler import FFmpegHandler, CancelledError
from video_processor import VideoProcessor


class TaskStatus(Enum):
    PENDING = "Ожидание"
    PROBING = "Анализ"
    PROCESSING = "Обработка"
    DONE = "Готово"
    ERROR = "Ошибка"
    CANCELLED = "Отменено"


class StreamTask:
    """Represents a single stream in the queue."""

    def __init__(self, file_path: str):
        self.file_path: str = file_path
        self.filename: str = Path(file_path).name
        self.stem: str = Path(file_path).stem
        self.duration: float = 0.0
        self.num_segments: int = 0
        self.status: TaskStatus = TaskStatus.PENDING
        self.current_segment: int = 0
        self.progress: float = 0.0
        self.error_message: str = ""
        # Extended progress info
        self.speed: float = 0.0           # encoding speed (e.g. 2.4x)
        self.start_time: float = 0.0      # time.time() when processing started
        self.elapsed_sec: float = 0.0     # seconds elapsed for this task
        self.eta_sec: float = 0.0         # estimated seconds remaining for this task


class QueueManager(QThread):
    """
    Manages a queue of StreamTask objects and processes them sequentially
    in a worker thread.
    """

    # --- signals (emitted from worker thread, received in GUI thread) ---
    task_updated = Signal(int)                      # task_index
    task_progress = Signal(int, int, float)          # task_idx, seg_idx, percent
    task_completed = Signal(int, bool, str)          # task_idx, success, error_msg
    queue_completed = Signal()
    log_message = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tasks: list[StreamTask] = []
        self._cancel_event = threading.Event()
        self._pause_flag = False
        self._settings_snapshot: dict = {}

    # ------------------------------------------------------------------
    # Task list management (called from GUI thread)
    # ------------------------------------------------------------------

    def add_task(self, file_path: str) -> int:
        task = StreamTask(file_path)
        self._tasks.append(task)
        return len(self._tasks) - 1

    def remove_task(self, index: int) -> None:
        if 0 <= index < len(self._tasks):
            self._tasks.pop(index)

    def clear_tasks(self) -> None:
        self._tasks.clear()

    def get_tasks(self) -> list[StreamTask]:
        return list(self._tasks)

    def task_count(self) -> int:
        return len(self._tasks)

    # ------------------------------------------------------------------
    # Control (called from GUI thread)
    # ------------------------------------------------------------------

    def start_processing(self, settings: dict) -> None:
        """Snapshot settings and start the worker thread."""
        self._settings_snapshot = dict(settings)
        self._cancel_event.clear()
        self._pause_flag = False
        self.start()

    def pause(self) -> None:
        self._pause_flag = True

    def resume(self) -> None:
        self._pause_flag = False

    def cancel(self) -> None:
        self._cancel_event.set()
        self._pause_flag = False

    @property
    def is_paused(self) -> bool:
        return self._pause_flag

    # ------------------------------------------------------------------
    # Worker (runs in background thread)
    # ------------------------------------------------------------------

    def run(self) -> None:
        ffmpeg = FFmpegHandler()
        processor = VideoProcessor(ffmpeg)
        settings = self._settings_snapshot
        seg_sec = settings.get("segment_duration_min", 16) * 60

        # ============================================================
        # Phase 1: probe ALL files upfront → total duration & chunks
        # ============================================================
        self.log_message.emit("Анализ всех файлов…")
        for idx, task in enumerate(self._tasks):
            if self._cancel_event.is_set():
                break
            if task.status in (TaskStatus.DONE, TaskStatus.CANCELLED):
                continue

            task.status = TaskStatus.PROBING
            self.task_updated.emit(idx)

            try:
                info = ffmpeg.probe_video(task.file_path)
                task.duration = info["duration"]
                task.num_segments = max(
                    1,
                    len(VideoProcessor.calculate_segments(task.duration, seg_sec)),
                )
                task.status = TaskStatus.PENDING  # back to pending, will process later
                self.task_updated.emit(idx)
            except Exception as exc:
                task.status = TaskStatus.ERROR
                task.error_message = str(exc)
                self.task_completed.emit(idx, False, str(exc))
                self.task_updated.emit(idx)

        # Emit update so GUI can show total chunks immediately
        total_chunks = sum(t.num_segments for t in self._tasks)
        total_dur = sum(t.duration for t in self._tasks)
        self.log_message.emit(
            f"Всего: {len(self._tasks)} файлов, "
            f"{total_chunks} кусков, "
            f"{int(total_dur // 60)} мин видео"
        )
        # notify GUI about all tasks (they now have duration & num_segments)
        for idx in range(len(self._tasks)):
            self.task_updated.emit(idx)

        # ============================================================
        # Phase 2: process each file
        # ============================================================
        for idx, task in enumerate(self._tasks):
            if self._cancel_event.is_set():
                task.status = TaskStatus.CANCELLED
                self.task_updated.emit(idx)
                continue

            if task.status in (TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.ERROR):
                continue

            # ---- process ----
            task.status = TaskStatus.PROCESSING
            task.start_time = time.time()
            self.task_updated.emit(idx)

            def _on_progress(
                seg_idx: int, total_segs: int, pct: float, speed: float,
                _i=idx, _task=task,
            ) -> None:
                _task.current_segment = seg_idx
                _task.num_segments = total_segs
                _task.speed = speed
                _task.progress = (
                    (seg_idx + pct / 100.0) / total_segs * 100.0
                )
                _task.elapsed_sec = time.time() - _task.start_time
                # ETA for remaining video in this task based on encoding speed
                if speed > 0 and _task.duration > 0:
                    processed_video_sec = _task.duration * _task.progress / 100.0
                    remaining_video_sec = _task.duration - processed_video_sec
                    _task.eta_sec = remaining_video_sec / speed
                else:
                    _task.eta_sec = 0.0
                self.task_progress.emit(_i, seg_idx, pct)
                self.task_updated.emit(_i)

            def _on_log(msg: str) -> None:
                self.log_message.emit(msg)

            try:
                processor.process_stream(
                    stream_path=task.file_path,
                    settings=settings,
                    progress_callback=_on_progress,
                    cancel_event=self._cancel_event,
                    pause_check=lambda: self._pause_flag,
                    log_callback=_on_log,
                )

                if self._cancel_event.is_set():
                    task.status = TaskStatus.CANCELLED
                    self.task_completed.emit(idx, False, "Отменено")
                else:
                    task.status = TaskStatus.DONE
                    task.progress = 100.0
                    task.elapsed_sec = time.time() - task.start_time
                    task.eta_sec = 0.0
                    self.task_completed.emit(idx, True, "")

            except CancelledError:
                task.status = TaskStatus.CANCELLED
                self.task_completed.emit(idx, False, "Отменено")

            except Exception as exc:
                task.status = TaskStatus.ERROR
                task.error_message = str(exc)
                self.task_completed.emit(idx, False, str(exc))

            self.task_updated.emit(idx)

        self.queue_completed.emit()
