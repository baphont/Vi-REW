import sys
import os
import subprocess
import cv2
import numpy as np
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QFrame,
    QHBoxLayout, QVBoxLayout, QPushButton, QCheckBox, 
    QFileDialog, QStyle, QMessageBox, QProgressBar,
    QSlider, QGroupBox, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, QObject, Signal, Slot, QTimer, QSize
from PySide6.QtGui import QImage, QPixmap, QAction, QIcon, QKeySequence, QShortcut

# --- MoviePy 1.0.3 引用 ---
from moviepy.editor import VideoFileClip, concatenate_videoclips, vfx
import imageio_ffmpeg 
from proglog import ProgressBarLogger 

# --- [UI Logger] ---
class QtLogger(ProgressBarLogger):
    def __init__(self, progress_signal, message_signal):
        super().__init__(init_state=None, bars=None, ignored_bars=None, logged_bars='all', min_time_interval=0, ignore_bars_under=0)
        self.progress_signal = progress_signal 
        self.message_signal = message_signal   

    def callback(self, **changes):
        if 'message' in changes:
            self.message_signal.emit(changes['message'])

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar in ['t', 'index', 'frame_index']:
            total = self.bars[bar]['total']
            if total > 0:
                percentage = int((value / total) * 100)
                self.progress_signal.emit(percentage)

