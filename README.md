簡單的小工具，不需要另外下載影音剪輯軟體即可直接倒轉影片  
合併功能：可直接把倒轉後的片段串接起來  
應用場合：製作首尾幀不間斷的動態背景等等  
可直接使用 python 執行，也可下載 [exe](https://drive.google.com/file/d/1XHepGLBagBd83jGxiEf0-jvElWcpCOm-/view?usp=drive_link) 檔案  
exe 檔案可能會有系統警告跳出  

不建議使用超過30秒的影片，一般動態背景也不會到那麼長，如需倒轉長片的話還是建議使用剪輯軟體效率更好  
目前有GPU加速，但本身沒有AMD跟INTEL卡可以測試，如果崩潰請告知  


新增 PRO 版本：  
可以選擇幀數調整所需要的部分 [exe](https://drive.google.com/file/d/1k_4-fNjlU_9wKxdwr6xGweKdLddPHQru/view?usp=drive_link)

---

## 安裝說明

### Python 環境安裝

如果您想從原始碼執行，請先安裝 Python 3.8+ 然後安裝所需套件：

```bash
pip install -r requirements.txt
```

### 手動安裝套件

如果 requirements.txt 無法正常安裝，可以手動安裝：

```bash
pip install PySide6>=6.5.0
pip install moviepy>=1.0.3
pip install imageio-ffmpeg>=0.4.7
pip install proglog>=0.1.10
pip install opencv-python>=4.7.0
pip install numpy>=1.21.0
```

### 執行程式

安裝完成後，可以執行以下命令啟動程式：

**標準版：**
```bash
python Vi-REW.py
```

**Pro 版本：**
```bash
python Vi-REW-Pro.py
```

### 注意事項

- 建議使用虛擬環境 (venv) 來避免套件衝突
- Pro 版本需要額外安裝 OpenCV 來支援影片預覽功能
- 如果遇到 FFmpeg 相關錯誤，請確保系統已安裝相關編碼器
