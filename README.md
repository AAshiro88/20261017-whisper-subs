# Whisper 自動繁體中文字幕工具

YouTube / Bilibili 網址或本地影音檔，拖放即產生繁體中文 `.srt` 字幕。
輸出會做兩項後處理：簡體轉繁體（OpenCC `s2twp`）、中文字旁的標點轉為全形，並依字詞時間戳把過長段落切成好閱讀的短句。
本機實測環境：NVIDIA GeForce RTX 3050 8GB、Windows 11、Python 3.11.17（conda 環境 `whisper-subs`）。

## 快速開始

環境已於本機建立完成，可直接使用：

| 檔案 | 用途 |
|---|---|
| `setup_env.bat` | 建立 conda 環境與安裝套件（**只需執行一次**，已執行過） |
| `run_url.bat` | 拖放 YouTube / Bilibili **網址** |
| `run_file.bat` | 拖放本地**影片 / 音檔**（可一次拖多個） |
| `run_folder.bat` | 拖放**資料夾**批次處理；不帶參數執行則處理 `input\` 內所有媒體檔 |

字幕一律寫入 `output\`，檔名與來源同名（`.srt`）。

其他格式或參數請直接用命令列（範例見下方「進階用法」）。

## 目錄結構

```
20261017-whisper-subs\
├─ README.md
├─ config.json               模型、精度、語言、字幕長度等設定
├─ requirements.txt          主要直接依賴（含版本）
├─ requirements.lock.txt     完整解析版本（pip freeze）
├─ transcribe.py             核心 CLI
├─ setup_env.bat
├─ run_url.bat / run_file.bat / run_folder.bat
├─ input\                    yt-dlp 下載的暫存音檔（轉錄後自動刪除）
├─ output\                   產出的 .srt / .vtt / .txt
└─ models\                   faster-whisper 模型快取（首次執行自動下載 large-v3 約 3GB）
```

## 設定檔 `config.json`

| 欄位 | 預設值 | 說明 |
|---|---|---|
| `model` | `large-v3` | 品質優先。改成 `large-v3-turbo` 速度約快 2–4 倍、記憶體約減半 |
| `device` | `cuda` | 無顯示卡時自動降為 `cpu` |
| `compute_type` | `auto` | 依可用顯示記憶體自動選 `float16` / `int8_float16` / `int8` |
| `language` | `zh` | 語言代碼。`zh` 繁中、`ja` 日本語、`en` 英文；空字串為自動判斷 |
| `beam_size` | `5` | 解碼品質，數字越大越準也越慢 |
| `vad_filter` | `true` | 語音活動偵測，自動跳過靜音段，長影片速度提升明顯 |
| `initial_prompt` | 台灣華語提示 | 用來誘導模型輸出繁體中文與標點 |
| `refine_long_subtitles` | `true` | 依字詞時間戳把過長字幕切成好閱讀的短句 |
| `max_subtitle_chars` | `20` | 單則字幕字數上限（英文請調大到 60 左右） |
| `max_subtitle_seconds` | `6.0` | 單則字幕時間上限 |
| `output_formats` | `["srt"]` | 可加 `vtt`、`txt` |
| `opencc_config` | `s2twp` | 簡轉繁並套用台灣用語；想保留原文可設 `traditional_converter` 為 `none` |
| `cookies_from_browser` | 空字串 | Bilibili 高畫質或需登入的內容可填 `edge` 或 `chrome` |

## 進階用法

```bat
:: 輸出三種格式
run_file.bat 影片.mp4 --format srt,vtt,txt

:: 換較快的模型
run_file.bat 影片.mp4 --model large-v3-turbo

:: 指定輸出資料夾
run_file.bat 影片.mp4 --output-dir D:\字幕

:: 保留下載的音檔（不自動刪除）
run_url.bat https://www.youtube.com/watch?v=xxxx

:: 完全繞過 bat，直接呼叫
"C:\Users\ayore\.conda\envs\whisper-subs\python.exe" transcribe.py 影片.mp4 --format srt
```

## 本機實測數據

以 12.1 秒繁體中文語音、`large-v3` + `float16`、開啟 VAD 與字詞時間戳：

| 項目 | 實測值 |
|---|---|
| 顯卡記憶體峰值 | 約 6.2GB（其中桌面等背景約 2.0GB，模型與推論約 4.2GB） |
| 轉錄速度 | 約 6.3 倍速（12.1 秒音檔 1.9 秒完成） |
| 短檔準確度 | 逐字完全正確（以 Windows TTS 合成語音驗證） |

注意：短音檔的倍速會被模型載入與暖機時間拉低，長影片（數十分鐘以上）的實際倍速通常更高。
執行前建議關閉遊戲等佔用顯卡的程式，8GB 顯卡在 `large-v3` 下已接近上限。

## 已知限制

- **YouTube 反爬蟲**：YouTube 會調整驗證機制，偶爾會出現下載失敗。程式已自動啟用 `node` 作為 JavaScript 執行環境；若仍失敗，可更新 `yt-dlp`（`pip install -U yt-dlp`）或改用 Bilibili。
- **只有 ffmpeg、沒有 ffprobe**：`imageio-ffmpeg` 只附帶 `ffmpeg.exe`。本工具只下載純音軌（`bestaudio`），正常情況不需要 ffprobe；若某些來源需要合併音視訊才會失敗。
- **繁簡與台灣用語轉換**：模型輸出多為簡體，`s2twp` 會轉成繁體並套用台灣慣用詞，但偶爾會有不合語境的替換，正式使用前建議抽查。
- **字幕分段**：切分依賴模型給的字詞時間戳，無標點又講得很快的段落，切點可能落在字與字之間。
- **非逐字稿**：本工具輸出的是「以句為單位」的字幕，不是逐字對齊稿；短句、疊字、語速變化大的內容時間軸可能有 0.1–0.3 秒誤差。
- **版權**：字幕僅供個人使用，對外散布或商業使用須取得內容授權。

## 環境與套件版本

| 項目 | 版本 |
|---|---|
| conda 環境 | `whisper-subs`（Python 3.11.17） |
| faster-whisper | 1.2.1 |
| ctranslate2 | 4.8.3 |
| yt-dlp | 2026.8.19 |
| imageio-ffmpeg | 0.6.0 |
| opencc-python-reimplemented | 0.1.7 |
| 顯卡驅動 | 617.14（CUDA 12 runtime 由 ctranslate2 內附，**不需安裝 CUDA Toolkit**） |

重新建立環境：刪除 `models\` 快取後再次執行 `setup_env.bat` 即可。