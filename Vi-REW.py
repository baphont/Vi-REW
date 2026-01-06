import sys
import os
import time
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QFrame,
    QHBoxLayout, QVBoxLayout, QPushButton, QCheckBox, 
    QFileDialog, QStyle, QMessageBox, QProgressBar
)
from PySide6.QtCore import Qt, QThread, QObject, Signal, Slot
from PySide6.QtGui import QColor, QIcon

# --- 導入 MoviePy 與 Proglog ---
from moviepy import VideoFileClip, concatenate_videoclips
from moviepy import vfx
from proglog import ProgressBarLogger 

# --- [UI Logger] ---
class QtLogger(ProgressBarLogger):
    def __init__(self, progress_signal, message_signal):
        super().__init__(init_state=None, bars=None, ignored_bars=None, logged_bars='all', min_time_interval=0, ignore_bars_under=0)
        self.progress_signal = progress_signal 
        self.message_signal = message_signal   

    def callback(self, **changes):
        if 'message' in changes:
            msg = changes['message']
            # print(f"[系統訊息] {msg}") # Debug用，打包時可註解
            self.message_signal.emit(msg)

    def bars_callback(self, bar, attr, value, old_value=None):
        if bar in ['t', 'index', 'frame_index']:
            total = self.bars[bar]['total']
            if total > 0:
                percentage = int((value / total) * 100)
                # sys.stdout.write(f"\r[進度] {percentage}%") # Debug用
                # sys.stdout.flush()
                self.progress_signal.emit(percentage)

# --- 影片處理核心 (高畫質 + 防卡死) ---
class VideoReverseWorker(QObject):
    finished = Signal(str)      
    error = Signal(str)         
    progress_msg = Signal(str)  
    progress_val = Signal(int)  

    def __init__(self, file_path, is_boomerang):
        super().__init__()
        self.file_path = file_path
        self.is_boomerang = is_boomerang

    @Slot()
    def run(self):
        temp_reversed_path = None
        original_clip = None
        reversed_clip = None
        final_clip = None
        temp_audio_name = "temp-audio.m4a"

        # [設定] 高畫質參數 (CRF 18 = 視覺無損)
        # 如果覺得檔案太大，可以改回 23 (預設)
        # 如果想要完全無損 (檔案巨大)，可以改 0
        hq_params = ['-crf', '18'] 

        try:
            self.progress_msg.emit("正在載入影片...")
            self.progress_val.emit(0)
            
            original_clip = VideoFileClip(self.file_path)
            
            # 安全修剪
            if original_clip.duration > 0.1:
                new_duration = original_clip.duration - 0.05
                original_clip = original_clip.with_section_cut_out(new_duration, original_clip.duration)
            
            self.progress_msg.emit("正在計算倒轉特效...")
            reversed_clip = original_clip.with_effects([vfx.TimeMirror()])

            base_name = os.path.splitext(self.file_path)[0]
            my_logger = QtLogger(self.progress_val, self.progress_msg)

            if self.is_boomerang:
                self.progress_msg.emit("正在生成倒轉暫存檔 (高畫質)...")
                temp_reversed_path = base_name + "_temp_rev.mp4"
                
                # 寫入暫存檔 (也要用高畫質，不然畫質會先爛一次)
                reversed_clip.write_videofile(
                    temp_reversed_path, 
                    codec="libx264", 
                    audio_codec="aac",
                    temp_audiofile=temp_audio_name,
                    remove_temp=True,
                    threads=4,
                    preset="medium",   
                    ffmpeg_params=hq_params,  # <--- 加入高畫質參數
                    logger=my_logger
                )
                
                rev_clip_disk = VideoFileClip(temp_reversed_path)
                
                self.progress_msg.emit("正在合併影片 (Boomerang)...")
                final_clip = concatenate_videoclips([original_clip, rev_clip_disk])
                
                output_path = base_name + "_boomerang.mp4"
                
                # 輸出最終檔
                final_clip.write_videofile(
                    output_path, 
                    codec="libx264", 
                    audio_codec="aac", 
                    temp_audiofile=temp_audio_name,
                    remove_temp=True,
                    threads=4,
                    ffmpeg_params=hq_params, # <--- 加入高畫質參數
                    logger=my_logger
                )
                
                rev_clip_disk.close()
                
            else:
                output_path = base_name + "_REW.mp4"
                self.progress_msg.emit("正在輸出倒轉影片 (高畫質)...")
                
                reversed_clip.write_videofile(
                    output_path, 
                    codec="libx264", 
                    audio_codec="aac", 
                    temp_audiofile=temp_audio_name,
                    remove_temp=True,
                    threads=4,
                    ffmpeg_params=hq_params, # <--- 加入高畫質參數
                    logger=my_logger
                )

            # 資源清理
            if original_clip: original_clip.close()
            if reversed_clip: reversed_clip.close()
            if final_clip: final_clip.close()

            if temp_reversed_path and os.path.exists(temp_reversed_path):
                try: os.remove(temp_reversed_path)
                except: pass

            self.progress_val.emit(100)
            self.finished.emit(output_path)

        except Exception as e:
            self.error.emit(f"處理失敗: {str(e)}")
            
        finally:
            try:
                if original_clip: original_clip.close()
            except: pass

