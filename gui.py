"""
Stream Auto Cutter — GUI Module.

Main application window and widgets using PySide6.
"""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QAction
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QGroupBox, QLabel, QComboBox, QSpinBox,
    QPushButton, QCheckBox, QSlider, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QTextEdit, QProgressBar, QMessageBox,
    QSplitter
)

from queue_manager import QueueManager, TaskStatus
from settings import Settings
from profiles import ProfileManager


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, profiles: ProfileManager):
        super().__init__()
        self.settings = settings
        self.profiles = profiles

        self.setWindowTitle("Stream Auto Cutter")
        self.resize(1000, 700)
        self.setMinimumSize(800, 600)
        self.setAcceptDrops(True)

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
        self.tab_size = self._create_size_tab()
        self.tab_profiles = self._create_profiles_tab()
        
        self.tabs.addTab(self.tab_cut, "Нарезка")
        self.tabs.addTab(self.tab_io, "Интро/Аутро")
        self.tabs.addTab(self.tab_logo, "Логотип")
        self.tabs.addTab(self.tab_video, "Видео")
        self.tabs.addTab(self.tab_size, "Размер")
        self.tabs.addTab(self.tab_profiles, "Профили")
        
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
        main_layout.addLayout(bottom_layout)

        # Load settings to UI
        self._load_settings_to_ui()
        
        # Connect settings changes to save
        self._connect_ui_to_settings()

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
        
        self.chk_logo = QCheckBox("Включить логотип")
        layout.addWidget(self.chk_logo)
        
        h_type = QHBoxLayout()
        h_type.addWidget(QLabel("Тип логотипа:"))
        self.cb_logo_type = QComboBox()
        self.cb_logo_type.addItems(["Обычная картинка (PNG/JPG)", "Видео (Green Screen)"])
        h_type.addWidget(self.cb_logo_type)
        h_type.addStretch()
        layout.addLayout(h_type)
        
        h_path = QHBoxLayout()
        self.lbl_logo_path = QLabel("Путь не выбран")
        btn_logo_browse = QPushButton("Обзор...")
        btn_logo_browse.clicked.connect(self._browse_logo)
        h_path.addWidget(self.lbl_logo_path, stretch=1)
        h_path.addWidget(btn_logo_browse)
        layout.addLayout(h_path)
        
        # Position
        h_pos = QHBoxLayout()
        h_pos.addWidget(QLabel("Позиция:"))
        self.cb_logo_pos = QComboBox()
        self.cb_logo_pos.addItems(["top_left", "top_right", "bottom_left", "bottom_right"])
        h_pos.addWidget(self.cb_logo_pos)
        h_pos.addStretch()
        layout.addLayout(h_pos)
        
        # Size
        h_size = QHBoxLayout()
        h_size.addWidget(QLabel("Размер (%):"))
        self.slider_logo_size = QSlider(Qt.Orientation.Horizontal)
        self.slider_logo_size.setRange(5, 50)
        self.lbl_logo_size_val = QLabel("15%")
        self.slider_logo_size.valueChanged.connect(lambda v: self.lbl_logo_size_val.setText(f"{v}%"))
        h_size.addWidget(self.slider_logo_size)
        h_size.addWidget(self.lbl_logo_size_val)
        layout.addLayout(h_size)
        
        # Opacity
        h_op = QHBoxLayout()
        h_op.addWidget(QLabel("Прозрачность (%):"))
        self.slider_logo_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_logo_opacity.setRange(0, 100)
        self.lbl_logo_opacity_val = QLabel("80%")
        self.slider_logo_opacity.valueChanged.connect(lambda v: self.lbl_logo_opacity_val.setText(f"{v}%"))
        h_op.addWidget(self.slider_logo_opacity)
        h_op.addWidget(self.lbl_logo_opacity_val)
        layout.addLayout(h_op)
        
        # Display Time
        h_time = QHBoxLayout()
        h_time.addWidget(QLabel("Время показа:"))
        self.cb_logo_time = QComboBox()
        self.cb_logo_time.addItems(["full", "first_n", "last_n", "custom"])
        self.cb_logo_time.currentIndexChanged.connect(self._on_logo_time_changed)
        h_time.addWidget(self.cb_logo_time)
        layout.addLayout(h_time)
        
        self.w_logo_times = QWidget()
        lt = QHBoxLayout(self.w_logo_times)
        lt.setContentsMargins(0, 0, 0, 0)
        lt.addWidget(QLabel("От (сек):"))
        self.spin_logo_start = QSpinBox()
        self.spin_logo_start.setRange(0, 3600)
        lt.addWidget(self.spin_logo_start)
        lt.addWidget(QLabel("До (сек):"))
        self.spin_logo_end = QSpinBox()
        self.spin_logo_end.setRange(0, 3600)
        lt.addWidget(self.spin_logo_end)
        lt.addStretch()
        self.w_logo_times.setVisible(False)
        layout.addWidget(self.w_logo_times)
        
        layout.addStretch()
        return widget

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

    def _create_size_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        self.chk_size_limit = QCheckBox("Ограничить размер файла")
        self.chk_size_limit.toggled.connect(self._on_size_limit_toggled)
        layout.addWidget(self.chk_size_limit)
        
        h_size = QHBoxLayout()
        h_size.addWidget(QLabel("Желаемый размер:"))
        self.spin_size_mb = QSpinBox()
        self.spin_size_mb.setRange(10, 10000)
        self.spin_size_mb.setSuffix(" MB")
        h_size.addWidget(self.spin_size_mb)
        h_size.addStretch()
        layout.addLayout(h_size)
        
        h_audio = QHBoxLayout()
        h_audio.addWidget(QLabel("Битрейт аудио:"))
        self.spin_audio_kbps = QSpinBox()
        self.spin_audio_kbps.setRange(32, 320)
        self.spin_audio_kbps.setSuffix(" kbps")
        self.spin_audio_kbps.setValue(128)
        h_audio.addWidget(self.spin_audio_kbps)
        h_audio.addStretch()
        layout.addLayout(h_audio)
        
        layout.addStretch()
        return widget

    def _create_profiles_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        h_prof = QHBoxLayout()
        self.cb_profiles = QComboBox()
        self._update_profiles_list()
        h_prof.addWidget(self.cb_profiles, stretch=1)
        
        btn_load = QPushButton("Загрузить")
        btn_load.clicked.connect(self.action_load_profile)
        h_prof.addWidget(btn_load)
        layout.addLayout(h_prof)
        
        h_save = QHBoxLayout()
        btn_save = QPushButton("Сохранить как...")
        btn_save.clicked.connect(self.action_save_profile)
        h_save.addWidget(btn_save)
        
        btn_del = QPushButton("Удалить")
        btn_del.clicked.connect(self.action_delete_profile)
        h_save.addWidget(btn_del)
        h_save.addStretch()
        layout.addLayout(h_save)
        
        layout.addStretch()
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
        
        l_type = s.get("logo_type", "image")
        if l_type == "video_chromakey":
            self.cb_logo_type.setCurrentIndex(1)
        else:
            self.cb_logo_type.setCurrentIndex(0)
            
        self.lbl_logo_path.setText(s.get("logo_path", "Путь не выбран") or "Путь не выбран")
        self.cb_logo_pos.setCurrentText(s.get("logo_position", "top_right"))
        self.slider_logo_size.setValue(s.get("logo_size", 15))
        self.slider_logo_opacity.setValue(s.get("logo_opacity", 80))
        self.cb_logo_time.setCurrentText(s.get("logo_display", "full"))
        self.spin_logo_start.setValue(s.get("logo_time_start", 0))
        self.spin_logo_end.setValue(s.get("logo_time_end", 10))
        
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
            
        # Size
        self.chk_size_limit.setChecked(s.get("file_size_limit_enabled", True))
        self.spin_size_mb.setValue(s.get("file_size_limit_mb", 650))
        self.spin_audio_kbps.setValue(s.get("audio_bitrate", 128))

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
        s.set("logo_type", "video_chromakey" if self.cb_logo_type.currentIndex() == 1 else "image")
        s.set("logo_position", self.cb_logo_pos.currentText())
        s.set("logo_size", self.slider_logo_size.value())
        s.set("logo_opacity", self.slider_logo_opacity.value())
        s.set("logo_display", self.cb_logo_time.currentText())
        s.set("logo_time_start", self.spin_logo_start.value())
        s.set("logo_time_end", self.spin_logo_end.value())
        
        # Video
        s.set("resolution", self.cb_res.currentText())
        s.set("custom_resolution_w", self.spin_res_w.value())
        s.set("custom_resolution_h", self.spin_res_h.value())
        s.set("fps", self.cb_fps.currentText())
        s.set("codec", self.cb_codec.currentData())
        
        # Size
        s.set("file_size_limit_enabled", self.chk_size_limit.isChecked())
        s.set("file_size_limit_mb", self.spin_size_mb.value())
        s.set("audio_bitrate", self.spin_audio_kbps.value())

    def _connect_ui_to_settings(self):
        # Trigger save on any relevant change
        self.cb_duration.currentIndexChanged.connect(self._save_ui_to_settings)
        self.spin_duration.valueChanged.connect(self._save_ui_to_settings)
        
        self.chk_intro.toggled.connect(self._save_ui_to_settings)
        self.chk_outro.toggled.connect(self._save_ui_to_settings)
        
        self.chk_logo.toggled.connect(self._save_ui_to_settings)
        self.cb_logo_type.currentIndexChanged.connect(self._save_ui_to_settings)
        self.cb_logo_pos.currentIndexChanged.connect(self._save_ui_to_settings)
        self.slider_logo_size.valueChanged.connect(self._save_ui_to_settings)
        self.slider_logo_opacity.valueChanged.connect(self._save_ui_to_settings)
        self.cb_logo_time.currentIndexChanged.connect(self._save_ui_to_settings)
        self.spin_logo_start.valueChanged.connect(self._save_ui_to_settings)
        self.spin_logo_end.valueChanged.connect(self._save_ui_to_settings)
        
        self.cb_res.currentIndexChanged.connect(self._save_ui_to_settings)
        self.spin_res_w.valueChanged.connect(self._save_ui_to_settings)
        self.spin_res_h.valueChanged.connect(self._save_ui_to_settings)
        self.cb_fps.currentIndexChanged.connect(self._save_ui_to_settings)
        self.cb_codec.currentIndexChanged.connect(self._save_ui_to_settings)
        
        self.chk_size_limit.toggled.connect(self._save_ui_to_settings)
        self.spin_size_mb.valueChanged.connect(self._save_ui_to_settings)
        self.spin_audio_kbps.valueChanged.connect(self._save_ui_to_settings)

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
        
    def _on_size_limit_toggled(self, checked: bool):
        self.spin_size_mb.setEnabled(checked)
        
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

    def _update_profiles_list(self):
        curr = self.cb_profiles.currentText()
        self.cb_profiles.clear()
        self.cb_profiles.addItems(self.profiles.get_all_names())
        idx = self.cb_profiles.findText(curr)
        if idx >= 0:
            self.cb_profiles.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    # Profile Actions
    # ------------------------------------------------------------------
    
    def action_load_profile(self):
        name = self.cb_profiles.currentText()
        if not name: return
        data = self.profiles.get_profile(name)
        if data:
            self.settings.update(data)
            self._load_settings_to_ui()
            self._log_message(f"Профиль '{name}' загружен.")
            
    def action_save_profile(self):
        from PySide6.QtWidgets import QInputDialog
        self._save_ui_to_settings()
        name, ok = QInputDialog.getText(self, "Сохранить профиль", "Имя профиля:")
        if ok and name:
            if self.profiles.is_builtin(name):
                QMessageBox.warning(self, "Ошибка", "Нельзя перезаписать встроенный профиль.")
                return
            self.profiles.save_profile(name, self.settings.get_all())
            self._update_profiles_list()
            self.cb_profiles.setCurrentText(name)
            self._log_message(f"Профиль '{name}' сохранен.")
            
    def action_delete_profile(self):
        name = self.cb_profiles.currentText()
        if not name: return
        if self.profiles.is_builtin(name):
            QMessageBox.warning(self, "Ошибка", "Нельзя удалить встроенный профиль.")
            return
        
        res = QMessageBox.question(self, "Удаление", f"Удалить профиль '{name}'?")
        if res == QMessageBox.StandardButton.Yes:
            self.profiles.delete_profile(name)
            self._update_profiles_list()
            self._log_message(f"Профиль '{name}' удален.")

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
        self._log_message("Обработка всей очереди завершена.")
        
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
