"""
Stream Auto Cutter — GUI Module.

Main application window and widgets using PySide6.
"""

import time
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QGroupBox, QLabel, QComboBox, QSpinBox,
    QPushButton, QCheckBox, QSlider, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QTextEdit, QProgressBar, QMessageBox,
    QSplitter, QDialog, QDialogButtonBox, QListWidget, QLineEdit
)

from vk_uploader import VkUploader

from queue_manager import QueueManager, TaskStatus
from settings import Settings
from gpu_detector import detect_available_encoders
from ffmpeg_handler import get_ffmpeg_path



class LogoEditDialog(QDialog):
    def __init__(self, parent=None, logo_data=None):
        super().__init__(parent)
        self.setWindowTitle("Настройка логотипа")
        self.setMinimumWidth(400)
        self.logo_data = logo_data or {
            "path": "",
            "type": "image",
            "position": "top_right",
            "size": 15,
            "opacity": 80,
            "angle": 0,
            "color": "Green (0x00FF00)",
            "display": "full",
            "time_start": 0,
            "time_end": 10
        }
        self._init_ui()
        self._load_data()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        h_type = QHBoxLayout()
        h_type.addWidget(QLabel("Тип:"))
        self.cb_type = QComboBox()
        self.cb_type.addItems(["image", "video_chromakey"])
        self.cb_type.currentIndexChanged.connect(self._on_type_changed)
        h_type.addWidget(self.cb_type)
        layout.addLayout(h_type)

        self.w_color = QWidget()
        h_color = QHBoxLayout(self.w_color)
        h_color.setContentsMargins(0,0,0,0)
        h_color.addWidget(QLabel("Цвет фона (Chromakey):"))
        self.cb_color = QComboBox()
        self.cb_color.addItems(["Green (0x00FF00)", "Blue (0x0000FF)", "Black (0x000000)"])
        h_color.addWidget(self.cb_color)
        layout.addWidget(self.w_color)

        h_path = QHBoxLayout()
        self.lbl_path = QLabel("Путь не выбран")
        btn_browse = QPushButton("Обзор...")
        btn_browse.clicked.connect(self._browse)
        h_path.addWidget(self.lbl_path, stretch=1)
        h_path.addWidget(btn_browse)
        layout.addLayout(h_path)

        h_pos = QHBoxLayout()
        h_pos.addWidget(QLabel("Позиция:"))
        self.cb_pos = QComboBox()
        self.cb_pos.addItems(["top_left", "top_right", "bottom_left", "bottom_right", "center"])
        h_pos.addWidget(self.cb_pos)
        layout.addLayout(h_pos)

        h_size = QHBoxLayout()
        h_size.addWidget(QLabel("Размер (%):"))
        self.spin_size = QSpinBox()
        self.spin_size.setRange(5, 50)
        h_size.addWidget(self.spin_size)
        layout.addLayout(h_size)

        h_op = QHBoxLayout()
        h_op.addWidget(QLabel("Прозрачность (%):"))
        self.spin_op = QSpinBox()
        self.spin_op.setRange(0, 100)
        h_op.addWidget(self.spin_op)
        layout.addLayout(h_op)

        h_angle = QHBoxLayout()
        h_angle.addWidget(QLabel("Угол наклона (град):"))
        self.spin_angle = QSpinBox()
        self.spin_angle.setRange(-360, 360)
        h_angle.addWidget(self.spin_angle)
        layout.addLayout(h_angle)

        h_time = QHBoxLayout()
        h_time.addWidget(QLabel("Показ:"))
        self.cb_time = QComboBox()
        self.cb_time.addItem("На всё видео", "full")
        self.cb_time.addItem("Только на сегмент (без интро/аутро)", "segment_only")
        self.cb_time.addItem("Первые N секунд", "first_n")
        self.cb_time.addItem("Последние N секунд", "last_n")
        self.cb_time.addItem("Своё время", "custom")
        self.cb_time.currentIndexChanged.connect(self._on_time_changed)
        h_time.addWidget(self.cb_time)
        layout.addLayout(h_time)

        self.w_times = QWidget()
        lt = QHBoxLayout(self.w_times)
        lt.setContentsMargins(0,0,0,0)
        lt.addWidget(QLabel("От:"))
        self.spin_tstart = QSpinBox()
        self.spin_tstart.setRange(0, 3600)
        lt.addWidget(self.spin_tstart)
        lt.addWidget(QLabel("До:"))
        self.spin_tend = QSpinBox()
        self.spin_tend.setRange(0, 3600)
        lt.addWidget(self.spin_tend)
        self.w_times.setVisible(False)
        layout.addWidget(self.w_times)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _browse(self):
        f, _ = QFileDialog.getOpenFileName(self, "Выбрать логотип", "", "Media (*.png *.jpg *.jpeg *.mp4 *.mov)")
        if f:
            self.lbl_path.setText(f)

    def _on_time_changed(self):
        display = self.cb_time.currentData()
        # поля времени нужны только для first_n / last_n / custom
        self.w_times.setVisible(display in ("first_n", "last_n", "custom"))
        # для first_n — только поле "До", для last_n — только "От"
        if display == "first_n":
            self.spin_tstart.setEnabled(False)
            self.spin_tend.setEnabled(True)
        elif display == "last_n":
            self.spin_tstart.setEnabled(True)
            self.spin_tend.setEnabled(False)
        else:
            self.spin_tstart.setEnabled(True)
            self.spin_tend.setEnabled(True)

    def _on_type_changed(self):
        self.w_color.setVisible(self.cb_type.currentText() == "video_chromakey")

    def _load_data(self):
        self.cb_type.setCurrentText(self.logo_data.get("type", "image"))
        self.lbl_path.setText(self.logo_data.get("path", "Путь не выбран") or "Путь не выбран")
        self.cb_pos.setCurrentText(self.logo_data.get("position", "top_right"))
        self.spin_size.setValue(self.logo_data.get("size", 15))
        self.spin_op.setValue(self.logo_data.get("opacity", 80))
        self.spin_angle.setValue(self.logo_data.get("angle", 0))
        self.cb_color.setCurrentText(self.logo_data.get("color", "Green (0x00FF00)"))
        # находим индекс по data-значению
        display_val = self.logo_data.get("display", "full")
        idx = self.cb_time.findData(display_val)
        self.cb_time.setCurrentIndex(idx if idx >= 0 else 0)
        self.spin_tstart.setValue(self.logo_data.get("time_start", 0))
        self.spin_tend.setValue(self.logo_data.get("time_end", 10))
        self._on_time_changed()
        self._on_type_changed()

    def get_data(self):
        return {
            "path": self.lbl_path.text() if self.lbl_path.text() != "Путь не выбран" else "",
            "type": self.cb_type.currentText(),
            "position": self.cb_pos.currentText(),
            "size": self.spin_size.value(),
            "opacity": self.spin_op.value(),
            "angle": self.spin_angle.value(),
            "color": self.cb_color.currentText(),
            "display": self.cb_time.currentData(),   # data-значение, не текст с экрана
            "time_start": self.spin_tstart.value(),
            "time_end": self.spin_tend.value(),
        }

