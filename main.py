import sys
from pathlib import Path
from threading import Thread, Lock
from collections.abc import Callable
import numpy as np
import sounddevice as sd
import soundfile as sf
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QHBoxLayout,
    QFrame,
)
from PySide6.QtCore import Qt, QObject, Signal, QTimer

APP_STYLE = """
QMainWindow { background-color: #1E1E1E; }
QLabel { color: #E0E0E0; font-size: 14px; }
QScrollArea { border: none; }
QSlider::groove:horizontal { height: 6px; background: #333333; border-radius: 3px; }
QSlider::handle:horizontal { width: 14px; margin: -4px 0; background: deeppink; border-radius: 7px; }
QPushButton { background-color: deeppink; color: black; border: none; border-radius: 8px; font-size: 13px; padding: 5px 12px; }
QPushButton:hover { background-color: #ff77cc; }
QPushButton:pressed { background-color: #ff55aa; }
QFrame#sectionFrame { background-color: #2A2A2A; border-radius: 8px; padding: 6px; }
"""

MUSIC_DIR = Path.home() / "Music"
EXTENSIONS = {".wav", ".mp3", ".flac"}


class UiSignalBridge(QObject):
    refresh_requested = Signal()


class MusicWatcher(FileSystemEventHandler):
    def __init__(self, ui_signals: UiSignalBridge):
        super().__init__()
        self.ui_signals = ui_signals

    def on_any_event(self, event):
        self.ui_signals.refresh_requested.emit()


class TrackPlayer:
    def __init__(self, path: Path):
        self.sf = sf.SoundFile(str(path))
        self.samplerate = self.sf.samplerate
        self.channels = self.sf.channels
        self.stream = None
        self.lock = Lock()
        self.volume = 1.0
        self.paused = False
        self.current_frame = 0
        self.finished_callback: Callable[[], None] | None = None  # Type hint

    def callback(self, outdata, frames, time, status):
        if status:
            print(status)
        if self.paused:
            outdata.fill(0)
            return
        with self.lock:
            data = self.sf.read(frames, dtype="float32", always_2d=True)
            if len(data) < frames:
                outdata[: len(data)] = data * self.volume
                outdata[len(data) :].fill(0)
                if self.finished_callback:
                    Thread(target=self.finished_callback, daemon=True).start()
                raise sd.CallbackStop()
            else:
                outdata[:] = data * self.volume
            self.current_frame = self.sf.tell()

    def play(self):
        self.stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            blocksize=2048,
            callback=self.callback,
        )
        self.stream.start()

    def stop(self):
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.sf.seek(0)
        self.current_frame = 0

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def set_volume(self, value: int):
        with self.lock:
            self.volume = np.clip(value / 100, 0.0, 1.0)

    def seek(self, seconds: float):
        frame = int(seconds * self.samplerate)
        frame = np.clip(frame, 0, len(self.sf))
        with self.lock:
            self.sf.seek(frame)
            self.current_frame = self.sf.tell()


class Track:
    def __init__(self, path: Path):
        self.path = path
        self.player = TrackPlayer(path)
        with sf.SoundFile(str(path)) as f:
            self.duration_seconds = len(f) / f.samplerate

    def play(self):
        self.player.play()

    def stop(self):
        self.player.stop()

    def pause(self):
        self.player.pause()

    def resume(self):
        self.player.resume()

    def set_volume(self, value: int):
        self.player.set_volume(value)

    def seek(self, seconds: float):
        self.player.seek(seconds)

    def get_position(self):
        return self.player.current_frame / self.player.samplerate


class ClickableSlider(QSlider):
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = (
                event.position().x()
                if hasattr(event, "position")
                else event.x()
            )
            value = (
                self.minimum()
                + (self.maximum() - self.minimum()) * pos / self.width()
            )
            self.setValue(int(value))
            self.sliderMoved.emit(int(value))
        super().mousePressEvent(event)