# --- UI (保持不變) ---
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.setWindowTitle("Vi-REW 1.0 (High Quality)")
        self.setGeometry(100, 100, 600, 480)
        self.setAcceptDrops(True)
        self.thread = None
        self.worker = None
        self.current_file_path = None
        self.setup_ui()

    def setup_ui(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{ background-color: #1E1E1E; color: #CCCCCC; font-family: "Segoe UI", sans-serif; }}
            QFrame {{ border: none; }}
            QPushButton {{ background-color: #3C3C3C; border: 1px solid #505050; padding: 8px 16px; border-radius: 4px; color: #FFFFFF; font-size: 14px; }}
            QPushButton:hover {{ background-color: #505050; }}
            QPushButton:pressed {{ background-color: #252526; }}
            QPushButton#ActionBtn {{ background-color: #2E7D32; border: 1px solid #1B5E20; font-weight: bold; }}
            QPushButton#ActionBtn:hover {{ background-color: #388E3C; }}
            QCheckBox {{ color: #CCCCCC; font-size: 14px; spacing: 8px; }}
            QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 4px; border: 1px solid #666; background: #252526; }}
            QCheckBox::indicator:checked {{ background-color: #4CAF50; border: 1px solid #4CAF50; }}
            QProgressBar {{ border: 1px solid #3E3E42; border-radius: 4px; background-color: #252526; text-align: center; color: #FFFFFF; }}
            QProgressBar::chunk {{ background-color: #4CAF50; border-radius: 3px; }}
            QLabel a {{ color: #4CAF50; text-decoration: none; }}
        """)
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(15)

        top_bar_label = QLabel()
        top_bar_label.setTextFormat(Qt.TextFormat.RichText)
        top_bar_label.setOpenExternalLinks(True)
        top_bar_label.setText('<a href="https://linktr.ee/tori.kira" style="color: #4CAF50; text-decoration: none; font-weight:bold;">https://linktr.ee/tori.kira</a>')
        top_bar_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        main_layout.addWidget(top_bar_label)

        self.info_panel = QFrame()
        self.info_panel.setStyleSheet("background-color: #252526; border: 1px solid #3E3E42; border-radius: 8px;")
        info_layout = QVBoxLayout(self.info_panel)
        info_layout.setContentsMargins(0, 40, 0, 40)
        self.file_label = QLabel("拖曳影片檔案至此\n或點擊下方按鈕選擇")
        self.file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_label.setStyleSheet("color: #888; font-size: 16px;")
        info_layout.addWidget(self.file_label)
        main_layout.addWidget(self.info_panel, 1)

        options_layout = QHBoxLayout()
        self.boomerang_check = QCheckBox("串接原檔 (Boomerang 效果)")
        self.boomerang_check.setChecked(False) 
        options_layout.addWidget(self.boomerang_check)
        options_layout.addStretch()
        main_layout.addLayout(options_layout)

        btn_layout = QHBoxLayout()
        self.select_btn = QPushButton("選擇檔案")
        self.select_btn.clicked.connect(self.select_file)
        btn_layout.addWidget(self.select_btn)
        self.start_btn = QPushButton("開始倒轉")
        self.start_btn.setObjectName("ActionBtn")
        self.start_btn.clicked.connect(self.start_processing)
        self.start_btn.setEnabled(False)
        btn_layout.addWidget(self.start_btn)
        main_layout.addLayout(btn_layout)

        self.status_label = QLabel("準備就緒")
        self.status_label.setStyleSheet("color: #AAA; margin-top: 5px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setTextVisible(False)
        main_layout.addWidget(self.progress_bar)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls(): event.acceptProposedAction()
    def dropEvent(self, event):
        if urls := event.mimeData().urls(): self.load_file(urls[0].toLocalFile())
    def select_file(self):
        if file_path := QFileDialog.getOpenFileName(self, "選擇影片", "", "Video Files (*.mp4 *.mov *.avi *.mkv)")[0]: self.load_file(file_path)
    def load_file(self, file_path):
        if not file_path.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
            self.status_label.setText("錯誤：請選擇有效的影片檔案"); return
        self.current_file_path = file_path
        self.file_label.setText(f"已選擇：\n{os.path.basename(file_path)}")
        self.file_label.setStyleSheet("color: #4CAF50; font-size: 18px; font-weight: bold;")
        self.start_btn.setEnabled(True)
        self.status_label.setText("等待開始...")
        self.progress_bar.setValue(0)
    def start_processing(self):
        if not self.current_file_path: return
        self.start_btn.setEnabled(False); self.select_btn.setEnabled(False); self.boomerang_check.setEnabled(False)
        self.file_label.setStyleSheet("color: #FFC107; font-size: 18px; font-weight: bold;")
        self.thread = QThread()
        self.worker = VideoReverseWorker(self.current_file_path, self.boomerang_check.isChecked())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress_msg.connect(self.update_status)
        self.worker.progress_val.connect(self.update_progress)
        self.worker.finished.connect(self.on_finished)
        self.worker.error.connect(self.on_error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    @Slot(str)
    def update_status(self, msg): self.status_label.setText(msg)
    @Slot(int)
    def update_progress(self, val): self.progress_bar.setValue(val)
    @Slot(str)
    def on_finished(self, output_path):
        self.reset_ui(); self.progress_bar.setValue(100)
        self.file_label.setText(f"完成！\n已儲存為：{os.path.basename(output_path)}")
        self.file_label.setStyleSheet("color: #4CAF50; font-size: 18px; font-weight: bold;")
        self.status_label.setText("處理完成")
        QMessageBox.information(self, "成功", f"影片處理完成！\n儲存位置：{output_path}")
    @Slot(str)
    def on_error(self, error_msg):
        self.reset_ui()
        self.file_label.setText("發生錯誤")
        self.file_label.setStyleSheet("color: #F44336; font-size: 18px; font-weight: bold;")
        self.status_label.setText("錯誤")
        QMessageBox.critical(self, "錯誤", f"處理時發生錯誤：\n{error_msg}")
    def reset_ui(self):
        self.start_btn.setEnabled(True); self.select_btn.setEnabled(True); self.boomerang_check.setEnabled(True)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion") 
    window = MainWindow()
    window.show()
    sys.exit(app.exec())