# --- 影片處理核心 ---
class VideoReverseWorker(QObject):
    finished = Signal(str)      
    error = Signal(str)         
    progress_msg = Signal(str)  
    progress_val = Signal(int)  

    def __init__(self, file_path, is_boomerang, start_frame, end_frame, fps):
        super().__init__()
        self.file_path = file_path
        self.is_boomerang = is_boomerang
        self.start_frame = start_frame
        self.end_frame = end_frame
        self.fps = fps

    def detect_hardware_encoder(self, ffmpeg_path):
        if not ffmpeg_path: return None
        try:
            result = subprocess.run([ffmpeg_path, "-encoders"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output = result.stdout
            if "h264_nvenc" in output: return "nvidia"
            elif "h264_amf" in output: return "amd"
            elif "h264_qsv" in output: return "intel"
        except Exception:
            return None
        return None

    @Slot()
    def run(self):
        temp_reversed_path = None
        original_clip = None
        trimmed_clip = None
        reversed_clip = None
        final_clip = None
        temp_audio_name = "temp-audio.m4a"

        try:
            self.progress_msg.emit("初始化處理引擎...")
            self.progress_val.emit(0)

            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
            os.environ["FFMPEG_BINARY"] = ffmpeg_path
            
            cpu_cores = os.cpu_count() or 4
            gpu_type = self.detect_hardware_encoder(ffmpeg_path)
            
            target_codec = "libx264"
            target_preset = "ultrafast"
            target_params = ['-crf', '18', '-pix_fmt', 'yuv420p']

            if gpu_type == "nvidia":
                self.progress_msg.emit("使用 NVIDIA 硬體加速")
                target_codec = "h264_nvenc"
                target_preset = "p1"
                target_params = ['-rc', 'constqp', '-qp', '18', '-zerolatency', '1', '-pix_fmt', 'yuv420p']
            elif gpu_type == "amd":
                self.progress_msg.emit("使用 AMD 硬體加速")
                target_codec = "h264_amf"
                target_preset = "speed"
                target_params = ['-rc', 'cqp', '-qp_p', '18', '-qp_i', '18', '-usage', 'ultralowlatency', '-pix_fmt', 'yuv420p']
            elif gpu_type == "intel":
                self.progress_msg.emit("使用 Intel QSV 硬體加速")
                target_codec = "h264_qsv"
                target_preset = "veryfast"
                target_params = ['-global_quality', '18', '-pix_fmt', 'yuv420p']

            self.progress_msg.emit("讀取原始影片...")
            original_clip = VideoFileClip(self.file_path)
            
            # 轉換幀數為秒數
            s_time = self.start_frame / self.fps
            e_time = self.end_frame / self.fps
            
            if e_time > original_clip.duration: e_time = original_clip.duration
            if s_time < 0: s_time = 0
            
            if s_time > 0 or e_time < original_clip.duration:
                self.progress_msg.emit(f"裁切: {s_time:.2f}s - {e_time:.2f}s")
                trimmed_clip = original_clip.subclip(s_time, e_time)
            else:
                trimmed_clip = original_clip

            self.progress_msg.emit("計算倒轉...")
            reversed_clip = trimmed_clip.fx(vfx.time_mirror)

            base_name = os.path.splitext(self.file_path)[0]
            my_logger = QtLogger(self.progress_val, self.progress_msg)

            def write_clip(clip, path):
                clip.write_videofile(
                    path, codec=target_codec, audio_codec="aac",
                    temp_audiofile=temp_audio_name, remove_temp=True,
                    threads=cpu_cores, preset=target_preset,
                    ffmpeg_params=target_params, logger=my_logger
                )

            if self.is_boomerang:
                self.progress_msg.emit("生成暫存檔...")
                temp_reversed_path = base_name + "_temp_rev.mp4"
                write_clip(reversed_clip, temp_reversed_path)
                
                rev_clip_disk = VideoFileClip(temp_reversed_path)
                self.progress_msg.emit("合併影片...")
                final_clip = concatenate_videoclips([trimmed_clip, rev_clip_disk])
                
                output_path = base_name + "_boomerang.mp4"
                write_clip(final_clip, output_path)
                rev_clip_disk.close()
            else:
                output_path = base_name + "_REW.mp4"
                self.progress_msg.emit("輸出影片...")
                write_clip(reversed_clip, output_path)

            if original_clip: original_clip.close()
            if trimmed_clip and trimmed_clip != original_clip: trimmed_clip.close()
            if reversed_clip: reversed_clip.close()
            if final_clip: final_clip.close()
            if temp_reversed_path and os.path.exists(temp_reversed_path):
                try: os.remove(temp_reversed_path)
                except: pass

            self.progress_val.emit(100)
            self.finished.emit(output_path)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(f"錯誤: {str(e)}")
        finally:
            try:
                if original_clip: original_clip.close()
            except: pass

# --- UI 部分 ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.setWindowTitle("Vi-REW Pro")
        self.setGeometry(100, 100, 700, 800)
        self.setAcceptDrops(True)
        
        # 影片變數
        self.cap = None 
        self.total_frames = 0
        self.fps = 30.0
        self.current_frame_idx = 0
        self.start_frame = 0
        self.end_frame = 0
        
        # 播放控制
        self.is_playing = False
        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self.next_frame_slot)
        
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background-color: #1E1E1E; color: #CCCCCC; font-family: "Segoe UI", sans-serif; }}
            QGroupBox {{ border: 1px solid #3E3E42; border-radius: 6px; margin-top: 12px; font-weight: bold; padding-top: 10px; }}
            QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; padding: 0 5px; color: #4CAF50; }}
            QPushButton {{ background-color: #3C3C3C; border: 1px solid #505050; padding: 6px; border-radius: 4px; color: white; }}
            QPushButton:hover {{ background-color: #505050; }}
            QPushButton:pressed {{ background-color: #252526; }}
            QPushButton#ActionBtn {{ background-color: #2E7D32; border: 1px solid #1B5E20; font-weight: bold; font-size: 14px; padding: 10px; }}
            QPushButton#ActionBtn:hover {{ background-color: #388E3C; }}
            QPushButton#TrimBtn {{ background-color: #0078D4; border: 1px solid #005A9E; }}
            QPushButton#TrimBtn:hover {{ background-color: #106EBE; }}
            QPushButton#PlayBtn {{ background-color: #D83B01; border: 1px solid #A80000; padding: 5px 15px; }}
            QPushButton#PlayBtn:hover {{ background-color: #EA4C19; }}
            QSlider::groove:horizontal {{ border: 1px solid #3E3E42; height: 8px; background: #252526; margin: 2px 0; border-radius: 4px; }}
            QSlider::handle:horizontal {{ background: #4CAF50; border: 1px solid #4CAF50; width: 18px; height: 18px; margin: -7px 0; border-radius: 9px; }}
            QLabel#TimeCode {{ font-family: "Consolas", monospace; font-size: 14px; font-weight: bold; color: #FFF; }}
            QProgressBar {{ border: 1px solid #3E3E42; border-radius: 4px; text-align: center; color: white; }}
            QProgressBar::chunk {{ background-color: #4CAF50; }}
        """)
        
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(10)

        # 1. 預覽視窗
        self.preview_label = QLabel("請拖曳影片至此載入")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet("background-color: #000; border: 1px solid #333; color: #666; font-size: 18px;")
        self.preview_label.setMinimumHeight(360)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.preview_label)

        # 2. 控制面板
        control_panel = QFrame()
        control_panel.setStyleSheet("background-color: #252526; border-radius: 8px;")
        cp_layout = QVBoxLayout(control_panel)
        
        # 資訊列
        info_layout = QHBoxLayout()
        self.time_label = QLabel("00:00:00")
        self.time_label.setObjectName("TimeCode")
        self.frame_label = QLabel("Frame: 0 / 0")
        self.frame_label.setObjectName("TimeCode")
        info_layout.addWidget(self.time_label)
        info_layout.addStretch()
        info_layout.addWidget(self.frame_label)
        cp_layout.addLayout(info_layout)

        # 滑桿
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setEnabled(False)
        self.slider.valueChanged.connect(self.on_slider_move) # 修改連接函數以避免播放衝突
        cp_layout.addWidget(self.slider)
        
        # 按鈕區 (播放控制 + 剪輯)
        btn_area_layout = QHBoxLayout()
        
        # 播放按鈕
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("PlayBtn")
        self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.play_btn.setToolTip("播放/暫停 (Space)")
        self.play_btn.clicked.connect(self.toggle_playback)
        self.play_btn.setEnabled(False)
        
        # 空白鍵快捷鍵
        self.shortcut_space = QShortcut(QKeySequence("Space"), self)
        self.shortcut_space.activated.connect(self.toggle_playback)

        # 逐幀
        self.btn_prev = QPushButton("<")
        self.btn_prev.clicked.connect(lambda: self.step_frame(-1))
        self.btn_next = QPushButton(">")
        self.btn_next.clicked.connect(lambda: self.step_frame(1))

        # 設定點
        self.btn_set_in = QPushButton("[ 設定起點")
        self.btn_set_in.setObjectName("TrimBtn")
        self.btn_set_in.clicked.connect(self.set_in_point)
        self.btn_set_out = QPushButton("設定終點 ]")
        self.btn_set_out.setObjectName("TrimBtn")
        self.btn_set_out.clicked.connect(self.set_out_point)

        # 佈局
        btn_area_layout.addWidget(self.play_btn)
        btn_area_layout.addSpacing(10)
        btn_area_layout.addWidget(self.btn_prev)
        btn_area_layout.addWidget(self.btn_next)
        btn_area_layout.addSpacing(20)
        btn_area_layout.addWidget(self.btn_set_in)
        btn_area_layout.addWidget(self.btn_set_out)
        btn_area_layout.addStretch()
        
        cp_layout.addLayout(btn_area_layout)
        layout.addWidget(control_panel)

        # 3. 範圍資訊
        range_group = QGroupBox("輸出與循環範圍")
        r_layout = QHBoxLayout(range_group)
        self.range_info = QLabel("尚未選擇範圍 (預設全片)")
        self.range_info.setStyleSheet("color: #4CAF50; font-weight: bold;")
        r_layout.addWidget(self.range_info)
        layout.addWidget(range_group)

        # 4. 輸出選項
        self.boomerang_check = QCheckBox("啟用 Boomerang 效果 (正向+倒轉)")
        layout.addWidget(self.boomerang_check)

        main_btn_layout = QHBoxLayout()
        self.select_btn = QPushButton("開啟檔案")
        self.select_btn.clicked.connect(self.select_file)
        main_btn_layout.addWidget(self.select_btn)
        
        self.start_btn = QPushButton("開始輸出")
        self.start_btn.setObjectName("ActionBtn")
        self.start_btn.clicked.connect(self.start_processing)
        self.start_btn.setEnabled(False)
        main_btn_layout.addWidget(self.start_btn)
        layout.addLayout(main_btn_layout)

        # 狀態
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        self.status_label = QLabel("準備就緒")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

    # --- 邏輯功能 ---
    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    
    def dropEvent(self, event):
        if urls := event.mimeData().urls(): self.load_video(urls[0].toLocalFile())
    
    def select_file(self):
        if path := QFileDialog.getOpenFileName(self, "選擇影片", "", "Video (*.mp4 *.mov *.avi *.mkv)")[0]:
            self.load_video(path)

    def load_video(self, path):
        if self.cap: self.cap.release()
        
        # 停止舊的播放
        if self.is_playing: self.toggle_playback()

        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            self.status_label.setText("無法開啟影片")
            return

        self.current_file_path = path
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30.0
        
        # UI 更新
        self.slider.blockSignals(True) # 防止觸發 seek
        self.slider.setRange(0, self.total_frames - 1)
        self.slider.setValue(0)
        self.slider.setEnabled(True)
        self.slider.blockSignals(False)
        
        self.start_btn.setEnabled(True)
        self.play_btn.setEnabled(True)
        
        # 重置剪輯點
        self.start_frame = 0
        self.end_frame = self.total_frames - 1
        self.current_frame_idx = 0
        self.update_range_label()
        
        self.seek_video(0)
        self.status_label.setText(f"已載入: {os.path.basename(path)}")

    def toggle_playback(self):
        if not self.cap: return
        
        if self.is_playing:
            self.play_timer.stop()
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.is_playing = False
        else:
            # 設定計時器間隔 (毫秒) = 1000 / FPS
            interval = int(1000 / self.fps)
            self.play_timer.start(interval)
            self.play_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self.is_playing = True

    def next_frame_slot(self):
        # 這是由 QTimer 觸發的
        next_idx = self.current_frame_idx + 1
        
        # 循環邏輯 Check
        limit_frame = self.end_frame
        
        if next_idx > limit_frame:
            # 如果超過終點，循環回到起點
            next_idx = self.start_frame
            # 或者是如果要單次播放停止，就呼叫 toggle_playback()
        
        if next_idx >= self.total_frames:
             # 安全邊界
             next_idx = self.start_frame

        self.slider.blockSignals(True)
        self.slider.setValue(next_idx)
        self.slider.blockSignals(False)
        self.seek_video(next_idx)

    def on_slider_move(self, val):
        # 當使用者拖曳時
        self.seek_video(val)

    def seek_video(self, frame_idx):
        if not self.cap: return
        self.current_frame_idx = frame_idx
        
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        
        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            
            scaled_pixmap = QPixmap.fromImage(q_img).scaled(
                self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.preview_label.setPixmap(scaled_pixmap)
            
            # 更新時間
            seconds = frame_idx / self.fps
            time_str = f"{int(seconds//3600):02}:{int((seconds%3600)//60):02}:{seconds%60:05.2f}"
            self.time_label.setText(time_str)
            self.frame_label.setText(f"Frame: {frame_idx} / {self.total_frames}")

    def step_frame(self, step):
        if not self.cap: return
        # 暫停播放如果使用者手動介入
        if self.is_playing: self.toggle_playback()
        
        new_val = self.slider.value() + step
        if 0 <= new_val < self.total_frames:
            self.slider.setValue(new_val) # 這會觸發 on_slider_move -> seek_video

    def set_in_point(self):
        if not self.cap: return
        self.start_frame = self.current_frame_idx
        if self.start_frame >= self.end_frame:
            self.end_frame = self.total_frames - 1 
        self.update_range_label()

    def set_out_point(self):
        if not self.cap: return
        if self.current_frame_idx <= self.start_frame:
            QMessageBox.warning(self, "錯誤", "終點必須大於起點")
            return
        self.end_frame = self.current_frame_idx
        self.update_range_label()

    def update_range_label(self):
        duration_frames = self.end_frame - self.start_frame
        duration_sec = duration_frames / self.fps
        self.range_info.setText(
            f"循環/輸出區間: {self.start_frame}f -> {self.end_frame}f (長度: {duration_sec:.2f}s)"
        )

    def start_processing(self):
        if self.is_playing: self.toggle_playback()
        
        self.lock_ui(True)
        self.thread = QThread()
        self.worker = VideoReverseWorker(
            self.current_file_path,
            self.boomerang_check.isChecked(),
            self.start_frame,
            self.end_frame,
            self.fps
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress_msg.connect(self.status_label.setText)
        self.worker.progress_val.connect(self.progress_bar.setValue)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    def lock_ui(self, locked):
        self.start_btn.setEnabled(not locked)
        self.select_btn.setEnabled(not locked)
        self.slider.setEnabled(not locked)
        self.play_btn.setEnabled(not locked)
        self.btn_set_in.setEnabled(not locked)
        self.btn_set_out.setEnabled(not locked)
        self.setAcceptDrops(not locked)

    @Slot(str)
    def on_finished(self, output_path):
        self.lock_ui(False)
        self.progress_bar.setValue(100)
        QMessageBox.information(self, "完成", f"影片處理成功！\n儲存於：{output_path}")
        self.status_label.setText("處理完成")

    @Slot(str)
    def on_error(self, err):
        self.lock_ui(False)
        QMessageBox.critical(self, "錯誤", err)
        self.status_label.setText("發生錯誤")
    
    def resizeEvent(self, event):
        if self.cap: self.seek_video(self.current_frame_idx)
        super().resizeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    w = MainWindow()
    w.show()
    sys.exit(app.exec())