class MusicPlayer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Music Player")
        self.resize(600, 800)
        self.setStyleSheet(APP_STYLE)

        self.current_track = None
        self.current_volume = 100
        self.user_seeking = False
        self.loop_mode = "none"  # default loop mode

        self.ui_signals = UiSignalBridge()
        self.ui_signals.refresh_requested.connect(self.refresh_ui)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setSpacing(12)

        # ── Song list
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll_layout.setSpacing(8)
        self.scroll_area.setWidget(self.scroll_content)
        main_layout.addWidget(self.scroll_area)

        # ── Playback controls frame
        playback_frame = QFrame()
        playback_frame.setObjectName("sectionFrame")
        playback_layout = QVBoxLayout(playback_frame)
        main_layout.addWidget(playback_frame)

        playback_layout.addWidget(QLabel("Playback"))
        self.progress_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setRange(0, 1000)
        self.progress_slider.setValue(0)
        self.progress_slider.setEnabled(False)
        self.progress_slider.sliderPressed.connect(self.start_seek)
        self.progress_slider.sliderReleased.connect(self.end_seek)
        self.progress_slider.sliderMoved.connect(self.seek_track)
        playback_layout.addWidget(self.progress_slider)

        self.time_label = QLabel("00:00 / 00:00")
        playback_layout.addWidget(self.time_label)

        # ── Loop controls
        loop_layout = QHBoxLayout()
        playback_layout.addLayout(loop_layout)

        self.loop_none_btn = QPushButton("Don't Loop")
        self.loop_list_btn = QPushButton("Loop List")
        self.loop_song_btn = QPushButton("Loop Song")
        for btn in [self.loop_none_btn, self.loop_list_btn, self.loop_song_btn]:
            loop_layout.addWidget(btn)

        self.loop_none_btn.clicked.connect(lambda: self.set_loop_mode("none"))
        self.loop_list_btn.clicked.connect(lambda: self.set_loop_mode("list"))
        self.loop_song_btn.clicked.connect(lambda: self.set_loop_mode("song"))

        # Apply default loop mode highlight
        self.set_loop_mode("none")

        # ── Volume controls frame
        volume_frame = QFrame()
        volume_frame.setObjectName("sectionFrame")
        volume_layout = QHBoxLayout(volume_frame)
        main_layout.addWidget(volume_frame)

        volume_label = QLabel("Volume:")
        volume_layout.addWidget(volume_label)

        self.volume_slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.current_volume)
        self.volume_slider.valueChanged.connect(self.on_volume_change)
        volume_layout.addWidget(self.volume_slider)

        self.volume_percent_label = QLabel(f"{self.current_volume}%")
        volume_layout.addWidget(self.volume_percent_label)

        self.track_rows = {}
        self.play_buttons = {}
        self.track_list = []

        # ── File watcher
        self.watcher = Observer()
        self.event_handler = MusicWatcher(self.ui_signals)
        self.watcher.schedule(
            self.event_handler, str(MUSIC_DIR), recursive=True
        )
        self.watcher.start()

        # ── Timer for progress updates
        self.timer = QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.update_progress)
        self.timer.start()

        self.refresh_ui()

    # ── Loop Mode
    def set_loop_mode(self, mode):
        self.loop_mode = mode
        active_style = "background-color: #bb0066;"  # slightly darker pink
        inactive_style = "background-color: deeppink;"

        self.loop_none_btn.setStyleSheet(
            active_style if mode == "none" else inactive_style
        )
        self.loop_list_btn.setStyleSheet(
            active_style if mode == "list" else inactive_style
        )
        self.loop_song_btn.setStyleSheet(
            active_style if mode == "song" else inactive_style
        )

    # ── Music scan
    def scan_music(self):
        return [
            p
            for p in MUSIC_DIR.rglob("*")
            if p.is_file() and p.suffix.lower() in EXTENSIONS
        ]

    def refresh_ui(self):
        self.track_list = self.scan_music()
        for i in reversed(range(self.scroll_layout.count())):
            w = self.scroll_layout.itemAt(i).widget()
            if w:
                w.setParent(None)
        self.track_rows.clear()
        self.play_buttons.clear()
        for path in self.track_list:
            self.add_song_row(path)

    def add_song_row(self, path: Path):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setSpacing(12)

        title = QLabel(path.stem)
        title.setFixedWidth(320)
        layout.addWidget(title)

        try:
            with sf.SoundFile(str(path)) as f:
                duration = len(f) / f.samplerate
                minutes = int(duration // 60)
                seconds = int(duration % 60)
                time_label = QLabel(f"{minutes}:{seconds:02}")
        except Exception:
            time_label = QLabel("--:--")
        layout.addWidget(time_label)

        play_btn = QPushButton("▶")
        play_btn.setFixedSize(48, 32)
        layout.addWidget(play_btn)

        self.scroll_layout.addWidget(row)
        self.track_rows[path] = row
        self.play_buttons[path] = play_btn

        def toggle_play(_=None, p=path):
            if self.current_track and self.current_track.path == p:
                if self.current_track.player.paused:
                    self.current_track.resume()
                    self.update_play_buttons(p)
                else:
                    self.current_track.pause()
                    self.update_play_buttons(None)
            else:
                self.play_track(p)

        play_btn.clicked.connect(toggle_play)

    def update_play_buttons(self, active_path: Path | None):
        for path, btn in self.play_buttons.items():
            btn.setText("⏸" if path == active_path else "▶")

    def highlight_track(self, path: Path):
        for p, w in self.track_rows.items():
            w.setStyleSheet("")
        if path in self.track_rows:
            self.track_rows[path].setStyleSheet(
                "background-color: #333333; border-radius: 5px;"
            )
        self.update_play_buttons(path)

    def play_track(self, path: Path):
        if self.current_track:
            self.current_track.stop()
            self.current_track = None
            self.progress_slider.setValue(0)
            self.time_label.setText("00:00 / 00:00")
        try:
            track = Track(path)
            track.set_volume(self.current_volume)

            def on_finished():
                self.on_track_finished(path)

            track.player.finished_callback = on_finished
            Thread(target=track.play, daemon=True).start()
            self.current_track = track
            self.progress_slider.setEnabled(True)
            self.highlight_track(path)
        except Exception as e:
            print(f"Failed to play {path.name}: {e}")

    def on_track_finished(self, path: Path):
        if self.loop_mode == "song":
            self.play_track(path)
        elif self.loop_mode == "list":
            try:
                idx = self.track_list.index(path)
                next_idx = (idx + 1) % len(self.track_list)
                self.play_track(self.track_list[next_idx])
            except ValueError:
                pass
        else:
            self.current_track = None
            self.progress_slider.setValue(0)
            self.time_label.setText("00:00 / 00:00")
            self.update_play_buttons(None)

    def on_volume_change(self, value: int):
        self.current_volume = value
        self.volume_percent_label.setText(f"{value}%")
        if self.current_track:
            self.current_track.set_volume(value)

    def update_progress(self):
        if self.current_track and not self.user_seeking:
            pos_sec = self.current_track.get_position()
            duration_sec = self.current_track.duration_seconds
            slider_value = int(pos_sec / duration_sec * 1000)
            self.progress_slider.blockSignals(True)
            self.progress_slider.setValue(slider_value)
            self.progress_slider.blockSignals(False)

            cur_min = int(pos_sec // 60)
            cur_sec = int(pos_sec % 60)
            dur_min = int(duration_sec // 60)
            dur_sec = int(duration_sec % 60)
            self.time_label.setText(
                f"{cur_min}:{cur_sec:02} / {dur_min}:{dur_sec:02}"
            )

    def start_seek(self):
        self.user_seeking = True

    def end_seek(self):
        self.user_seeking = False
        self.seek_track(self.progress_slider.value())

    def seek_track(self, value=None):
        if self.current_track:
            if value is None:
                value = self.progress_slider.value()
            target_sec = value / 1000 * self.current_track.duration_seconds
            self.current_track.seek(target_sec)

    def closeEvent(self, event):
        if self.current_track:
            self.current_track.stop()
        self.watcher.stop()
        self.watcher.join()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = MusicPlayer()
    player.show()
    sys.exit(app.exec())
