"""
Stream Auto Cutter — GUI Module.

Main application window and widgets using PySide6.
"""

from __future__ import annotations

import os
import re
import sys
import time
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QUrl, QStandardPaths
from PySide6.QtGui import QIcon, QPainter, QColor, QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QGroupBox, QLabel, QComboBox, QSpinBox, QRadioButton,
    QPushButton, QCheckBox, QTableWidget, QTableWidgetItem, QSizePolicy,
    QHeaderView, QFileDialog, QTextEdit, QProgressBar, QMessageBox,
    QSplitter, QDialog, QDialogButtonBox, QListWidget, QLineEdit,
    QInputDialog, QAbstractItemView, QScrollArea, QFrame,
)

from vk_uploader import VkUploader
from queue_manager import QueueManager, TaskStatus
from settings import Settings
from gpu_detector import detect_available_encoders
from ffmpeg_handler import get_ffmpeg_path


# ----------------------------------------------------------------------
# Constants & helpers
# ----------------------------------------------------------------------

VIDEO_EXTS = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".ts")
VIDEO_FILTER = "Видео (" + " ".join(f"*{e}" for e in VIDEO_EXTS) + ")"
IMAGE_FILTER = "Картинки (*.png *.jpg *.jpeg *.webp)"
LOGO_VIDEO_FILTER = "Видео (*.mp4 *.mov *.mkv *.webm)"
AUDIO_FILTER = "Аудио (*.mp3 *.wav *.aac *.ogg *.m4a *.flac)"

POSITIONS = [
    ("top_left", "Вверху слева"),
    ("top_right", "Вверху справа"),
    ("bottom_left", "Внизу слева"),
    ("bottom_right", "Внизу справа"),
    ("center", "По центру"),
]
POSITION_NAMES = dict(POSITIONS)

LOGO_DISPLAY = [
    ("full", "Всё видео"),
    ("segment_only", "Только основная часть (без интро/аутро)"),
    ("first_n", "Первые N секунд"),
    ("last_n", "Последние N секунд"),
    ("custom", "Свой интервал"),
]
LOGO_DISPLAY_NAMES = dict(LOGO_DISPLAY)

DURATION_PRESETS = [5, 10, 16, 20, 30]

CPU_CODECS = ("libx264", "libx265")

STATUS_COLORS = {
    TaskStatus.DONE: "#6cc070",
    TaskStatus.ERROR: "#e06c75",
    TaskStatus.CANCELLED: "#909090",
    TaskStatus.PROCESSING: "#4fa3e0",
    TaskStatus.PROBING: "#4fa3e0",
}

MUTED = "color: #8a8a8a;"
HINT = "color: #8a8a8a; font-size: 11px;"


