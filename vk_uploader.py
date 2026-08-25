"""
Stream Auto Cutter — VK Uploader Module.

Uploads finished video segments to VKontakte in a background QThread,
emitting Qt signals so the GUI stays responsive.

После успешной загрузки:
  - видеофайл перемещается в подпапку uploaded/ (рядом с исходной папкой)
  - использованный заголовок удаляется из titles.txt (первая строка)
"""

from __future__ import annotations

import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal


class VkUploader(QThread):
    """
    Worker thread that uploads a list of video files to VK one by one.

    Signals
    -------
    progress(current, total, filename)   -- emitted before each upload starts
    file_done(filename, video_id, ok)    -- emitted after each upload attempt
    log_message(text)                    -- timestamped log lines
    finished_all(success, errors)        -- emitted when the run is complete
    """

    progress = Signal(int, int, str)      # current (1-based), total, filename
    file_done = Signal(str, str, bool)    # filename, video_id/error, ok?
    log_message = Signal(str)
    finished_all = Signal(int, int)       # uploaded OK, errors

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token: str = ""
        self._group_id: Optional[int] = None
        self._files: list[str] = []
        self._titles: list[str] = []
        self._titles_path: str = ""
        self._delay: int = 10
        self._max_videos: int = 150
        self._cancelled: bool = False

    def configure(
        self,
        token: str,
        files: list[str],
        titles: list[str],
        titles_path: str = "",
        group_id: Optional[int] = None,
        delay: int = 10,
        max_videos: int = 150,
    ) -> None:
        self._token = token
        self._files = files
        self._titles = titles
        self._titles_path = titles_path
        self._group_id = group_id
        self._delay = delay
        self._max_videos = max_videos
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    # ------------------------------------------------------------------
    # Main upload loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        try:
            import vk_api
            from vk_api.upload import VkUpload
        except ImportError:
            self._log("Библиотека vk_api не установлена. Запустите: pip install vk_api")
            self.finished_all.emit(0, 0)
            return

        if not self._token:
            self._log("Токен ВКонтакте не указан.")
            self.finished_all.emit(0, 0)
            return

        if not self._files:
            self._log("Нет файлов для загрузки.")
            self.finished_all.emit(0, 0)
            return

        try:
            vk_session = vk_api.VkApi(token=self._token)
            upload = VkUpload(vk_session)
        except Exception as e:
            self._log(f"Ошибка авторизации ВК: {e}")
            self.finished_all.emit(0, 0)
            return

        total = min(len(self._files), len(self._titles), self._max_videos)
        success_count = 0
        error_count = 0

        self._log("=" * 50)
        self._log(f"Загрузка в ВКонтакте: {total} файлов")
        if self._group_id:
            self._log(f"Группа: {self._group_id}")
        else:
            self._log("Назначение: личная страница")
        self._log("=" * 50)

        for i in range(total):
            if self._cancelled:
                self._log("Загрузка отменена.")
                break

            filepath = self._files[i]
            title = self._titles[i]
            filename = Path(filepath).name

            self.progress.emit(i + 1, total, filename)
            self._log(f"[{i+1}/{total}] Загрузка: {filename}")
            self._log(f"   -> Заголовок: {title}")

            upload_kwargs: dict = {
                "video_file": filepath,
                "name": title,
                "wallpost": 0,
            }
            if self._group_id:
                upload_kwargs["group_id"] = self._group_id

            try:
                result = upload.video(**upload_kwargs)
                video_id = str(result.get("video_id", "OK"))
                self._log(f"   ✓ Загружен (id: {video_id})")
                self.file_done.emit(filename, video_id, True)
                success_count += 1

                # --- После успешной загрузки ---
                self._move_to_uploaded(filepath)
                self._pop_first_title()

            except Exception as e:
                err_str = str(e)
                self._log(f"   ✗ Ошибка: {err_str}")
                self.file_done.emit(filename, err_str, False)
                error_count += 1

            if i < total - 1 and not self._cancelled:
                self._log(f"   Пауза {self._delay} сек...")
                for _ in range(self._delay * 10):
                    if self._cancelled:
                        break
                    time.sleep(0.1)

        self._log("=" * 50)
        self._log(f"Готово. Успешно: {success_count}, Ошибок: {error_count}")
        self._log("=" * 50)
        self.finished_all.emit(success_count, error_count)

    # ------------------------------------------------------------------
    # Post-upload helpers
    # ------------------------------------------------------------------

    def _move_to_uploaded(self, filepath: str) -> None:
        """Переносит файл в подпапку uploaded/ рядом с исходной папкой."""
        src = Path(filepath)
        if not src.exists():
            return
        dest_dir = src.parent / "uploaded"
        try:
            dest_dir.mkdir(exist_ok=True)
            dest = dest_dir / src.name
            # Если файл с таким именем уже есть — добавляем суффикс
            if dest.exists():
                dest = dest_dir / f"{src.stem}_dup{src.suffix}"
            shutil.move(str(src), str(dest))
            self._log(f"   → Перемещён в uploaded/{src.name}")
        except Exception as e:
            self._log(f"   ⚠ Не удалось переместить файл: {e}")

    def _pop_first_title(self) -> None:
        """Удаляет первую строку из titles.txt после успешной загрузки."""
        if not self._titles_path:
            return
        path = Path(self._titles_path)
        if not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            # Убираем первую непустую строку
            remaining = lines[1:] if lines else []
            path.write_text("\n".join(remaining) + ("\n" if remaining else ""), encoding="utf-8")
        except Exception as e:
            self._log(f"   ⚠ Не удалось обновить titles.txt: {e}")

    # ------------------------------------------------------------------

    def _log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_message.emit(f"[{timestamp}] {text}")