class MainWindow(QMainWindow):
    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings

        self.setWindowTitle("Stream Auto Cutter")
        self.resize(1000, 700)
        self.setMinimumSize(800, 600)
        self.setAcceptDrops(True)

        # Set App Window Icon
        for icon_name in ("icon.png", "icon.ico"):
            meipass = getattr(sys, "_MEIPASS", None)
            icon_p = Path(meipass) / icon_name if meipass else Path(__file__).parent / icon_name
            if icon_p.is_file():
                self.setWindowIcon(QIcon(str(icon_p)))
                break

        # Apply dark theme
        self.apply_theme()

        # Core manager
        self.queue_manager = QueueManager(self)
        self.queue_manager.task_updated.connect(self._on_task_updated)
        self.queue_manager.task_progress.connect(self._on_task_progress)
        self.queue_manager.task_completed.connect(self._on_task_completed)
        self.queue_manager.queue_completed.connect(self._on_queue_completed)
        self.queue_manager.log_message.connect(self._on_log_message)

        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Splitter for files list and settings
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter, stretch=1)

        # Left panel: Files
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        files_group = QGroupBox("Очередь файлов")
        files_layout = QVBoxLayout(files_group)
        
        # Files buttons
        files_btn_layout = QHBoxLayout()
        self.btn_add_file = QPushButton("Добавить файлы...")
        self.btn_add_file.clicked.connect(self.action_add_files)
        self.btn_add_folder = QPushButton("Добавить папку...")
        self.btn_add_folder.clicked.connect(self.action_add_folder)
        self.btn_remove = QPushButton("Удалить выбранные")
        self.btn_remove.clicked.connect(self.action_remove_files)
        self.btn_clear = QPushButton("Очистить")
        self.btn_clear.clicked.connect(self.action_clear_files)
        
        files_btn_layout.addWidget(self.btn_add_file)
        files_btn_layout.addWidget(self.btn_add_folder)
        files_btn_layout.addWidget(self.btn_remove)
        files_btn_layout.addWidget(self.btn_clear)
        files_layout.addLayout(files_btn_layout)

        # Table
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Имя", "Длительность", "Статус", "Прогресс"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(3, 100)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        # Enable drag and drop later
        self.table.setAcceptDrops(True)
        files_layout.addWidget(self.table)
        
        left_layout.addWidget(files_group)
        splitter.addWidget(left_panel)

        # Right panel: Settings
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        self.tabs = QTabWidget()
        
        self.tab_cut = self._create_cut_tab()
        self.tab_io = self._create_io_tab()
        self.tab_logo = self._create_logo_tab()
        self.tab_video = self._create_video_tab()
        self.tab_vk = self._create_vk_tab()
        
        self.tabs.addTab(self.tab_cut, "Нарезка")
        self.tabs.addTab(self.tab_io, "Интро/Аутро")
        self.tabs.addTab(self.tab_logo, "Логотип")
        self.tabs.addTab(self.tab_video, "Видео")
        self.tabs.addTab(self.tab_vk, "ВКонтакте")

        # VK uploader worker
        self._vk_uploader: VkUploader | None = None
        
        right_layout.addWidget(self.tabs)
        splitter.addWidget(right_panel)
        
        splitter.setSizes([400, 400])

        # Bottom panel: Log and Progress
        bottom_layout = QVBoxLayout()
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(100)
        bottom_layout.addWidget(self.log_text)
        
        controls_layout = QHBoxLayout()
        
        self.btn_start = QPushButton("▶ Старт")
        self.btn_start.setMinimumHeight(40)
        self.btn_start.clicked.connect(self.action_start)
        
        self.btn_pause = QPushButton("⏸ Пауза")
        self.btn_pause.setMinimumHeight(40)
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.action_pause)
        
        self.btn_stop = QPushButton("⏹ Стоп")
        self.btn_stop.setMinimumHeight(40)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.action_stop)
        
        self.progress_overall = QProgressBar()
        self.progress_overall.setTextVisible(True)
        self.progress_overall.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_overall.setFormat("%p%")
        
        controls_layout.addWidget(self.btn_start)
        controls_layout.addWidget(self.btn_pause)
        controls_layout.addWidget(self.btn_stop)
        controls_layout.addWidget(self.progress_overall, stretch=1)
        
        bottom_layout.addLayout(controls_layout)

        # ETA / speed / chunks info line
        self.lbl_eta = QLabel("")
        self.lbl_eta.setStyleSheet("color: #a0a0a0; font-size: 12px; padding: 2px 4px;")
        bottom_layout.addWidget(self.lbl_eta)

        main_layout.addLayout(bottom_layout)

        # Queue timing
        self._queue_start_time: float = 0.0
        self._available_encoders: dict = {}

        # Elapsed-time timer (ticks every second while processing)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._update_elapsed)

        # Load settings to UI
        self._load_settings_to_ui()
        
        # Connect settings changes to save
        self._connect_ui_to_settings()

        # Auto-detect GPU encoders in background
        self._detect_gpu_encoders()

    # ------------------------------------------------------------------
    # UI Creation
    # ------------------------------------------------------------------

    def _create_cut_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        group = QGroupBox("Настройки нарезки")
        glayout = QVBoxLayout(group)
        
        hlayout = QHBoxLayout()
        hlayout.addWidget(QLabel("Длина части:"))
        
        self.cb_duration = QComboBox()
        self.cb_duration.addItems(["5 минут", "10 минут", "16 минут", "20 минут", "30 минут", "Своё значение"])
        self.cb_duration.currentIndexChanged.connect(self._on_duration_type_changed)
        hlayout.addWidget(self.cb_duration)
        
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(1, 600)
        self.spin_duration.setSuffix(" мин")
        self.spin_duration.setEnabled(False)
        hlayout.addWidget(self.spin_duration)
        
        hlayout.addStretch()
        glayout.addLayout(hlayout)
        
        layout.addWidget(group)
        layout.addStretch()
        return widget

    def _create_io_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Intro
        grp_intro = QGroupBox("Интро")
        l_intro = QVBoxLayout(grp_intro)
        
        self.chk_intro = QCheckBox("Включить интро")
        l_intro.addWidget(self.chk_intro)
        
        h_intro = QHBoxLayout()
        self.lbl_intro_path = QLabel("Путь не выбран")
        btn_intro_browse = QPushButton("Обзор...")
        btn_intro_browse.clicked.connect(lambda: self._browse_file(self.lbl_intro_path, "intro_path"))
        h_intro.addWidget(self.lbl_intro_path, stretch=1)
        h_intro.addWidget(btn_intro_browse)
        l_intro.addLayout(h_intro)
        layout.addWidget(grp_intro)
        
        # Outro
        grp_outro = QGroupBox("Аутро")
        l_outro = QVBoxLayout(grp_outro)
        
        self.chk_outro = QCheckBox("Включить аутро")
        l_outro.addWidget(self.chk_outro)
        
        h_outro = QHBoxLayout()
        self.lbl_outro_path = QLabel("Путь не выбран")
        btn_outro_browse = QPushButton("Обзор...")
        btn_outro_browse.clicked.connect(lambda: self._browse_file(self.lbl_outro_path, "outro_path"))
        h_outro.addWidget(self.lbl_outro_path, stretch=1)
        h_outro.addWidget(btn_outro_browse)
        l_outro.addLayout(h_outro)
        layout.addWidget(grp_outro)
        
        layout.addStretch()
        return widget


    def _create_logo_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        self.chk_logo = QCheckBox("Включить наложение логотипов")
        layout.addWidget(self.chk_logo)
        
        self.list_logos = QListWidget()
        layout.addWidget(self.list_logos)
        
        h_btns = QHBoxLayout()
        btn_add = QPushButton("Добавить логотип")
        btn_add.clicked.connect(self._action_add_logo)
        h_btns.addWidget(btn_add)
        
        btn_edit = QPushButton("Изменить")
        btn_edit.clicked.connect(self._action_edit_logo)
        h_btns.addWidget(btn_edit)
        
        btn_remove = QPushButton("Удалить")
        btn_remove.clicked.connect(self._action_remove_logo)
        h_btns.addWidget(btn_remove)
        
        layout.addLayout(h_btns)
        
        # Save reference for internal list of dicts
        self._logos_data = []
        
        return widget

    def _refresh_logos_list(self):
        self.list_logos.clear()
        for i, ld in enumerate(self._logos_data):
            p = ld.get("path", "")
            name = Path(p).name if p else "Не выбран"
            pos = ld.get("position", "")
            self.list_logos.addItem(f"{i+1}. {name} [{pos}]")

    def _action_add_logo(self):
        dlg = LogoEditDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._logos_data.append(dlg.get_data())
            self._refresh_logos_list()
            self._save_ui_to_settings()

    def _action_edit_logo(self):
        r = self.list_logos.currentRow()
        if r < 0 or r >= len(self._logos_data): return
        dlg = LogoEditDialog(self, self._logos_data[r])
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._logos_data[r] = dlg.get_data()
            self._refresh_logos_list()
            self._save_ui_to_settings()

    def _action_remove_logo(self):
        r = self.list_logos.currentRow()
        if r >= 0 and r < len(self._logos_data):
            del self._logos_data[r]
            self._refresh_logos_list()
            self._save_ui_to_settings()

    def _create_video_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        grp = QGroupBox("Настройки видео")
        glayout = QVBoxLayout(grp)
        
        # Resolution
        h_res = QHBoxLayout()
        h_res.addWidget(QLabel("Разрешение:"))
        self.cb_res = QComboBox()
        self.cb_res.addItems(["source", "1280x720", "1920x1080", "2560x1440", "3840x2160", "custom"])
        self.cb_res.currentIndexChanged.connect(self._on_res_changed)
        h_res.addWidget(self.cb_res)
        
        self.spin_res_w = QSpinBox()
        self.spin_res_w.setRange(320, 7680)
        self.spin_res_w.setVisible(False)
        self.spin_res_h = QSpinBox()
        self.spin_res_h.setRange(240, 4320)
        self.spin_res_h.setVisible(False)
        h_res.addWidget(self.spin_res_w)
        h_res.addWidget(self.spin_res_h)
        h_res.addStretch()
        glayout.addLayout(h_res)
        
        # FPS
        h_fps = QHBoxLayout()
        h_fps.addWidget(QLabel("FPS:"))
        self.cb_fps = QComboBox()
        self.cb_fps.addItems(["source", "24", "30", "60"])
        h_fps.addWidget(self.cb_fps)
        h_fps.addStretch()
        glayout.addLayout(h_fps)
        
        # Codec
        h_codec = QHBoxLayout()
        h_codec.addWidget(QLabel("Кодек:"))
        self.cb_codec = QComboBox()
        self.cb_codec.addItem("h264_nvenc (NVIDIA)", "h264_nvenc")
        self.cb_codec.addItem("hevc_nvenc (NVIDIA)", "hevc_nvenc")
        self.cb_codec.addItem("h264_videotoolbox (Mac)", "h264_videotoolbox")
        self.cb_codec.addItem("hevc_videotoolbox (Mac)", "hevc_videotoolbox")
        self.cb_codec.addItem("libx264 (Процессор)", "libx264")
        self.cb_codec.addItem("libx265 (Процессор)", "libx265")
        h_codec.addWidget(self.cb_codec)
        h_codec.addStretch()
        glayout.addLayout(h_codec)
        
        layout.addWidget(grp)
        layout.addStretch()
        return widget





    def _create_vk_tab(self) -> QWidget:
        """Вкладка загрузки видео в ВКонтакте."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(8)

        # --- Авторизация ---
        auth_group = QGroupBox("Авторизация")
        auth_layout = QVBoxLayout(auth_group)

        h_token = QHBoxLayout()
        h_token.addWidget(QLabel("Токен ВК:"))
        self.vk_token_edit = QLineEdit()
        self.vk_token_edit.setPlaceholderText("vk1.a.xxxxxxxxxxxx...")
        self.vk_token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        h_token.addWidget(self.vk_token_edit, stretch=1)
        auth_layout.addLayout(h_token)

        h_group = QHBoxLayout()
        h_group.addWidget(QLabel("ID группы (пусто = личная страница):"))
        self.vk_group_edit = QLineEdit()
        self.vk_group_edit.setPlaceholderText("123456789")
        h_group.addWidget(self.vk_group_edit, stretch=1)
        auth_layout.addLayout(h_group)

        layout.addWidget(auth_group)

        # --- Источник видео ---
        src_group = QGroupBox("Исходные файлы")
        src_layout = QVBoxLayout(src_group)

        h_folder = QHBoxLayout()
        h_folder.addWidget(QLabel("Папка с видео:"))
        self.vk_folder_lbl = QLabel("Не выбрана")
        self.vk_folder_lbl.setWordWrap(True)
        btn_folder = QPushButton("Обзор...")
        btn_folder.clicked.connect(self._vk_browse_folder)
        h_folder.addWidget(self.vk_folder_lbl, stretch=1)
        h_folder.addWidget(btn_folder)
        src_layout.addLayout(h_folder)

        h_titles = QHBoxLayout()
        h_titles.addWidget(QLabel("Файл с названиями:"))
        self.vk_titles_lbl = QLabel("Не выбран")
        self.vk_titles_lbl.setWordWrap(True)
        btn_titles = QPushButton("Обзор...")
        btn_titles.clicked.connect(self._vk_browse_titles)
        h_titles.addWidget(self.vk_titles_lbl, stretch=1)
        h_titles.addWidget(btn_titles)
        src_layout.addLayout(h_titles)

        layout.addWidget(src_group)

        # --- Параметры загрузки ---
        params_group = QGroupBox("Параметры")
        params_layout = QHBoxLayout(params_group)

        params_layout.addWidget(QLabel("Пауза (сек):"))
        self.vk_delay_spin = QSpinBox()
        self.vk_delay_spin.setRange(1, 300)
        self.vk_delay_spin.setValue(10)
        params_layout.addWidget(self.vk_delay_spin)

        params_layout.addSpacing(20)
        params_layout.addWidget(QLabel("Макс. видео за сессию:"))
        self.vk_max_spin = QSpinBox()
        self.vk_max_spin.setRange(1, 1000)
        self.vk_max_spin.setValue(150)
        params_layout.addWidget(self.vk_max_spin)
        params_layout.addStretch()

        layout.addWidget(params_group)

        # --- Управление ---
        ctrl_layout = QHBoxLayout()
        self.vk_btn_start = QPushButton("▶ Загрузить в ВК")
        self.vk_btn_start.setMinimumHeight(36)
        self.vk_btn_start.clicked.connect(self.action_vk_start)
        self.vk_btn_stop = QPushButton("⏹ Остановить")
        self.vk_btn_stop.setMinimumHeight(36)
        self.vk_btn_stop.setEnabled(False)
        self.vk_btn_stop.clicked.connect(self.action_vk_stop)
        ctrl_layout.addWidget(self.vk_btn_start)
        ctrl_layout.addWidget(self.vk_btn_stop)
        layout.addLayout(ctrl_layout)

        # --- Прогресс ---
        self.vk_progress = QProgressBar()
        self.vk_progress.setTextVisible(True)
        self.vk_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vk_progress.setFormat("Файл %v из %m")
        layout.addWidget(self.vk_progress)

        # --- Лог ---
        self.vk_log = QTextEdit()
        self.vk_log.setReadOnly(True)
        layout.addWidget(self.vk_log, stretch=1)

        return widget

    def apply_theme(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #2b2b2b;
                color: #e0e0e0;
            }
            QGroupBox {
                border: 1px solid #555;
                border-radius: 4px;
                margin-top: 1ex;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 3px;
                color: #a0a0a0;
            }
            QPushButton {
                background-color: #3c3f41;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 5px 15px;
            }
            QPushButton:hover {
                background-color: #4c5052;
            }
            QPushButton:pressed {
                background-color: #2b2b2b;
            }
            QTableWidget {
                background-color: #1e1e1e;
                alternate-background-color: #2a2a2a;
                gridline-color: #333;
                border: 1px solid #555;
            }
            QHeaderView::section {
                background-color: #3c3f41;
                padding: 4px;
                border: 1px solid #555;
            }
            QTabWidget::pane {
                border: 1px solid #555;
            }
            QTabBar::tab {
                background: #3c3f41;
                border: 1px solid #555;
                padding: 5px 15px;
            }
            QTabBar::tab:selected {
                background: #4c5052;
            }
            QTextEdit {
                background-color: #1e1e1e;
                border: 1px solid #555;
                font-family: monospace;
            }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 4px;
                text-align: center;
            }
            QProgressBar::chunk {
                background-color: #007acc;
            }
        """)

    # ------------------------------------------------------------------
    # Data sync
    # ------------------------------------------------------------------
    
    def _load_settings_to_ui(self):
        s = self.settings
        
        # Cut
        dur = s.get("segment_duration_min", 16)
        dur_map = {5: 0, 10: 1, 16: 2, 20: 3, 30: 4}
        if dur in dur_map:
            self.cb_duration.setCurrentIndex(dur_map[dur])
            self.spin_duration.setValue(dur)
        else:
            self.cb_duration.setCurrentIndex(5)
            self.spin_duration.setValue(dur)
            
        # IO
        self.chk_intro.setChecked(s.get("intro_enabled", False))
        self.chk_outro.setChecked(s.get("outro_enabled", False))
        self.lbl_intro_path.setText(s.get("intro_path", "Путь не выбран") or "Путь не выбран")
        self.lbl_outro_path.setText(s.get("outro_path", "Путь не выбран") or "Путь не выбран")
        
        # Logo
        self.chk_logo.setChecked(s.get("logo_enabled", False))
        self._logos_data = s.get("logos", [])
        self._refresh_logos_list()
        
        # Video
        self.cb_res.setCurrentText(s.get("resolution", "source"))
        self.spin_res_w.setValue(s.get("custom_resolution_w", 1920))
        self.spin_res_h.setValue(s.get("custom_resolution_h", 1080))
        self.cb_fps.setCurrentText(s.get("fps", "source"))
        
        codec_val = s.get("codec", "h264_nvenc")
        idx = self.cb_codec.findData(codec_val)
        if idx >= 0:
            self.cb_codec.setCurrentIndex(idx)
        else:
            self.cb_codec.setCurrentIndex(0)
            


        # VK
        self.vk_token_edit.setText(s.get("vk_token", ""))
        self.vk_group_edit.setText(s.get("vk_group_id", ""))
        self.vk_titles_lbl.setText(s.get("vk_titles_file", "") or "Не выбран")
        self.vk_folder_lbl.setText(s.get("vk_video_folder", "") or "Не выбрана")
        self.vk_delay_spin.setValue(s.get("vk_delay_sec", 10))
        self.vk_max_spin.setValue(s.get("vk_max_videos", 150))

    def _save_ui_to_settings(self):
        s = self.settings
        
        # Cut
        idx = self.cb_duration.currentIndex()
        if idx == 5:
            s.set("segment_duration_min", self.spin_duration.value())
        else:
            val = [5, 10, 16, 20, 30][idx]
            s.set("segment_duration_min", val)
            
        # IO
        s.set("intro_enabled", self.chk_intro.isChecked())
        s.set("outro_enabled", self.chk_outro.isChecked())
        
        # Logo
        s.set("logo_enabled", self.chk_logo.isChecked())
        s.set("logos", self._logos_data)
        
        # Video
        s.set("resolution", self.cb_res.currentText())
        s.set("custom_resolution_w", self.spin_res_w.value())
        s.set("custom_resolution_h", self.spin_res_h.value())
        s.set("fps", self.cb_fps.currentText())
        s.set("codec", self.cb_codec.currentData())
        


        # VK
        s.set("vk_token", self.vk_token_edit.text().strip())
        s.set("vk_group_id", self.vk_group_edit.text().strip())
        s.set("vk_delay_sec", self.vk_delay_spin.value())
        s.set("vk_max_videos", self.vk_max_spin.value())

    def _connect_ui_to_settings(self):
        # Trigger save on any relevant change
        self.cb_duration.currentIndexChanged.connect(self._save_ui_to_settings)
        self.spin_duration.valueChanged.connect(self._save_ui_to_settings)
        
        self.chk_intro.toggled.connect(self._save_ui_to_settings)
        self.chk_outro.toggled.connect(self._save_ui_to_settings)
        
        self.chk_logo.toggled.connect(self._save_ui_to_settings)

        
        self.cb_res.currentIndexChanged.connect(self._save_ui_to_settings)
        self.spin_res_w.valueChanged.connect(self._save_ui_to_settings)
        self.spin_res_h.valueChanged.connect(self._save_ui_to_settings)
        self.cb_fps.currentIndexChanged.connect(self._save_ui_to_settings)
        self.cb_codec.currentIndexChanged.connect(self._save_ui_to_settings)
        


        # VK
        self.vk_token_edit.textChanged.connect(self._save_ui_to_settings)
        self.vk_group_edit.textChanged.connect(self._save_ui_to_settings)
        self.vk_delay_spin.valueChanged.connect(self._save_ui_to_settings)
        self.vk_max_spin.valueChanged.connect(self._save_ui_to_settings)

    # ------------------------------------------------------------------
    # GPU Detection & Elapsed Timer
    # ------------------------------------------------------------------

    def _detect_gpu_encoders(self):
        """Run GPU encoder detection in a background thread."""
        def _worker():
            try:
                self._available_encoders = detect_available_encoders(get_ffmpeg_path())
            except Exception:
                self._available_encoders = {}
            # Schedule UI update on the main thread
            QTimer.singleShot(0, self._on_encoders_detected)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()

    def _on_encoders_detected(self):
        """Update codec combo: mark unavailable encoders."""
        if not self._available_encoders:
            return
        for i in range(self.cb_codec.count()):
            codec_val = self.cb_codec.itemData(i)
            if codec_val in self._available_encoders:
                if not self._available_encoders[codec_val]:
                    txt = self.cb_codec.itemText(i)
                    if "(недоступен)" not in txt:
                        self.cb_codec.setItemText(i, f"{txt} (недоступен)")

    def _update_elapsed(self):
        """Called every second by _elapsed_timer while processing."""
        tasks = self.queue_manager.get_tasks()
        if not tasks:
            return

        # Overall elapsed since queue started
        elapsed = time.time() - self._queue_start_time if self._queue_start_time else 0

        # Total chunks across ALL files (all probed upfront, so num_segments is accurate)
        total_chunks = sum(t.num_segments for t in tasks)
        done_chunks = 0
        for t in tasks:
            if t.status == TaskStatus.DONE:
                done_chunks += t.num_segments
            elif t.status == TaskStatus.PROCESSING:
                done_chunks += t.current_segment  # completed segments in active task

        # Current encoding speed (from the active task)
        current_speed = 0.0
        for t in tasks:
            if t.status == TaskStatus.PROCESSING and t.speed > 0:
                current_speed = t.speed
                break

        # ---- Total queue ETA ----
        # All files already probed → t.duration is known for every task
        total_eta = 0.0
        for t in tasks:
            if t.status == TaskStatus.PROCESSING:
                # remaining video seconds in this task / encoding speed
                total_eta += t.eta_sec
            elif t.status == TaskStatus.PENDING:
                # entire file still waiting — use current speed
                if current_speed > 0:
                    total_eta += t.duration / current_speed

        # Total video remaining (for display)
        total_video_remaining = 0.0
        for t in tasks:
            if t.status == TaskStatus.PROCESSING:
                total_video_remaining += t.duration * (1.0 - t.progress / 100.0)
            elif t.status == TaskStatus.PENDING:
                total_video_remaining += t.duration

        parts = []
        parts.append(f"Кусков: {done_chunks}/{total_chunks}")
        parts.append(f"Прошло: {self._fmt_duration(elapsed)}")
        if total_eta > 0:
            parts.append(f"Осталось: ~{self._fmt_duration(total_eta)}")
        if current_speed > 0:
            parts.append(f"Скорость: {current_speed:.1f}x")
        if total_video_remaining > 0:
            parts.append(f"Видео: {self._fmt_duration(total_video_remaining)}")

        self.lbl_eta.setText("  |  ".join(parts))

    @staticmethod
    def _fmt_duration(seconds: float) -> str:
        """Format seconds into HH:MM:SS or MM:SS."""
        s = int(seconds)
        h, remainder = divmod(s, 3600)
        m, sec = divmod(remainder, 60)
        if h:
            return f"{h}:{m:02d}:{sec:02d}"
        return f"{m:02d}:{sec:02d}"

    # ------------------------------------------------------------------
    # UI Logic & Events
    # ------------------------------------------------------------------
    
    def _on_duration_type_changed(self, idx: int):
        self.spin_duration.setEnabled(idx == 5)
        
    def _on_logo_time_changed(self, idx: int):
        self.w_logo_times.setVisible(idx != 0) # hide if "full"
        
    def _on_res_changed(self, idx: int):
        txt = self.cb_res.currentText()
        show_custom = (txt == "custom")
        self.spin_res_w.setVisible(show_custom)
        self.spin_res_h.setVisible(show_custom)
        

        
    def _browse_file(self, label_widget: QLabel, settings_key: str):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите файл", filter="Видео (*.mp4 *.mkv *.mov)")
        if path:
            label_widget.setText(path)
            self.settings.set(settings_key, path)

    def _browse_logo(self):
        is_video = (self.cb_logo_type.currentIndex() == 1)
        flt = "Видео (*.mp4 *.mkv *.mov)" if is_video else "Картинки (*.png *.jpg *.jpeg)"
        path, _ = QFileDialog.getOpenFileName(self, "Выберите логотип", filter=flt)
        if path:
            self.lbl_logo_path.setText(path)
            self.settings.set("logo_path", path)
            self._save_ui_to_settings()



    # ------------------------------------------------------------------
    # VK Uploader
    # ------------------------------------------------------------------

    def _vk_browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Выберите папку с видео")
        if folder:
            self.vk_folder_lbl.setText(folder)
            self.settings.set("vk_video_folder", folder)

    def _vk_browse_titles(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл с названиями", filter="Текстовые файлы (*.txt)"
        )
        if path:
            self.vk_titles_lbl.setText(path)
            self.settings.set("vk_titles_file", path)

    def action_vk_start(self):
        import os, re

        token = self.vk_token_edit.text().strip()
        if not token:
            QMessageBox.warning(self, "ВКонтакте", "Укажите токен ВКонтакте.")
            return

        folder = self.vk_folder_lbl.text()
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "ВКонтакте", "Укажите корректную папку с видео.")
            return

        titles_path = self.vk_titles_lbl.text()
        if not titles_path or not os.path.isfile(titles_path):
            QMessageBox.warning(self, "ВКонтакте", "Укажите файл с названиями.")
            return

        # --- собираем файлы (естественная сортировка) ---
        def _nat_key(s: str):
            return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

        exts = (".mp4", ".mov", ".avi", ".mkv", ".webm")
        files = sorted(
            [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(exts)],
            key=lambda p: _nat_key(os.path.basename(p)),
        )

        if not files:
            QMessageBox.warning(self, "ВКонтакте", "В папке нет видеофайлов.")
            return

        with open(titles_path, "r", encoding="utf-8") as fh:
            titles = [line.strip() for line in fh if line.strip()]

        if not titles:
            QMessageBox.warning(self, "ВКонтакте", "Файл с названиями пуст.")
            return

        group_id_str = self.vk_group_edit.text().strip()
        group_id = int(group_id_str) if group_id_str.isdigit() else None

        total = min(len(files), len(titles), self.vk_max_spin.value())
        self.vk_progress.setMaximum(total)
        self.vk_progress.setValue(0)
        self.vk_log.clear()

        self._vk_uploader = VkUploader(self)
        self._vk_uploader.configure(
            token=token,
            files=files,
            titles=titles,
            titles_path=titles_path,
            group_id=group_id,
            delay=self.vk_delay_spin.value(),
            max_videos=self.vk_max_spin.value(),
        )
        self._vk_uploader.progress.connect(self._on_vk_progress)
        self._vk_uploader.file_done.connect(self._on_vk_file_done)
        self._vk_uploader.log_message.connect(self._on_vk_log)
        self._vk_uploader.finished_all.connect(self._on_vk_finished)

        self.vk_btn_start.setEnabled(False)
        self.vk_btn_stop.setEnabled(True)
        self._vk_uploader.start()

    def action_vk_stop(self):
        if self._vk_uploader and self._vk_uploader.isRunning():
            self._vk_uploader.cancel()
            self.vk_btn_stop.setEnabled(False)

    def _on_vk_progress(self, current: int, total: int, filename: str):
        self.vk_progress.setValue(current)
        self.vk_progress.setFormat(f"Файл {current} из {total}: {filename}")

    def _on_vk_file_done(self, filename: str, vid_id: str, ok: bool):
        pass  # подробности уже в лог

    def _on_vk_log(self, text: str):
        self.vk_log.append(text)
        scrollbar = self.vk_log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_vk_finished(self, success: int, errors: int):
        self.vk_btn_start.setEnabled(True)
        self.vk_btn_stop.setEnabled(False)
        self.vk_progress.setFormat(f"Готово: {success} загружено, {errors} ошибок")
        QMessageBox.information(
            self, "ВКонтакте",
            f"Загрузка завершена.\nУспешно: {success}\nОшибок: {errors}"
        )

    # ------------------------------------------------------------------
    # File Management
    # ------------------------------------------------------------------

    def action_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Добавить видео", filter="Видео (*.mp4 *.mkv *.mov)")
        for f in files:
            self._add_file_to_queue(f)

    def action_add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Добавить папку")
        if folder:
            import os
            for file in os.listdir(folder):
                if file.lower().endswith(('.mp4', '.mkv', '.mov')):
                    self._add_file_to_queue(os.path.join(folder, file))
                    
    def _add_file_to_queue(self, path: str):
        idx = self.queue_manager.add_task(path)
        
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        item_name = QTableWidgetItem(Path(path).name)
        item_dur = QTableWidgetItem("---")
        item_status = QTableWidgetItem(TaskStatus.PENDING.value)
        item_prog = QTableWidgetItem("0%")
        
        # Store index in data
        item_name.setData(Qt.ItemDataRole.UserRole, idx)
        
        self.table.setItem(row, 0, item_name)
        self.table.setItem(row, 1, item_dur)
        self.table.setItem(row, 2, item_status)
        self.table.setItem(row, 3, item_prog)
        
    def action_remove_files(self):
        # Get selected rows
        rows = sorted(list(set(item.row() for item in self.table.selectedItems())), reverse=True)
        for r in rows:
            idx = self.table.item(r, 0).data(Qt.ItemDataRole.UserRole)
            self.queue_manager.remove_task(idx)
            self.table.removeRow(r)
            
        # Re-sync UI with queue (re-add all to fix indices)
        tasks = self.queue_manager.get_tasks()
        self.queue_manager.clear_tasks()
        self.table.setRowCount(0)
        for t in tasks:
            self._add_file_to_queue(t.file_path)

    def action_clear_files(self):
        self.queue_manager.clear_tasks()
        self.table.setRowCount(0)

    # ------------------------------------------------------------------
    # Processing Control
    # ------------------------------------------------------------------

    def action_start(self):
        if self.queue_manager.task_count() == 0:
            QMessageBox.warning(self, "Внимание", "Очередь пуста.")
            return
            
        self._save_ui_to_settings()
        
        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_stop.setEnabled(True)
        
        # Disable queue modifications
        self.btn_add_file.setEnabled(False)
        self.btn_add_folder.setEnabled(False)
        self.btn_remove.setEnabled(False)
        self.btn_clear.setEnabled(False)
        self.tabs.setEnabled(False)
        
        self.log_text.clear()
        self._log_message("Запуск обработки...")
        self.lbl_eta.setText("")
        
        self._queue_start_time = time.time()
        self._elapsed_timer.start()
        
        self.queue_manager.start_processing(self.settings.get_all())
        
    def action_pause(self):
        if self.queue_manager.is_paused:
            self.queue_manager.resume()
            self.btn_pause.setText("⏸ Пауза")
            self._log_message("Обработка возобновлена.")
        else:
            self.queue_manager.pause()
            self.btn_pause.setText("▶ Продолжить")
            self._log_message("Обработка приостановлена (после завершения текущего сегмента).")
            
    def action_stop(self):
        self._log_message("Остановка (ожидание завершения текущей операции)...")
        self.btn_stop.setEnabled(False)
        self.btn_pause.setEnabled(False)
        self.queue_manager.cancel()

    # ------------------------------------------------------------------
    # Queue Signals
    # ------------------------------------------------------------------
    
    def _find_row_by_task_idx(self, idx: int) -> int:
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) == idx:
                return r
        return -1

    def _on_task_updated(self, idx: int):
        row = self._find_row_by_task_idx(idx)
        if row < 0: return
        
        tasks = self.queue_manager.get_tasks()
        if idx >= len(tasks): return
        t = tasks[idx]
        
        # update duration
        if t.duration > 0:
            m, s = divmod(int(t.duration), 60)
            h, m = divmod(m, 60)
            dur_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            self.table.item(row, 1).setText(dur_str)
            
        self.table.item(row, 2).setText(t.status.value)
        # Show [Кусок X/Y] Z% in progress column
        if t.num_segments > 0 and t.status == TaskStatus.PROCESSING:
            seg_display = t.current_segment + 1
            self.table.item(row, 3).setText(
                f"[{seg_display}/{t.num_segments}] {t.progress:.1f}%"
            )
        else:
            self.table.item(row, 3).setText(f"{t.progress:.1f}%")
        
    def _on_task_progress(self, task_idx: int, seg_idx: int, percent: float):
        self._on_task_updated(task_idx)
        # Update overall roughly
        tasks = self.queue_manager.get_tasks()
        if not tasks: return
        
        total = 100.0 * len(tasks)
        current = sum(t.progress for t in tasks)
        self.progress_overall.setValue(int(current / total * 100))
        
    def _on_task_completed(self, task_idx: int, success: bool, msg: str):
        self._on_task_updated(task_idx)
        if not success:
            self._log_message(f"Ошибка задачи {task_idx}: {msg}")
            
    def _on_queue_completed(self):
        self._elapsed_timer.stop()
        elapsed = time.time() - self._queue_start_time if self._queue_start_time else 0

        tasks = self.queue_manager.get_tasks()
        total_chunks = sum(t.num_segments for t in tasks)

        self._log_message(
            f"Обработка всей очереди завершена. "
            f"Кусков: {total_chunks}, Время: {self._fmt_duration(elapsed)}"
        )
        self.lbl_eta.setText(
            f"✅ Готово  |  Кусков: {total_chunks}  |  "
            f"Общее время: {self._fmt_duration(elapsed)}"
        )
        
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_pause.setText("⏸ Пауза")
        self.btn_stop.setEnabled(False)
        
        self.btn_add_file.setEnabled(True)
        self.btn_add_folder.setEnabled(True)
        self.btn_remove.setEnabled(True)
        self.btn_clear.setEnabled(True)
        self.tabs.setEnabled(True)
        
        self.progress_overall.setValue(100)
        
    def _on_log_message(self, msg: str):
        self._log_message(msg)
        
    def _log_message(self, msg: str):
        self.log_text.append(msg)
        with open("debug_log.txt", "a", encoding="utf-8") as f:
            f.write(msg + "\n")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ------------------------------------------------------------------
    # Drag and Drop
    # ------------------------------------------------------------------
    # To properly handle drag & drop we would override dragEnterEvent
    # and dropEvent on the table or main window. For simplicity, we can
    # leave it as a quick implementation if needed, but it's requested.
    
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(('.mp4', '.mkv', '.mov')):
                self._add_file_to_queue(path)