def natural_key(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def plural(n: int, one: str, few: str, many: str) -> str:
    """plural(3, "часть", "части", "частей") -> "3 части" """
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        word = one
    elif 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        word = few
    else:
        word = many
    return f"{n} {word}"


def hint_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    lbl.setStyleSheet(HINT)
    return lbl


def combo_select_data(combo: QComboBox, value, fallback_index: int = 0) -> None:
    idx = combo.findData(value)
    combo.setCurrentIndex(idx if idx >= 0 else fallback_index)


def parse_vk_group_id(text: str) -> int | None:
    """Accept '123', '-123', 'club123', 'public123' or a full vk.com/club123 URL."""
    m = re.search(r"(\d+)\s*/?\s*$", text.strip())
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------------
# Reusable widgets
# ----------------------------------------------------------------------

class ElidedLabel(QLabel):
    """Label that shortens long paths in the middle: C:\\…\\video.mp4"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = ""
        self.setMinimumWidth(60)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self._refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self):
        fm = self.fontMetrics()
        self.setText(fm.elidedText(self._full, Qt.TextElideMode.ElideMiddle, max(20, self.width())))


class PathField(QWidget):
    """Path label + «Обзор…» + «✕» (clear). Shows a warning if the file is missing."""

    pathChanged = Signal(str)

    def __init__(self, placeholder="Не выбрано", mode="file", file_filter="",
                 dialog_title="Выберите файл", parent=None):
        super().__init__(parent)
        self._path = ""
        self._placeholder = placeholder
        self._mode = mode
        self._filter = file_filter
        self._title = dialog_title

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.label = ElidedLabel()
        self.btn_browse = QPushButton("Обзор…")
        self.btn_browse.clicked.connect(self._browse)
        self.btn_clear = QPushButton("✕")
        self.btn_clear.setFixedWidth(32)
        self.btn_clear.setToolTip("Сбросить")
        self.btn_clear.clicked.connect(lambda: self.set_path("", emit=True))
        lay.addWidget(self.label, stretch=1)
        lay.addWidget(self.btn_browse)
        lay.addWidget(self.btn_clear)
        self._refresh()

    def path(self) -> str:
        return self._path

    def exists(self) -> bool:
        if not self._path:
            return False
        p = Path(self._path)
        return p.is_dir() if self._mode == "dir" else p.is_file()

    def set_path(self, path: str, emit: bool = False) -> None:
        self._path = path or ""
        self._refresh()
        if emit:
            self.pathChanged.emit(self._path)

    def set_filter(self, file_filter: str) -> None:
        self._filter = file_filter

    def _browse(self):
        start = ""
        if self._path:
            p = Path(self._path)
            start = str(p if p.is_dir() else p.parent)
        if self._mode == "dir":
            path = QFileDialog.getExistingDirectory(self, self._title, start)
        else:
            path, _ = QFileDialog.getOpenFileName(self, self._title, start, self._filter)
        if path:
            self.set_path(path, emit=True)

    def _refresh(self):
        self.btn_clear.setEnabled(bool(self._path))
        if not self._path:
            self.label.set_full_text(self._placeholder)
            self.label.setStyleSheet(MUTED + " font-style: italic;")
            self.label.setToolTip("")
        elif not self.exists():
            self.label.set_full_text("⚠ " + self._path)
            self.label.setStyleSheet("color: #e06c75;")
            self.label.setToolTip(f"Не найдено: {self._path}")
        else:
            self.label.set_full_text(self._path)
            self.label.setStyleSheet("")
            self.label.setToolTip(self._path)


class QueueTable(QTableWidget):
    """Table that shows a hint when empty."""

    EMPTY_TEXT = ("Перетащите сюда видео или папку с видео\n"
                  "или нажмите «Добавить файлы…»")

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.rowCount() == 0:
            p = QPainter(self.viewport())
            p.setPen(QColor("#7a7a7a"))
            p.drawText(self.viewport().rect().adjusted(10, 10, -10, -10),
                       Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       self.EMPTY_TEXT)
            p.end()


# ----------------------------------------------------------------------
# Dialogs
# ----------------------------------------------------------------------

class LogoEditDialog(QDialog):
    def __init__(self, parent=None, logo_data=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка логотипа")
        self.setMinimumWidth(460)
        self.logo_data = logo_data or {
            "path": "", "type": "image", "position": "top_right",
            "size": 15, "opacity": 80, "angle": 0,
            "color": "Green (0x00FF00)", "display": "full",
            "time_start": 0, "time_end": 10,
        }
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.cb_type = QComboBox()
        self.cb_type.addItem("Картинка (PNG/JPG)", "image")
        self.cb_type.addItem("Видео с однотонным фоном (хромакей)", "video_chromakey")
        self.cb_type.setToolTip(
            "Картинка — обычный логотип, лучше PNG с прозрачным фоном.\n"
            "Хромакей — анимированный логотип-видео: фон указанного цвета станет прозрачным."
        )
        self.cb_type.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Тип:", self.cb_type)

        self.path_field = PathField("Файл не выбран", dialog_title="Выберите логотип")
        form.addRow("Файл:", self.path_field)

        self.cb_color = QComboBox()
        self.cb_color.addItem("Зелёный", "Green (0x00FF00)")
        self.cb_color.addItem("Синий", "Blue (0x0000FF)")
        self.cb_color.addItem("Чёрный", "Black (0x000000)")
        self.cb_color.setToolTip("Этот цвет фона будет вырезан из видео-логотипа")
        self.lbl_color = QLabel("Цвет фона:")
        form.addRow(self.lbl_color, self.cb_color)

        self.cb_pos = QComboBox()
        for key, name in POSITIONS:
            self.cb_pos.addItem(name, key)
        form.addRow("Где разместить:", self.cb_pos)

        self.spin_size = QSpinBox()
        self.spin_size.setRange(5, 50)
        self.spin_size.setSuffix(" % ширины кадра")
        form.addRow("Размер:", self.spin_size)

        self.spin_op = QSpinBox()
        self.spin_op.setRange(0, 100)
        self.spin_op.setSuffix(" %")
        self.spin_op.setToolTip("100% — логотип полностью виден, 0% — невидим")
        form.addRow("Видимость:", self.spin_op)

        self.spin_angle = QSpinBox()
        self.spin_angle.setRange(-360, 360)
        self.spin_angle.setSuffix("°")
        form.addRow("Поворот:", self.spin_angle)

        self.cb_time = QComboBox()
        for key, name in LOGO_DISPLAY:
            self.cb_time.addItem(name, key)
        self.cb_time.currentIndexChanged.connect(self._on_time_changed)
        form.addRow("Когда показывать:", self.cb_time)

        # first_n / last_n → one value
        self.spin_n = QSpinBox()
        self.spin_n.setRange(1, 36000)
        self.spin_n.setSuffix(" сек")
        self.lbl_n = QLabel("N:")
        form.addRow(self.lbl_n, self.spin_n)

        # custom → from/to
        self.w_times = QWidget()
        lt = QHBoxLayout(self.w_times)
        lt.setContentsMargins(0, 0, 0, 0)
        self.spin_tstart = QSpinBox()
        self.spin_tstart.setRange(0, 36000)
        self.spin_tstart.setSuffix(" сек")
        self.spin_tend = QSpinBox()
        self.spin_tend.setRange(0, 36000)
        self.spin_tend.setSuffix(" сек")
        lt.addWidget(QLabel("с"))
        lt.addWidget(self.spin_tstart)
        lt.addWidget(QLabel("по"))
        lt.addWidget(self.spin_tend)
        lt.addStretch()
        self.lbl_times = QLabel("Интервал:")
        form.addRow(self.lbl_times, self.w_times)

        layout.addLayout(form)
        layout.addWidget(hint_label("Время отсчитывается от начала каждой готовой части (включая интро)."))

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_time_changed(self):
        display = self.cb_time.currentData()
        single = display in ("first_n", "last_n")
        self.lbl_n.setVisible(single)
        self.spin_n.setVisible(single)
        self.lbl_n.setText("Первые:" if display == "first_n" else "Последние:")
        custom = display == "custom"
        self.lbl_times.setVisible(custom)
        self.w_times.setVisible(custom)
        self.adjustSize()

    def _on_type_changed(self):
        is_video = self.cb_type.currentData() == "video_chromakey"
        self.lbl_color.setVisible(is_video)
        self.cb_color.setVisible(is_video)
        self.path_field.set_filter(LOGO_VIDEO_FILTER if is_video else IMAGE_FILTER)

    def _load_data(self):
        d = self.logo_data
        combo_select_data(self.cb_type, d.get("type", "image"))
        self.path_field.set_path(d.get("path", ""))
        combo_select_data(self.cb_pos, d.get("position", "top_right"), 1)
        self.spin_size.setValue(d.get("size", 15))
        self.spin_op.setValue(d.get("opacity", 80))
        self.spin_angle.setValue(d.get("angle", 0))
        combo_select_data(self.cb_color, d.get("color", "Green (0x00FF00)"))
        display = d.get("display", "full")
        combo_select_data(self.cb_time, display)
        self.spin_tstart.setValue(d.get("time_start", 0))
        self.spin_tend.setValue(d.get("time_end", 10))
        # first_n uses time_end, last_n uses time_start
        if display == "first_n":
            self.spin_n.setValue(max(1, d.get("time_end", 10)))
        elif display == "last_n":
            self.spin_n.setValue(max(1, d.get("time_start", 10)))
        else:
            self.spin_n.setValue(10)
        self._on_time_changed()
        self._on_type_changed()

    def _on_accept(self):
        if not self.path_field.path():
            QMessageBox.warning(self, "Логотип", "Выберите файл логотипа.")
            return
        if self.cb_time.currentData() == "custom" and self.spin_tend.value() <= self.spin_tstart.value():
            QMessageBox.warning(self, "Логотип", "Время «по» должно быть больше времени «с».")
            return
        self.accept()

    def get_data(self):
        display = self.cb_time.currentData()
        t_start, t_end = self.spin_tstart.value(), self.spin_tend.value()
        if display == "first_n":
            t_start, t_end = 0, self.spin_n.value()
        elif display == "last_n":
            t_start, t_end = self.spin_n.value(), 0
        return {
            "path": self.path_field.path(),
            "type": self.cb_type.currentData(),
            "position": self.cb_pos.currentData(),
            "size": self.spin_size.value(),
            "opacity": self.spin_op.value(),
            "angle": self.spin_angle.value(),
            "color": self.cb_color.currentData(),
            "display": display,
            "time_start": t_start,
            "time_end": t_end,
        }


class SoundOverlayDialog(QDialog):
    """Диалог настройки одного звукового оверлея."""

    def __init__(self, parent=None, data=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка звука")
        self.setMinimumWidth(420)
        self._data = data or {"path": "", "start_sec": 0, "volume": 0.8, "loop": False}
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.path_field = PathField("Файл не выбран", file_filter=AUDIO_FILTER,
                                    dialog_title="Выберите аудиофайл")
        form.addRow("Файл:", self.path_field)

        self.spin_start = QSpinBox()
        self.spin_start.setRange(0, 7200)
        self.spin_start.setSuffix(" сек")
        self.spin_start.setToolTip("Через сколько секунд от начала части начнёт играть звук")
        form.addRow("Начать через:", self.spin_start)

        self.spin_vol = QSpinBox()
        self.spin_vol.setRange(0, 200)
        self.spin_vol.setSuffix(" %")
        self.spin_vol.setToolTip("100% — исходная громкость файла. Звук стрима не приглушается.")
        form.addRow("Громкость:", self.spin_vol)

        self.chk_loop = QCheckBox("Повторять по кругу до конца части")
        form.addRow("", self.chk_loop)

        layout.addLayout(form)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _load_data(self):
        self.path_field.set_path(self._data.get("path", ""))
        self.spin_start.setValue(int(self._data.get("start_sec", 0)))
        self.spin_vol.setValue(int(round(self._data.get("volume", 0.8) * 100)))
        self.chk_loop.setChecked(bool(self._data.get("loop", False)))

    def _on_accept(self):
        if not self.path_field.path():
            QMessageBox.warning(self, "Звук", "Выберите аудиофайл.")
            return
        self.accept()

    def get_data(self) -> dict:
        return {
            "path": self.path_field.path(),
            "start_sec": self.spin_start.value(),
            "volume": round(self.spin_vol.value() / 100.0, 2),
            "loop": self.chk_loop.isChecked(),
        }


# ----------------------------------------------------------------------
# Main window
# ----------------------------------------------------------------------

class MainWindow(QMainWindow):
    encoders_detected = Signal(dict)

    COL_NAME, COL_DUR, COL_STATUS, COL_PROGRESS = range(4)

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self._ui_loading = False          # suppress saves while filling widgets
        self._stop_requested = False
        self._running = False
        self._queue_start_time = 0.0
        self._available_encoders: dict = {}
        self._vk_uploader: VkUploader | None = None
        self._log_path: Path | None = None
        self._logos_data: list = []
        self._sounds_data: list = []

        self.setWindowTitle("Stream Auto Cutter")
        self.resize(1150, 760)
        self.setMinimumSize(900, 620)
        self.setAcceptDrops(True)
        self._set_icon()
        self.apply_theme()

        # Core manager
        self.queue_manager = QueueManager(self)
        self.queue_manager.task_updated.connect(self._on_task_updated)
        self.queue_manager.task_progress.connect(self._on_task_progress)
        self.queue_manager.task_completed.connect(self._on_task_completed)
        self.queue_manager.queue_completed.connect(self._on_queue_completed)
        self.queue_manager.log_message.connect(self._log_message)

        self._build_ui()

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        self._apply_values_to_ui(self.settings.get_all())
        self._connect_ui_to_settings()
        self._update_preset_dirty()

        self.encoders_detected.connect(self._on_encoders_detected)
        self._detect_gpu_encoders()

    def _set_icon(self):
        meipass = getattr(sys, "_MEIPASS", None)
        base = Path(meipass) if meipass else Path(__file__).parent
        for icon_name in ("icon.png", "icon.ico"):
            icon_p = base / icon_name
            if icon_p.is_file():
                self.setWindowIcon(QIcon(str(icon_p)))
                break

    # ------------------------------------------------------------------
    # UI Creation
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(8)

        v_split = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(v_split, stretch=1)

        h_split = QSplitter(Qt.Orientation.Horizontal)
        h_split.addWidget(self._build_queue_panel())

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addLayout(self._build_presets_bar())

        self.tabs = QTabWidget()
        self.tab_main = self._create_main_tab()
        self.tab_video = self._create_video_tab()
        self.tab_io = self._create_io_tab()
        self.tab_logo = self._create_logo_tab()
        self.tab_sound = self._create_sound_tab()
        self.tab_vk = self._create_vk_tab()
        for page, title in ((self.tab_main, "Нарезка"), (self.tab_video, "Видео"),
                            (self.tab_io, "Интро / Аутро"), (self.tab_logo, "Логотип"),
                            (self.tab_sound, "Звук"), (self.tab_vk, "ВКонтакте")):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.tabs.addTab(scroll, title)
        self._processing_tabs = [self.tab_main, self.tab_video, self.tab_io,
                                 self.tab_logo, self.tab_sound]
        rl.addWidget(self.tabs, stretch=1)
        h_split.addWidget(right)
        h_split.setSizes([520, 560])
        v_split.addWidget(h_split)

        # Log
        log_group = QGroupBox("Журнал")
        ll = QVBoxLayout(log_group)
        ll.setContentsMargins(6, 6, 6, 6)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(50)
        ll.addWidget(self.log_text)
        v_split.addWidget(log_group)
        v_split.setStretchFactor(0, 1)
        v_split.setStretchFactor(1, 0)
        self._v_split = v_split
        self._initial_layout_done = False

        # Controls
        controls = QHBoxLayout()
        self.btn_start = QPushButton("▶ Старт")
        self.btn_start.setObjectName("primary")
        self.btn_start.setToolTip("Начать нарезку всех файлов из очереди")
        self.btn_start.clicked.connect(self.action_start)
        self.btn_pause = QPushButton("⏸ Пауза")
        self.btn_pause.setToolTip("Текущая часть доделается, следующая не начнётся, пока не нажмёте «Продолжить»")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.action_pause)
        self.btn_stop = QPushButton("⏹ Стоп")
        self.btn_stop.setToolTip("Прервать обработку. Уже готовые части останутся.")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.action_stop)
        for b in (self.btn_start, self.btn_pause, self.btn_stop):
            b.setMinimumHeight(40)

        self.progress_overall = QProgressBar()
        self.progress_overall.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_overall.setFormat("Общий прогресс: %p%")
        self.progress_overall.setMinimumHeight(28)
        self.progress_overall.setValue(0)

        self.btn_open_output = QPushButton("📂 Папка с результатом")
        self.btn_open_output.setMinimumHeight(40)
        self.btn_open_output.setToolTip("Открыть папку, куда сохраняются готовые части")
        self.btn_open_output.clicked.connect(self._open_output_folder)

        controls.addWidget(self.btn_start)
        controls.addWidget(self.btn_pause)
        controls.addWidget(self.btn_stop)
        controls.addWidget(self.progress_overall, stretch=1)
        controls.addWidget(self.btn_open_output)
        main_layout.addLayout(controls)

        self.lbl_eta = QLabel("")
        self.lbl_eta.setStyleSheet("color: #a0a0a0; font-size: 12px; padding: 2px 4px;")
        main_layout.addWidget(self.lbl_eta)

    def _build_queue_panel(self) -> QWidget:
        files_group = QGroupBox("Очередь файлов")
        fl = QVBoxLayout(files_group)

        btns = QHBoxLayout()
        self.btn_add_file = QPushButton("➕ Добавить файлы…")
        self.btn_add_file.clicked.connect(self.action_add_files)
        self.btn_add_folder = QPushButton("📁 Добавить папку…")
        self.btn_add_folder.clicked.connect(self.action_add_folder)
        self.btn_remove = QPushButton("Убрать выбранные")
        self.btn_remove.setToolTip("Убрать из очереди (сами файлы не удаляются). Клавиша Delete.")
        self.btn_remove.clicked.connect(self.action_remove_files)
        self.btn_remove.setEnabled(False)
        self.btn_clear = QPushButton("Очистить")
        self.btn_clear.setToolTip("Убрать все файлы из очереди (сами файлы не удаляются)")
        self.btn_clear.clicked.connect(self.action_clear_files)
        for b in (self.btn_add_file, self.btn_add_folder, self.btn_remove, self.btn_clear):
            btns.addWidget(b)
        fl.addLayout(btns)

        self.table = QueueTable(0, 4)
        self.table.setHorizontalHeaderLabels(["Файл", "Длительность", "Статус", "Прогресс"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(self.COL_DUR, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(self.COL_PROGRESS, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_PROGRESS, 150)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._update_queue_buttons)
        fl.addWidget(self.table)

        QShortcut(QKeySequence.StandardKey.Delete, self.table, activated=self.action_remove_files)

        self.lbl_queue_summary = QLabel("")
        self.lbl_queue_summary.setStyleSheet(HINT)
        fl.addWidget(self.lbl_queue_summary)
        return files_group

    def _create_main_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        group = QGroupBox("Длина частей")
        gl = QVBoxLayout(group)
        h = QHBoxLayout()
        h.addWidget(QLabel("Резать на части по:"))
        self.cb_duration = QComboBox()
        for m in DURATION_PRESETS:
            self.cb_duration.addItem(f"{m} минут", m)
        self.cb_duration.addItem("Своё значение…", None)
        self.cb_duration.currentIndexChanged.connect(self._on_duration_type_changed)
        h.addWidget(self.cb_duration)
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(1, 600)
        self.spin_duration.setSuffix(" мин")
        self.spin_duration.setVisible(False)
        h.addWidget(self.spin_duration)
        h.addStretch()
        gl.addLayout(h)
        gl.addWidget(hint_label(
            "Каждое видео из очереди будет разрезано на части такой длины. "
            "Например, стрим на 2 часа при 16 минутах даст 8 частей."))
        layout.addWidget(group)

        out_group = QGroupBox("Куда сохранять")
        ol = QVBoxLayout(out_group)
        self.rb_out_near = QRadioButton("Рядом с исходным видео, в подпапку «output»")
        self.rb_out_custom = QRadioButton("В свою папку:")
        self.out_path = PathField("Папка не выбрана", mode="dir", dialog_title="Куда сохранять готовые части")
        ol.addWidget(self.rb_out_near)
        h_out = QHBoxLayout()
        h_out.addWidget(self.rb_out_custom)
        h_out.addWidget(self.out_path, stretch=1)
        ol.addLayout(h_out)
        ol.addWidget(hint_label("Имена готовых файлов: <имя видео>_part01.mp4, _part02.mp4 …"))
        self.rb_out_near.toggled.connect(self._on_output_mode_changed)
        self.out_path.pathChanged.connect(self._on_output_path_picked)
        layout.addWidget(out_group)

        layout.addStretch()
        return widget

    def _create_io_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(hint_label(
            "Интро и аутро добавляются к КАЖДОЙ части: в начало и в конец соответственно."))

        grp_intro = QGroupBox("Интро (в начале)")
        li = QVBoxLayout(grp_intro)
        self.chk_intro = QCheckBox("Добавлять интро")
        self.intro_path = PathField("Видео не выбрано", file_filter=VIDEO_FILTER, dialog_title="Выберите интро")
        li.addWidget(self.chk_intro)
        li.addWidget(self.intro_path)
        layout.addWidget(grp_intro)

        grp_outro = QGroupBox("Аутро (в конце)")
        lo = QVBoxLayout(grp_outro)
        self.chk_outro = QCheckBox("Добавлять аутро")
        self.outro_path = PathField("Видео не выбрано", file_filter=VIDEO_FILTER, dialog_title="Выберите аутро")
        lo.addWidget(self.chk_outro)
        lo.addWidget(self.outro_path)
        layout.addWidget(grp_outro)

        self.chk_intro.toggled.connect(self.intro_path.setEnabled)
        self.chk_outro.toggled.connect(self.outro_path.setEnabled)
        # selecting a file implies the user wants it on
        self.intro_path.pathChanged.connect(lambda p: p and self.chk_intro.setChecked(True))
        self.outro_path.pathChanged.connect(lambda p: p and self.chk_outro.setChecked(True))

        layout.addStretch()
        return widget

    def _create_list_editor(self, add_text, on_add, on_edit, on_remove):
        """List + Add/Edit/Remove buttons. Returns (container, list, edit_btn, remove_btn)."""
        box = QWidget()
        bl = QVBoxLayout(box)
        bl.setContentsMargins(0, 0, 0, 0)
        lst = QListWidget()
        lst.itemDoubleClicked.connect(lambda _: on_edit())
        bl.addWidget(lst)
        h = QHBoxLayout()
        b_add = QPushButton(add_text)
        b_add.clicked.connect(on_add)
        b_edit = QPushButton("Изменить")
        b_edit.clicked.connect(on_edit)
        b_del = QPushButton("Удалить")
        b_del.clicked.connect(on_remove)
        for b in (b_add, b_edit, b_del):
            h.addWidget(b)
        bl.addLayout(h)

        def _sel():
            has = lst.currentRow() >= 0
            b_edit.setEnabled(has)
            b_del.setEnabled(has)
        lst.currentRowChanged.connect(lambda _: _sel())
        _sel()
        return box, lst

    def _create_logo_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.chk_logo = QCheckBox("Накладывать логотипы")
        layout.addWidget(self.chk_logo)
        self.logo_box, self.list_logos = self._create_list_editor(
            "➕ Добавить логотип", self._action_add_logo, self._action_edit_logo, self._action_remove_logo)
        layout.addWidget(self.logo_box)
        layout.addWidget(hint_label("Можно добавить несколько логотипов. Двойной щелчок — изменить."))
        self.chk_logo.toggled.connect(self.logo_box.setEnabled)
        return widget

    def _create_sound_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.chk_sound = QCheckBox("Накладывать звук поверх звука стрима")
        layout.addWidget(self.chk_sound)
        self.sound_box, self.list_sounds = self._create_list_editor(
            "➕ Добавить звук", self._action_add_sound, self._action_edit_sound, self._action_remove_sound)
        layout.addWidget(self.sound_box)
        layout.addWidget(hint_label(
            "Например, фоновая музыка или звуковой сигнал. Оригинальный звук стрима остаётся."))
        self.chk_sound.toggled.connect(self.sound_box.setEnabled)
        return widget

    def _create_video_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        grp = QGroupBox("Качество и скорость")
        form = QFormLayout(grp)

        h_res = QHBoxLayout()
        self.cb_res = QComboBox()
        self.cb_res.addItem("Как в исходнике", "source")
        self.cb_res.addItem("720p (1280×720)", "1280x720")
        self.cb_res.addItem("1080p (1920×1080)", "1920x1080")
        self.cb_res.addItem("1440p (2560×1440)", "2560x1440")
        self.cb_res.addItem("4K (3840×2160)", "3840x2160")
        self.cb_res.addItem("Своё…", "custom")
        self.cb_res.currentIndexChanged.connect(self._on_res_changed)
        self.spin_res_w = QSpinBox()
        self.spin_res_w.setRange(320, 7680)
        self.spin_res_h = QSpinBox()
        self.spin_res_h.setRange(240, 4320)
        self.lbl_res_x = QLabel("×")
        h_res.addWidget(self.cb_res)
        h_res.addWidget(self.spin_res_w)
        h_res.addWidget(self.lbl_res_x)
        h_res.addWidget(self.spin_res_h)
        h_res.addStretch()
        form.addRow("Разрешение:", h_res)

        self.cb_fps = QComboBox()
        self.cb_fps.addItem("Как в исходнике", "source")
        for f in ("24", "30", "60"):
            self.cb_fps.addItem(f"{f} кадров/сек", f)
        form.addRow("Частота кадров:", self.cb_fps)

        self.cb_codec = QComboBox()
        self.cb_codec.addItem("NVIDIA — H.264", "h264_nvenc")
        self.cb_codec.addItem("NVIDIA — H.265 (HEVC)", "hevc_nvenc")
        self.cb_codec.addItem("Intel — H.264", "h264_qsv")
        self.cb_codec.addItem("Intel — H.265 (HEVC)", "hevc_qsv")
        self.cb_codec.addItem("AMD — H.264", "h264_amf")
        self.cb_codec.addItem("AMD — H.265 (HEVC)", "hevc_amf")
        self.cb_codec.addItem("Mac — H.264", "h264_videotoolbox")
        self.cb_codec.addItem("Mac — H.265 (HEVC)", "hevc_videotoolbox")
        self.cb_codec.addItem("Процессор — H.264 (медленно, работает везде)", "libx264")
        self.cb_codec.addItem("Процессор — H.265 (очень медленно)", "libx265")
        self.cb_codec.setToolTip(
            "Через что кодировать видео.\n"
            "Видеокарта (NVIDIA/Intel/AMD/Mac) — в разы быстрее.\n"
            "H.264 — совместим со всеми сайтами. H.265 — файлы меньше, но кодируется дольше."
        )
        self.lbl_codec_status = QLabel("Проверяю, какие кодеки работают на этом компьютере…")
        self.lbl_codec_status.setStyleSheet(HINT)
        self.lbl_codec_status.setWordWrap(True)
        codec_box = QVBoxLayout()
        codec_box.addWidget(self.cb_codec)
        codec_box.addWidget(self.lbl_codec_status)
        form.addRow("Кодек:", codec_box)

        self.cb_workers = QComboBox()
        self.cb_workers.addItem("1 — по одной части", 1)
        self.cb_workers.addItem("2 — рекомендуется", 2)
        self.cb_workers.addItem("3 — для мощных видеокарт", 3)
        self.cb_workers.addItem("4 — максимум", 4)
        self.cb_workers.setToolTip(
            "Сколько частей кодировать одновременно.\n"
            "Больше — быстрее, но сильнее нагрузка. Если появляются ошибки — уменьшите."
        )
        form.addRow("Одновременно:", self.cb_workers)
        layout.addWidget(grp)

        grp_shorts = QGroupBox("Вертикальное видео (Shorts / Reels / TikTok)")
        sl = QVBoxLayout(grp_shorts)
        self.chk_shorts = QCheckBox("Сделать вертикальным 9:16")
        sl.addWidget(self.chk_shorts)
        self.shorts_box = QWidget()
        sf = QFormLayout(self.shorts_box)
        sf.setContentsMargins(0, 0, 0, 0)
        self.cb_shorts_res = QComboBox()
        self.cb_shorts_res.addItem("1080×1920 (рекомендуется)", "1080x1920")
        self.cb_shorts_res.addItem("720×1280", "720x1280")
        sf.addRow("Размер:", self.cb_shorts_res)
        self.cb_shorts_fit = QComboBox()
        self.cb_shorts_fit.addItem("Видео целиком + размытый фон", "blur_sides")
        self.cb_shorts_fit.addItem("Обрезать края, оставить центр", "crop_center")
        self.cb_shorts_fit.addItem("Видео целиком + чёрные полосы", "black_bars")
        self.cb_shorts_fit.setToolTip(
            "Размытый фон — видно всё, сверху и снизу размытая копия кадра.\n"
            "Обрезка — кадр на весь экран, но края слева и справа теряются.\n"
            "Чёрные полосы — видно всё, сверху и снизу чёрное."
        )
        sf.addRow("Как вписать:", self.cb_shorts_fit)
        sl.addWidget(self.shorts_box)
        sl.addWidget(hint_label("При включении размер кадра берётся отсюда, а «Разрешение» выше не учитывается."))
        self.chk_shorts.toggled.connect(self.shorts_box.setEnabled)
        layout.addWidget(grp_shorts)

        layout.addStretch()
        return widget

    def _create_vk_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        auth_group = QGroupBox("Аккаунт")
        af = QFormLayout(auth_group)

        h_token = QHBoxLayout()
        self.vk_token_edit = QLineEdit()
        self.vk_token_edit.setPlaceholderText("vk1.a.xxxxxxxxxxxx…")
        self.vk_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        btn_show = QPushButton("👁")
        btn_show.setFixedWidth(36)
        btn_show.setCheckable(True)
        btn_show.setToolTip("Показать / скрыть токен")
        btn_show.toggled.connect(lambda on: self.vk_token_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        btn_help = QPushButton("?")
        btn_help.setFixedWidth(36)
        btn_help.setToolTip("Что такое токен")
        btn_help.clicked.connect(self._vk_show_help)
        h_token.addWidget(self.vk_token_edit, stretch=1)
        h_token.addWidget(btn_show)
        h_token.addWidget(btn_help)
        af.addRow("Токен:", h_token)

        self.vk_group_edit = QLineEdit()
        self.vk_group_edit.setPlaceholderText("пусто — на свою страницу; или 123456789 / club123456789")
        self.vk_group_edit.setToolTip("Число из адреса группы: vk.com/club123456789 → 123456789")
        af.addRow("Группа:", self.vk_group_edit)
        layout.addWidget(auth_group)

        src_group = QGroupBox("Что загружать")
        sv = QVBoxLayout(src_group)
        sf = QFormLayout()
        self.vk_folder = PathField("Папка не выбрана", mode="dir", dialog_title="Папка с готовыми видео")
        sf.addRow("Папка с видео:", self.vk_folder)
        self.vk_titles = PathField("Файл не выбран", file_filter="Текстовые файлы (*.txt)",
                                   dialog_title="Файл с названиями")
        sf.addRow("Названия (.txt):", self.vk_titles)
        sv.addLayout(sf)
        self.vk_summary = QLabel("")
        self.vk_summary.setWordWrap(True)
        self.vk_summary.setVisible(False)
        sv.addWidget(self.vk_summary)
        sv.addWidget(hint_label(
            "В файле с названиями — одно название на строку, по порядку видео. "
            "Загруженные видео переносятся в подпапку «uploaded», а их названия удаляются из файла."))
        self.vk_folder.pathChanged.connect(self._vk_update_summary)
        self.vk_titles.pathChanged.connect(self._vk_update_summary)
        layout.addWidget(src_group)

        params_group = QGroupBox("Параметры")
        pl = QHBoxLayout(params_group)
        pl.addWidget(QLabel("Пауза между видео:"))
        self.vk_delay_spin = QSpinBox()
        self.vk_delay_spin.setRange(1, 300)
        self.vk_delay_spin.setSuffix(" сек")
        self.vk_delay_spin.setToolTip("Чтобы ВК не посчитал загрузку спамом")
        pl.addWidget(self.vk_delay_spin)
        pl.addSpacing(20)
        pl.addWidget(QLabel("Не больше:"))
        self.vk_max_spin = QSpinBox()
        self.vk_max_spin.setRange(1, 1000)
        self.vk_max_spin.setSuffix(" видео за раз")
        self.vk_max_spin.valueChanged.connect(lambda _: self._vk_update_summary())
        pl.addWidget(self.vk_max_spin)
        pl.addStretch()
        layout.addWidget(params_group)

        ctrl = QHBoxLayout()
        self.vk_btn_start = QPushButton("▶ Загрузить в ВК")
        self.vk_btn_start.setObjectName("primary")
        self.vk_btn_start.setMinimumHeight(36)
        self.vk_btn_start.clicked.connect(self.action_vk_start)
        self.vk_btn_stop = QPushButton("⏹ Остановить")
        self.vk_btn_stop.setMinimumHeight(36)
        self.vk_btn_stop.setEnabled(False)
        self.vk_btn_stop.clicked.connect(self.action_vk_stop)
        ctrl.addWidget(self.vk_btn_start)
        ctrl.addWidget(self.vk_btn_stop)
        layout.addLayout(ctrl)

        self.vk_progress = QProgressBar()
        self.vk_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vk_progress.setFormat("Ожидание")
        self.vk_progress.setValue(0)
        layout.addWidget(self.vk_progress)

        self.vk_log = QTextEdit()
        self.vk_log.setReadOnly(True)
        self.vk_log.setMinimumHeight(100)
        layout.addWidget(self.vk_log, stretch=1)
        return widget

    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget, QDialog {
                background-color: #2b2b2b;
                color: #e0e0e0;
            }
            QWidget:disabled { color: #6a6a6a; }
            QGroupBox {
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 1.2ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 4px;
                color: #b0b0b0;
            }
            QPushButton {
                background-color: #3c3f41;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 5px 12px;
            }
            QPushButton:hover { background-color: #4c5052; }
            QPushButton:pressed { background-color: #2b2b2b; }
            QPushButton:checked { background-color: #4c5052; }
            QPushButton:disabled { color: #6a6a6a; border-color: #444; }
            QPushButton#primary {
                background-color: #0e639c;
                border-color: #1177bb;
                font-weight: bold;
            }
            QPushButton#primary:hover { background-color: #1177bb; }
            QPushButton#primary:disabled { background-color: #3a3d3f; border-color: #444; }
            QTableWidget, QListWidget {
                background-color: #1e1e1e;
                alternate-background-color: #252525;
                gridline-color: #333;
                border: 1px solid #555;
            }
            QHeaderView::section {
                background-color: #3c3f41;
                padding: 4px;
                border: 1px solid #555;
            }
            QTabWidget::pane { border: 1px solid #555; }
            QTabBar::tab {
                background: #3c3f41;
                border: 1px solid #555;
                padding: 6px 14px;
            }
            QTabBar::tab:selected { background: #4c5052; }
            QTextEdit {
                background-color: #1e1e1e;
                border: 1px solid #555;
                font-family: monospace;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: #1e1e1e;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 3px 5px;
            }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk { background-color: #007acc; }
            QToolTip {
                background-color: #3c3f41;
                color: #e0e0e0;
                border: 1px solid #555;
            }
        """)

    # ------------------------------------------------------------------
    # Data sync
    # ------------------------------------------------------------------

    def _apply_values_to_ui(self, data: dict):
        """Fill all processing + VK widgets from a settings/preset dict."""
        self._ui_loading = True
        try:
            # Cut
            dur = data.get("segment_duration_min", 16)
            if dur in DURATION_PRESETS:
                self.cb_duration.setCurrentIndex(DURATION_PRESETS.index(dur))
            else:
                self.cb_duration.setCurrentIndex(len(DURATION_PRESETS))
            self.spin_duration.setValue(dur)
            self._on_duration_type_changed(self.cb_duration.currentIndex())

            # Output
            sub = data.get("output_subfolder", "output") or "output"
            if Path(sub).is_absolute():
                self.rb_out_custom.setChecked(True)
                self.out_path.set_path(sub)
            else:
                self.rb_out_near.setChecked(True)
                self.out_path.set_path("")
            self._on_output_mode_changed()

            # Intro / outro
            self.chk_intro.setChecked(data.get("intro_enabled", False))
            self.chk_outro.setChecked(data.get("outro_enabled", False))
            self.intro_path.set_path(data.get("intro_path", ""))
            self.outro_path.set_path(data.get("outro_path", ""))
            self.intro_path.setEnabled(self.chk_intro.isChecked())
            self.outro_path.setEnabled(self.chk_outro.isChecked())

            # Logo
            self.chk_logo.setChecked(data.get("logo_enabled", False))
            self.logo_box.setEnabled(self.chk_logo.isChecked())
            self._logos_data = [dict(d) for d in data.get("logos", [])]
            self._refresh_logos_list()

            # Video
            combo_select_data(self.cb_res, data.get("resolution", "source"))
            self.spin_res_w.setValue(data.get("custom_resolution_w", 1920))
            self.spin_res_h.setValue(data.get("custom_resolution_h", 1080))
            self._on_res_changed()
            combo_select_data(self.cb_fps, str(data.get("fps", "source")))
            combo_select_data(self.cb_codec, data.get("codec", "libx264"),
                              self.cb_codec.findData("libx264"))
            combo_select_data(self.cb_workers, data.get("parallel_workers", 2), 1)

            # Shorts
            self.chk_shorts.setChecked(data.get("shorts_enabled", False))
            self.shorts_box.setEnabled(self.chk_shorts.isChecked())
            combo_select_data(self.cb_shorts_res, data.get("shorts_resolution", "1080x1920"))
            combo_select_data(self.cb_shorts_fit, data.get("shorts_fit", "blur_sides"))

            # Sound
            self.chk_sound.setChecked(data.get("sound_overlay_enabled", False))
            self.sound_box.setEnabled(self.chk_sound.isChecked())
            self._sounds_data = [dict(d) for d in data.get("sound_overlays", [])]
            self._refresh_sounds_list()

            # VK (not part of presets — only present in full settings)
            if "vk_token" in data:
                self.vk_token_edit.setText(data.get("vk_token", ""))
                self.vk_group_edit.setText(data.get("vk_group_id", ""))
                self.vk_folder.set_path(data.get("vk_video_folder", ""))
                self.vk_titles.set_path(data.get("vk_titles_file", ""))
                self.vk_delay_spin.setValue(data.get("vk_delay_sec", 10))
                self.vk_max_spin.setValue(data.get("vk_max_videos", 150))
                self._vk_update_summary()
        finally:
            self._ui_loading = False

    def _collect_ui_values(self) -> dict:
        dur = self.cb_duration.currentData()
        if self.rb_out_custom.isChecked() and self.out_path.path():
            output_sub = self.out_path.path()
        else:
            output_sub = "output"
        return {
            "segment_duration_min": dur if dur is not None else self.spin_duration.value(),
            "output_subfolder": output_sub,
            "intro_enabled": self.chk_intro.isChecked(),
            "outro_enabled": self.chk_outro.isChecked(),
            "intro_path": self.intro_path.path(),
            "outro_path": self.outro_path.path(),
            "logo_enabled": self.chk_logo.isChecked(),
            "logos": [dict(d) for d in self._logos_data],
            "resolution": self.cb_res.currentData(),
            "custom_resolution_w": self.spin_res_w.value(),
            "custom_resolution_h": self.spin_res_h.value(),
            "fps": self.cb_fps.currentData(),
            "codec": self.cb_codec.currentData(),
            "parallel_workers": self.cb_workers.currentData() or 2,
            "shorts_enabled": self.chk_shorts.isChecked(),
            "shorts_resolution": self.cb_shorts_res.currentData(),
            "shorts_fit": self.cb_shorts_fit.currentData(),
            "sound_overlay_enabled": self.chk_sound.isChecked(),
            "sound_overlays": [dict(d) for d in self._sounds_data],
            "vk_token": self.vk_token_edit.text().strip(),
            "vk_group_id": self.vk_group_edit.text().strip(),
            "vk_video_folder": self.vk_folder.path(),
            "vk_titles_file": self.vk_titles.path(),
            "vk_delay_sec": self.vk_delay_spin.value(),
            "vk_max_videos": self.vk_max_spin.value(),
        }

    def _save_ui_to_settings(self, *_):
        if self._ui_loading:
            return
        self.settings.update(self._collect_ui_values())
        self._update_preset_dirty()

    def _connect_ui_to_settings(self):
        save = self._save_ui_to_settings
        for combo in (self.cb_duration, self.cb_res, self.cb_fps, self.cb_codec, self.cb_workers,
                      self.cb_shorts_res, self.cb_shorts_fit):
            combo.currentIndexChanged.connect(save)
        for spin in (self.spin_duration, self.spin_res_w, self.spin_res_h,
                     self.vk_delay_spin, self.vk_max_spin):
            spin.valueChanged.connect(save)
        for chk in (self.chk_intro, self.chk_outro, self.chk_logo, self.chk_shorts,
                    self.chk_sound, self.rb_out_near):
            chk.toggled.connect(save)
        for pf in (self.intro_path, self.outro_path, self.out_path, self.vk_folder, self.vk_titles):
            pf.pathChanged.connect(save)
        self.vk_token_edit.textChanged.connect(save)
        self.vk_group_edit.textChanged.connect(save)

    # ------------------------------------------------------------------
    # Small UI reactions
    # ------------------------------------------------------------------

    def _on_duration_type_changed(self, idx: int):
        self.spin_duration.setVisible(self.cb_duration.itemData(idx) is None)

    def _on_res_changed(self, *_):
        custom = self.cb_res.currentData() == "custom"
        for w in (self.spin_res_w, self.lbl_res_x, self.spin_res_h):
            w.setVisible(custom)

    def _on_output_mode_changed(self, *_):
        self.out_path.setEnabled(self.rb_out_custom.isChecked())

    def _on_output_path_picked(self, path: str):
        if path:
            self.rb_out_custom.setChecked(True)

    def _update_queue_buttons(self):
        self.btn_remove.setEnabled(not self._running and bool(self.table.selectedItems()))

    # ------------------------------------------------------------------
    # Logos & sounds
    # ------------------------------------------------------------------

    def _refresh_logos_list(self):
        self.list_logos.clear()
        for i, ld in enumerate(self._logos_data):
            p = ld.get("path", "")
            name = Path(p).name if p else "файл не выбран"
            missing = " ⚠ файл не найден" if p and not Path(p).is_file() else ""
            pos = POSITION_NAMES.get(ld.get("position", ""), ld.get("position", ""))
            when = LOGO_DISPLAY_NAMES.get(ld.get("display", "full"), "")
            self.list_logos.addItem(
                f"{i + 1}. {name} — {pos.lower()}, {ld.get('size', 15)}%, {when.lower()}{missing}")

    def _action_add_logo(self):
        dlg = LogoEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._logos_data.append(dlg.get_data())
            self.chk_logo.setChecked(True)
            self._refresh_logos_list()
            self._save_ui_to_settings()

    def _action_edit_logo(self):
        r = self.list_logos.currentRow()
        if not 0 <= r < len(self._logos_data):
            return
        dlg = LogoEditDialog(self, self._logos_data[r])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._logos_data[r] = dlg.get_data()
            self._refresh_logos_list()
            self._save_ui_to_settings()

    def _action_remove_logo(self):
        r = self.list_logos.currentRow()
        if 0 <= r < len(self._logos_data):
            del self._logos_data[r]
            self._refresh_logos_list()
            self._save_ui_to_settings()

    def _refresh_sounds_list(self):
        self.list_sounds.clear()
        for i, sd in enumerate(self._sounds_data):
            p = sd.get("path", "")
            name = Path(p).name if p else "файл не выбран"
            missing = " ⚠ файл не найден" if p and not Path(p).is_file() else ""
            vol = int(round(sd.get("volume", 0.8) * 100))
            loop_s = ", по кругу" if sd.get("loop") else ""
            self.list_sounds.addItem(
                f"{i + 1}. {name} — с {sd.get('start_sec', 0)} сек, громкость {vol}%{loop_s}{missing}")

    def _action_add_sound(self):
        dlg = SoundOverlayDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._sounds_data.append(dlg.get_data())
            self.chk_sound.setChecked(True)
            self._refresh_sounds_list()
            self._save_ui_to_settings()

    def _action_edit_sound(self):
        r = self.list_sounds.currentRow()
        if not 0 <= r < len(self._sounds_data):
            return
        dlg = SoundOverlayDialog(self, self._sounds_data[r])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._sounds_data[r] = dlg.get_data()
            self._refresh_sounds_list()
            self._save_ui_to_settings()

    def _action_remove_sound(self):
        r = self.list_sounds.currentRow()
        if 0 <= r < len(self._sounds_data):
            del self._sounds_data[r]
            self._refresh_sounds_list()
            self._save_ui_to_settings()

    # ------------------------------------------------------------------
    # GPU Detection
    # ------------------------------------------------------------------

    def _detect_gpu_encoders(self):
        def _worker():
            try:
                result = detect_available_encoders(get_ffmpeg_path())
            except Exception:
                result = {}
            self.encoders_detected.emit(result)   # queued to GUI thread

        threading.Thread(target=_worker, daemon=True).start()

    def _codec_available(self, codec: str) -> bool:
        if codec in CPU_CODECS:
            return True
        return self._available_encoders.get(codec, True)

    def _on_encoders_detected(self, encoders: dict):
        self._available_encoders = encoders or {}
        if not self._available_encoders:
            self.lbl_codec_status.setText("Не удалось проверить кодеки (ffmpeg не найден?).")
            return

        model = self.cb_codec.model()
        hw_ok = []
        for i in range(self.cb_codec.count()):
            codec = self.cb_codec.itemData(i)
            item = model.item(i)
            if self._codec_available(codec):
                item.setEnabled(True)
                if codec not in CPU_CODECS:
                    hw_ok.append(codec)
            else:
                item.setEnabled(False)
                item.setToolTip("Не поддерживается на этом компьютере")

        if hw_ok:
            names = sorted({self.cb_codec.itemText(self.cb_codec.findData(c)).split(" — ")[0] for c in hw_ok})
            self.lbl_codec_status.setText(f"✓ Ускорение видеокартой доступно: {', '.join(names)}")
        else:
            self.lbl_codec_status.setText("Ускорение видеокартой не найдено — будет использоваться процессор (медленнее).")

        current = self.cb_codec.currentData()
        if not self._codec_available(current):
            new = hw_ok[0] if hw_ok else "libx264"
            self.cb_codec.setCurrentIndex(self.cb_codec.findData(new))
            self._log_message(
                f"Кодек «{current}» недоступен на этом компьютере — автоматически выбран "
                f"«{self.cb_codec.currentText()}».")

    # ------------------------------------------------------------------
    # Elapsed / ETA
    # ------------------------------------------------------------------

    def _update_elapsed(self):
        tasks = self.queue_manager.get_tasks()
        if not tasks:
            return
        elapsed = time.time() - self._queue_start_time if self._queue_start_time else 0

        total_chunks = sum(t.num_segments for t in tasks)
        done_chunks = 0
        for t in tasks:
            if t.status == TaskStatus.DONE:
                done_chunks += t.num_segments
            elif t.status == TaskStatus.PROCESSING:
                done_chunks += t.current_segment

        current_speed = next((t.speed for t in tasks
                              if t.status == TaskStatus.PROCESSING and t.speed > 0), 0.0)

        total_eta = 0.0
        for t in tasks:
            if t.status == TaskStatus.PROCESSING:
                total_eta += t.eta_sec
            elif t.status == TaskStatus.PENDING and current_speed > 0:
                total_eta += t.duration / current_speed

        parts = []
        if self.queue_manager.is_paused:
            parts.append("⏸ НА ПАУЗЕ")
        if total_chunks:
            parts.append(f"Частей готово: {done_chunks} из {total_chunks}")
        parts.append(f"Прошло: {fmt_duration(elapsed)}")
        if total_eta > 0:
            parts.append(f"Осталось примерно: {fmt_duration(total_eta)}")
        if current_speed > 0:
            parts.append(f"Скорость: {current_speed:.1f}× от реального времени")
        self.lbl_eta.setText("   •   ".join(parts))

    # ------------------------------------------------------------------
    # VK Uploader
    # ------------------------------------------------------------------

    def _vk_collect_files(self) -> list[str]:
        folder = self.vk_folder.path()
        if not folder or not os.path.isdir(folder):
            return []
        return sorted(
            (os.path.join(folder, f) for f in os.listdir(folder)
             if f.lower().endswith(VIDEO_EXTS) and os.path.isfile(os.path.join(folder, f))),
            key=lambda p: natural_key(os.path.basename(p)),
        )

    def _vk_read_titles(self) -> list[str]:
        path = self.vk_titles.path()
        if not path or not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                return [line.strip() for line in fh if line.strip()]
        except (OSError, UnicodeDecodeError):
            return []

    def _vk_update_summary(self, *_):
        if not self.vk_folder.path() and not self.vk_titles.path():
            self.vk_summary.setVisible(False)
            return
        self.vk_summary.setVisible(True)
        n_files = len(self._vk_collect_files())
        n_titles = len(self._vk_read_titles())
        n = min(n_files, n_titles, self.vk_max_spin.value())
        text = f"Видео в папке: {n_files}   •   Названий: {n_titles}   •   Будет загружено: {n}"
        if self.vk_folder.path() and self.vk_titles.path() and n_files != n_titles:
            text += "\n⚠ Количество видео и названий не совпадает"
            self.vk_summary.setStyleSheet("color: #e5c07b;")
        else:
            self.vk_summary.setStyleSheet(MUTED)
        self.vk_summary.setText(text)

    def _vk_show_help(self):
        QMessageBox.information(
            self, "Токен ВКонтакте",
            "Токен — это ключ доступа к вашему аккаунту ВК, через который программа загружает видео.\n\n"
            "• Нужен пользовательский токен с правами: video, groups, offline.\n"
            "• Обычно он начинается с «vk1.a.».\n"
            "• Токен хранится только на этом компьютере (в settings.json).\n\n"
            "⚠ Никому не передавайте токен — с ним можно управлять вашим аккаунтом.\n\n"
            "Группа: если загружаете в сообщество, укажите его ID — число из адреса "
            "vk.com/club123456789. Вы должны быть админом или редактором группы."
        )

    def action_vk_start(self):
        token = self.vk_token_edit.text().strip()
        if not token:
            QMessageBox.warning(self, "ВКонтакте", "Укажите токен ВКонтакте (кнопка «?» — подробнее).")
            return
        if not self.vk_folder.exists():
            QMessageBox.warning(self, "ВКонтакте", "Выберите папку с видео.")
            return
        if not self.vk_titles.exists():
            QMessageBox.warning(self, "ВКонтакте", "Выберите файл с названиями (.txt).")
            return

        files = self._vk_collect_files()
        if not files:
            QMessageBox.warning(self, "ВКонтакте", "В выбранной папке нет видеофайлов.")
            return
        titles = self._vk_read_titles()
        if not titles:
            QMessageBox.warning(self, "ВКонтакте", "Файл с названиями пуст или не читается (нужна кодировка UTF-8).")
            return

        group_text = self.vk_group_edit.text().strip()
        group_id = None
        if group_text:
            group_id = parse_vk_group_id(group_text)
            if group_id is None:
                QMessageBox.warning(self, "ВКонтакте",
                                    "Не понял ID группы. Укажите число, например 123456789.")
                return

        total = min(len(files), len(titles), self.vk_max_spin.value())
        if len(files) != len(titles):
            reply = QMessageBox.question(
                self, "ВКонтакте",
                f"Видео в папке: {len(files)}, названий: {len(titles)}.\n"
                f"Будет загружено только {total}. Продолжить?",
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.vk_progress.setMaximum(total)
        self.vk_progress.setValue(0)
        self.vk_log.clear()

        self._vk_uploader = VkUploader(self)
        self._vk_uploader.configure(
            token=token, files=files, titles=titles,
            titles_path=self.vk_titles.path(), group_id=group_id,
            delay=self.vk_delay_spin.value(), max_videos=self.vk_max_spin.value(),
        )
        self._vk_uploader.progress.connect(self._on_vk_progress)
        self._vk_uploader.log_message.connect(self._on_vk_log)
        self._vk_uploader.finished_all.connect(self._on_vk_finished)

        self.vk_btn_start.setEnabled(False)
        self.vk_btn_stop.setEnabled(True)
        self._vk_uploader.start()

    def action_vk_stop(self):
        if self._vk_uploader and self._vk_uploader.isRunning():
            self._vk_uploader.cancel()
            self.vk_btn_stop.setEnabled(False)
            self._on_vk_log("Остановка после текущего видео…")

    def _on_vk_progress(self, current: int, total: int, filename: str):
        self.vk_progress.setValue(current)
        self.vk_progress.setFormat(f"Видео {current} из {total}: {filename}")

    def _on_vk_log(self, text: str):
        self.vk_log.append(text)
        sb = self.vk_log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_vk_finished(self, success: int, errors: int):
        self.vk_btn_start.setEnabled(True)
        self.vk_btn_stop.setEnabled(False)
        self.vk_progress.setFormat(f"Готово: загружено {success}, ошибок {errors}")
        self._vk_update_summary()
        QApplication.alert(self)
        box = QMessageBox.warning if errors else QMessageBox.information
        box(self, "ВКонтакте", f"Загрузка завершена.\n\nЗагружено: {success}\nОшибок: {errors}"
            + ("\n\nПодробности — в журнале на вкладке «ВКонтакте»." if errors else ""))

    # ------------------------------------------------------------------
    # File Management
    # ------------------------------------------------------------------

    def _queued_paths(self) -> set[str]:
        return {os.path.normcase(os.path.abspath(t.file_path)) for t in self.queue_manager.get_tasks()}

    def _add_paths(self, paths: list[str]) -> None:
        """Add files and folders (folder → its video files). Skips duplicates."""
        files: list[str] = []
        for p in paths:
            if os.path.isdir(p):
                found = [os.path.join(p, f) for f in os.listdir(p) if f.lower().endswith(VIDEO_EXTS)]
                files.extend(sorted(found, key=lambda x: natural_key(os.path.basename(x))))
            elif p.lower().endswith(VIDEO_EXTS):
                files.append(p)

        existing = self._queued_paths()
        added = skipped = 0
        for f in files:
            key = os.path.normcase(os.path.abspath(f))
            if key in existing:
                skipped += 1
                continue
            existing.add(key)
            self._add_file_to_queue(f)
            added += 1

        if added or skipped:
            msg = f"Добавлено в очередь: {added}"
            if skipped:
                msg += f" (пропущено, уже в очереди: {skipped})"
            self._log_message(msg)
        elif paths:
            self._log_message("Видеофайлы не найдены. Поддерживаются: " + ", ".join(VIDEO_EXTS))
        self._update_queue_summary()

    def action_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Добавить видео", "", VIDEO_FILTER)
        if files:
            self._add_paths(files)

    def action_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Добавить все видео из папки")
        if folder:
            self._add_paths([folder])

    def _add_file_to_queue(self, path: str):
        self.queue_manager.add_task(path)
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem(Path(path).name)
        name.setToolTip(path)
        self.table.setItem(row, self.COL_NAME, name)
        self.table.setItem(row, self.COL_DUR, QTableWidgetItem("—"))
        self.table.setItem(row, self.COL_STATUS, QTableWidgetItem(TaskStatus.PENDING.value))
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bar.setFormat("")
        self.table.setCellWidget(row, self.COL_PROGRESS, bar)
        self._refresh_row(row)

    def _refresh_row(self, row: int):
        """Row index == task index (kept in sync on add/remove)."""
        tasks = self.queue_manager.get_tasks()
        if not 0 <= row < len(tasks) or row >= self.table.rowCount():
            return
        t = tasks[row]
        if t.duration > 0:
            self.table.item(row, self.COL_DUR).setText(fmt_duration(t.duration))

        st = self.table.item(row, self.COL_STATUS)
        text = t.status.value
        if t.status == TaskStatus.PROCESSING and self.queue_manager.is_paused:
            text = "Пауза"
        st.setText(text)
        color = QColor(STATUS_COLORS.get(t.status, "#e0e0e0"))
        st.setForeground(color)
        tip = t.error_message if t.status == TaskStatus.ERROR else ""
        st.setToolTip(tip)
        self.table.item(row, self.COL_NAME).setToolTip(t.file_path + (f"\n\nОшибка: {tip}" if tip else ""))

        bar: QProgressBar = self.table.cellWidget(row, self.COL_PROGRESS)
        if bar is not None:
            bar.setValue(int(t.progress * 10))
            if t.status == TaskStatus.PROCESSING and t.num_segments > 0:
                bar.setFormat(f"часть {t.current_segment + 1}/{t.num_segments} • {t.progress:.0f}%")
            elif t.status == TaskStatus.DONE:
                bar.setFormat(plural(t.num_segments, "часть", "части", "частей") + " ✓" if t.num_segments else "✓")
            elif t.num_segments > 0 and t.status == TaskStatus.PENDING:
                bar.setFormat(plural(t.num_segments, "часть", "части", "частей"))
            else:
                bar.setFormat(f"{t.progress:.0f}%" if t.progress else "")

    def _update_queue_summary(self):
        tasks = self.queue_manager.get_tasks()
        if not tasks:
            self.lbl_queue_summary.setText("")
            return
        total = sum(t.duration for t in tasks)
        text = f"Файлов: {len(tasks)}"
        if total > 0:
            text += f"   •   Общая длительность: {fmt_duration(total)}"
        done = sum(1 for t in tasks if t.status == TaskStatus.DONE)
        if done:
            text += f"   •   Готово: {done}"
        self.lbl_queue_summary.setText(text)

    def action_remove_files(self):
        if self._running:
            return
        rows = sorted({i.row() for i in self.table.selectedItems()}, reverse=True)
        for r in rows:
            self.queue_manager.remove_task(r)
            self.table.removeRow(r)
        self._update_queue_summary()
        self._update_queue_buttons()

    def action_clear_files(self):
        if self.queue_manager.task_count() == 0:
            return
        reply = QMessageBox.question(self, "Очистить очередь",
                                     "Убрать все файлы из очереди?\n(Сами файлы на диске не удаляются.)")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.queue_manager.clear_tasks()
        self.table.setRowCount(0)
        self.progress_overall.setValue(0)
        self.lbl_eta.setText("")
        self._update_queue_summary()

    # ------------------------------------------------------------------
    # Output folder
    # ------------------------------------------------------------------

    def _output_dir_for(self, src_path: str) -> Path:
        sub = self.settings.get("output_subfolder", "output") or "output"
        return Path(src_path).parent / sub   # absolute `sub` overrides the parent

    def _open_output_folder(self):
        tasks = self.queue_manager.get_tasks()
        target: Path | None = None
        rows = sorted({i.row() for i in self.table.selectedItems()})
        if rows and rows[0] < len(tasks):
            target = self._output_dir_for(tasks[rows[0]].file_path)
        elif tasks:
            done = [t for t in tasks if t.status == TaskStatus.DONE]
            target = self._output_dir_for((done or tasks)[0].file_path)
        else:
            sub = self.settings.get("output_subfolder", "output")
            if sub and Path(sub).is_absolute():
                target = Path(sub)

        if target is None:
            QMessageBox.information(self, "Папка с результатом",
                                    "Добавьте видео в очередь — готовые части появятся в подпапке «output» рядом с ним.")
            return
        if not target.is_dir():
            # nothing produced yet — open the nearest existing parent
            parent = target.parent
            if not parent.is_dir():
                QMessageBox.information(self, "Папка с результатом", f"Папка ещё не создана:\n{target}")
                return
            target = parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    # ------------------------------------------------------------------
    # Processing Control
    # ------------------------------------------------------------------

    def _validate_settings(self) -> list[str]:
        problems = []
        if self.chk_intro.isChecked():
            if not self.intro_path.path():
                problems.append("Интро включено, но видео не выбрано (вкладка «Интро / Аутро»).")
            elif not self.intro_path.exists():
                problems.append(f"Файл интро не найден: {self.intro_path.path()}")
        if self.chk_outro.isChecked():
            if not self.outro_path.path():
                problems.append("Аутро включено, но видео не выбрано (вкладка «Интро / Аутро»).")
            elif not self.outro_path.exists():
                problems.append(f"Файл аутро не найден: {self.outro_path.path()}")
        if self.chk_logo.isChecked():
            if not self._logos_data:
                problems.append("Логотипы включены, но ни одного не добавлено (вкладка «Логотип»).")
            for i, ld in enumerate(self._logos_data, 1):
                p = ld.get("path", "")
                if not p or not Path(p).is_file():
                    problems.append(f"Логотип №{i}: файл не найден ({p or 'не выбран'}).")
        if self.chk_sound.isChecked():
            if not self._sounds_data:
                problems.append("Наложение звука включено, но ни одного файла не добавлено (вкладка «Звук»).")
            for i, sd in enumerate(self._sounds_data, 1):
                p = sd.get("path", "")
                if not p or not Path(p).is_file():
                    problems.append(f"Звук №{i}: файл не найден ({p or 'не выбран'}).")
        if self.rb_out_custom.isChecked() and not self.out_path.path():
            problems.append("Выбрано «В свою папку», но папка не указана (вкладка «Нарезка»).")
        codec = self.cb_codec.currentData()
        if not self._codec_available(codec):
            problems.append(f"Кодек «{self.cb_codec.currentText()}» не работает на этом компьютере (вкладка «Видео»).")
        missing = [t.filename for t in self.queue_manager.get_tasks()
                   if t.status != TaskStatus.DONE and not Path(t.file_path).is_file()]
        if missing:
            problems.append("Файлы из очереди не найдены на диске: " + ", ".join(missing[:5])
                            + (" …" if len(missing) > 5 else ""))
        return problems

    @staticmethod
    def _reset_task(t):
        t.status = TaskStatus.PENDING
        t.progress = 0.0
        t.current_segment = 0
        t.error_message = ""
        t.speed = 0.0
        t.eta_sec = 0.0

    def action_start(self):
        tasks = self.queue_manager.get_tasks()
        if not tasks:
            QMessageBox.information(self, "Очередь пуста",
                                    "Добавьте видео: кнопка «Добавить файлы…» или перетащите их в окно.")
            return

        problems = self._validate_settings()
        if problems:
            QMessageBox.warning(self, "Проверьте настройки",
                                "Перед запуском нужно исправить:\n\n• " + "\n• ".join(problems))
            return

        if all(t.status == TaskStatus.DONE for t in tasks):
            reply = QMessageBox.question(self, "Всё уже готово",
                                         "Все файлы в очереди уже обработаны.\nОбработать их заново?")
            if reply != QMessageBox.StandardButton.Yes:
                return
            for t in tasks:
                self._reset_task(t)
        else:
            # retry failed / cancelled ones, keep finished
            for t in tasks:
                if t.status != TaskStatus.DONE:
                    self._reset_task(t)
        for r in range(len(tasks)):
            self._refresh_row(r)

        self._save_ui_to_settings()
        self._stop_requested = False
        self._set_running(True)

        self.log_text.clear()
        self._log_message("Запуск обработки…")
        self.lbl_eta.setText("")
        self.progress_overall.setValue(0)
        self._queue_start_time = time.time()
        self._elapsed_timer.start()
        self.queue_manager.start_processing(self.settings.get_all())

    def _set_running(self, running: bool):
        self._running = running
        self.btn_start.setEnabled(not running)
        self.btn_pause.setEnabled(running)
        self.btn_stop.setEnabled(running)
        if not running:
            self.btn_pause.setText("⏸ Пауза")
        for b in (self.btn_add_file, self.btn_add_folder, self.btn_clear):
            b.setEnabled(not running)
        self.setAcceptDrops(not running)
        for page in self._processing_tabs:
            page.setEnabled(not running)          # tabs stay viewable; VK tab stays usable
        for w in self._preset_widgets:
            w.setEnabled(not running)
        self._update_queue_buttons()

    def action_pause(self):
        if self.queue_manager.is_paused:
            self.queue_manager.resume()
            self.btn_pause.setText("⏸ Пауза")
            self._log_message("Продолжаем.")
        else:
            self.queue_manager.pause()
            self.btn_pause.setText("▶ Продолжить")
            self._log_message("Пауза: текущая часть доделается, следующая не начнётся.")
        for r in range(self.table.rowCount()):
            self._refresh_row(r)
        self._update_elapsed()

    def action_stop(self):
        reply = QMessageBox.question(self, "Остановить",
                                     "Остановить обработку?\nТекущая часть будет прервана, уже готовые части останутся.")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._stop_requested = True
        self._log_message("Остановка…")
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.queue_manager.cancel()

    # ------------------------------------------------------------------
    # Queue Signals
    # ------------------------------------------------------------------

    def _on_task_updated(self, idx: int):
        self._refresh_row(idx)

    def _on_task_progress(self, task_idx: int, seg_idx: int, percent: float):
        tasks = self.queue_manager.get_tasks()
        if not tasks:
            return
        # weight by duration when known, so long streams count more
        weights = [t.duration if t.duration > 0 else 1.0 for t in tasks]
        done = sum(w * t.progress / 100.0 for w, t in zip(weights, tasks))
        self.progress_overall.setValue(int(done / sum(weights) * 100))

    def _on_task_completed(self, task_idx: int, success: bool, msg: str):
        self._refresh_row(task_idx)
        if not success and msg != "Отменено":
            tasks = self.queue_manager.get_tasks()
            name = tasks[task_idx].filename if task_idx < len(tasks) else f"№{task_idx + 1}"
            self._log_message(f"❌ Ошибка в «{name}»: {msg}")

    def _on_queue_completed(self):
        self._elapsed_timer.stop()
        elapsed = time.time() - self._queue_start_time if self._queue_start_time else 0
        tasks = self.queue_manager.get_tasks()
        done = [t for t in tasks if t.status == TaskStatus.DONE]
        errors = [t for t in tasks if t.status == TaskStatus.ERROR]
        chunks = sum(t.num_segments for t in done)

        self._set_running(False)
        for r in range(len(tasks)):
            self._refresh_row(r)
        self._update_queue_summary()
        if not errors and not self._stop_requested:
            self.progress_overall.setValue(100)

        title = "Остановлено" if self._stop_requested else "Готово"
        self.lbl_eta.setText(
            f"{'⏹' if self._stop_requested else '✅'} {title}   •   Файлов: {len(done)} из {len(tasks)}"
            f"   •   Частей: {chunks}   •   Время: {fmt_duration(elapsed)}"
            + (f"   •   Ошибок: {len(errors)}" if errors else ""))
        self._log_message(f"{title}. Файлов: {len(done)}/{len(tasks)}, частей: {chunks}, "
                          f"время: {fmt_duration(elapsed)}.")

        QApplication.alert(self)
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setIcon(QMessageBox.Icon.Warning if errors else QMessageBox.Icon.Information)
        text = (f"Обработано файлов: {len(done)} из {len(tasks)}\n"
                f"Готовых частей: {chunks}\n"
                f"Затрачено времени: {fmt_duration(elapsed)}")
        if errors:
            text += f"\n\nС ошибками: {len(errors)} (наведите на строку в очереди, чтобы увидеть причину)"
            box.setDetailedText("\n\n".join(f"{t.filename}:\n{t.error_message}" for t in errors))
        box.setText(text)
        btn_open = box.addButton("📂 Открыть папку", QMessageBox.ButtonRole.ActionRole) if done else None
        box.addButton("Закрыть", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if btn_open is not None and box.clickedButton() is btn_open:
            self.table.clearSelection()
            self._open_output_folder()

    # ------------------------------------------------------------------
    # Log
    # ------------------------------------------------------------------

    def _resolve_log_path(self) -> Path | None:
        candidates = [Path(self.settings.path).parent]
        appdata = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        if appdata:
            candidates.append(Path(appdata))
        for d in candidates:
            try:
                d.mkdir(parents=True, exist_ok=True)
                p = d / "debug_log.txt"
                with open(p, "a", encoding="utf-8"):
                    pass
                return p
            except OSError:
                continue
        return None

    def _log_message(self, msg: str):
        self.log_text.append(msg)
        sb = self.log_text.verticalScrollBar()
        sb.setValue(sb.maximum())
        if self._log_path is None:
            self._log_path = self._resolve_log_path() or Path()
        if self._log_path != Path():
            try:
                with open(self._log_path, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
            except OSError:
                pass

    # ------------------------------------------------------------------
    # Presets
    # ------------------------------------------------------------------

    def _build_presets_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(QLabel("Пресет:"))

        self.cb_presets = QComboBox()
        self.cb_presets.setMinimumWidth(160)
        self.cb_presets.setToolTip(
            "Пресет — сохранённый набор настроек обработки (всё, кроме ВК).\n"
            "Звёздочка * означает, что настройки изменены и не сохранены в пресет.")
        bar.addWidget(self.cb_presets, stretch=1)

        btn_save = QPushButton("💾 Сохранить")
        btn_save.setToolTip("Сохранить текущие настройки в пресет")
        btn_save.clicked.connect(self._action_save_preset)
        btn_rename = QPushButton("✏️")
        btn_rename.setToolTip("Переименовать пресет")
        btn_rename.setFixedWidth(36)
        btn_rename.clicked.connect(self._action_rename_preset)
        btn_delete = QPushButton("🗑")
        btn_delete.setToolTip("Удалить пресет")
        btn_delete.setFixedWidth(36)
        btn_delete.clicked.connect(self._action_delete_preset)
        for b in (btn_save, btn_rename, btn_delete):
            bar.addWidget(b)
        self._preset_widgets = [self.cb_presets, btn_save, btn_rename, btn_delete]

        self._refresh_presets_combo(select_name=self.settings.get("active_preset"))
        self.cb_presets.currentIndexChanged.connect(self._on_preset_selected)
        return bar

    def _refresh_presets_combo(self, select_name: str | None = None):
        self.cb_presets.blockSignals(True)
        self.cb_presets.clear()
        self.cb_presets.addItem("— без пресета —", None)
        for name in self.settings.get_preset_names():
            self.cb_presets.addItem(name, name)
        if select_name:
            idx = self.cb_presets.findData(select_name)
            if idx >= 0:
                self.cb_presets.setCurrentIndex(idx)
        self.cb_presets.blockSignals(False)
        if hasattr(self, "tab_main"):
            self._update_preset_dirty()

    def _update_preset_dirty(self):
        """Mark the active preset with * when current settings differ from it."""
        idx = self.cb_presets.currentIndex()
        name = self.cb_presets.itemData(idx)
        if not name:
            return
        data = self.settings.load_preset(name) or {}
        dirty = any(self.settings.get(k) != v for k, v in data.items())
        self.cb_presets.setItemText(idx, f"{name} *" if dirty else name)

    def _on_preset_selected(self, combo_idx: int):
        # clear stale "*" marks on other items
        for i in range(1, self.cb_presets.count()):
            self.cb_presets.setItemText(i, self.cb_presets.itemData(i))
        name = self.cb_presets.itemData(combo_idx)
        if not name:
            self.settings.set_active_preset(None)
            return
        data = self.settings.load_preset(name)
        if data is None:
            return
        self.settings.update(dict(data))
        self._apply_values_to_ui(self.settings.get_all())
        self._save_ui_to_settings()       # normalise anything the preset didn't contain
        self.settings.set_active_preset(name)
        self._update_preset_dirty()
        self._log_message(f"Загружен пресет «{name}».")

    def _action_save_preset(self):
        current_name = self.cb_presets.currentData() or ""
        name, ok = QInputDialog.getText(self, "Сохранить пресет",
                                        "Название пресета:", text=current_name)
        if not ok or not name.strip():
            return
        name = name.strip()
        if name != current_name and name in self.settings.get_preset_names():
            reply = QMessageBox.question(self, "Пресет существует",
                                         f"Пресет «{name}» уже есть. Перезаписать?")
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._save_ui_to_settings()
        self.settings.save_preset(name)
        self._refresh_presets_combo(select_name=name)
        self._log_message(f"Пресет «{name}» сохранён.")

    def _action_rename_preset(self):
        old_name = self.cb_presets.currentData()
        if not old_name:
            QMessageBox.information(self, "Пресеты", "Сначала выберите пресет.")
            return
        new_name, ok = QInputDialog.getText(self, "Переименовать пресет", "Новое название:", text=old_name)
        if not ok or not new_name.strip() or new_name.strip() == old_name:
            return
        new_name = new_name.strip()
        if new_name in self.settings.get_preset_names():
            QMessageBox.warning(self, "Пресеты", f"Пресет «{new_name}» уже существует.")
            return
        self.settings.rename_preset(old_name, new_name)
        self._refresh_presets_combo(select_name=new_name)

    def _action_delete_preset(self):
        name = self.cb_presets.currentData()
        if not name:
            QMessageBox.information(self, "Пресеты", "Сначала выберите пресет.")
            return
        reply = QMessageBox.question(self, "Удалить пресет",
                                     f"Удалить пресет «{name}»?\nТекущие настройки не изменятся.")
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.settings.delete_preset(name)
        self._refresh_presets_combo()

    # ------------------------------------------------------------------
    # Drag and Drop / window events
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and not self._running:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self._add_paths(paths)
            event.acceptProposedAction()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._initial_layout_done:
            self._initial_layout_done = True
            total = sum(self._v_split.sizes())
            self._v_split.setSizes([max(200, total - 130), 130])

    def closeEvent(self, event):
        processing = self._running and self.queue_manager.isRunning()
        uploading = bool(self._vk_uploader and self._vk_uploader.isRunning())
        if processing or uploading:
            what = "Идёт нарезка видео" if processing else "Идёт загрузка в ВК"
            if processing and uploading:
                what = "Идёт нарезка видео и загрузка в ВК"
            reply = QMessageBox.question(
                self, "Выход", f"{what}.\nОстановить и закрыть программу?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._stop_requested = True
            try:
                self.queue_manager.queue_completed.disconnect(self._on_queue_completed)
            except (RuntimeError, TypeError):
                pass
            if processing:
                self.queue_manager.cancel()
            if uploading:
                self._vk_uploader.cancel()
                try:
                    self._vk_uploader.finished_all.disconnect(self._on_vk_finished)
                except (RuntimeError, TypeError):
                    pass
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                if processing:
                    self.queue_manager.wait(15000)
                if uploading:
                    self._vk_uploader.wait(5000)
            finally:
                QApplication.restoreOverrideCursor()
        event.accept()
