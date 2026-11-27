# Whisper 自動繁體中文字幕與重點節錄工具

YouTube / Bilibili 網址或本地影音檔，拖放或選檔即產生繁體中文 `.srt` 字幕與 `.txt` 逐字文字，並可搭配本機或遠端 Ollama 自動產出 Markdown 重點節錄。
輸出會做兩項後處理：簡體轉繁體（OpenCC `s2twp`）、中文字旁的標點轉為全形，並依字詞時間戳把過長段落切成好閱讀的短句。
目前本機環境：Windows 11、Intel Core Ultra 5 228V（CPU `int8` 模式）、Python 3.11.18（conda 環境 `whisper-subs`）。

## 快速開始

環境已於本機建立完成，可直接使用。

### 用法一：視窗選檔並自動轉錄 + Ollama 重點節錄（推薦）

1. 雙擊 `run_summary.bat`
2. 在跳出的 Windows 檔案選擇視窗中，選取**單個或多個**影片／音檔（按 `Ctrl` 或 `Shift` 可多選）
3. 程式會先以本機 Whisper 轉錄（產出 `.srt` 與 `.txt`），再依 `config.json` 的 `summary` 設定呼叫本機或遠端 Ollama 產出 `_重點節錄.md`
4. 所有結果寫在 `output\`

也可直接將單個或多個影片／資料夾**拖放到** `run_summary.bat` 圖示上執行。

### 用法二：雙擊後貼網址（僅產出字幕）

1. 雙擊 `run_url.bat`
2. 出現 `>` 提示符後，從瀏覽器複製網址（Ctrl+C）貼上，按 Enter
3. 想一次處理多支影片就繼續貼，最後**按一次空白鍵的 Enter** 就會開始
4. 字幕寫在 `output\`

本機音檔換成雙擊 `run_file.bat`，貼上檔案路徑即可；雙擊 `run_folder.bat` 則會處理 `input\` 資料夾內的所有媒體檔。

### 用法三：拖放

從瀏覽器把網址**直接拖到** `run_url.bat` 圖示上，或把影片拖到 `run_file.bat` / `run_summary.bat` 上，可以一次拖多個。

### 用法四：命令列

```bat
run_summary.bat "D:\影片\教學1.mp4" "D:\影片\教學2.mp4"
run_url.bat "https://www.youtube.com/watch?v=xxxxxxxxxxx"
run_file.bat "D:\影片\教學.mp4" --format srt,vtt,txt
```

### 檔案用途

| 檔案 | 用途 |
|---|---|
| `setup_env.bat` | 建立 conda 環境與安裝套件（**只需執行一次**，已執行過） |
| `run_summary.bat` | 視窗選取單個或多個影音檔（或拖放），執行 Whisper 轉錄 + 本機／遠端 Ollama 重點節錄 |
| `run_url.bat` | YouTube / Bilibili 網址（雙擊貼上或拖放） |
| `run_file.bat` | 本地影片 / 音檔（雙擊貼上路徑或拖放） |
| `run_folder.bat` | 資料夾批次；雙擊時處理 `input\`，也可拖放資料夾 |

其他格式或參數請直接用命令列（範例見下方「進階用法」）。

## 目錄結構

```
20261017-whisper-subs\
├─ README.md
├─ .env                      遠端 Ollama 位址（OLLAMA_HOST=http://<host>:11434）
├─ config.json               Whisper 模型、精度、語言與 Ollama 節錄設定
├─ requirements.txt          主要直接依賴（含版本）
├─ requirements.lock.txt     完整解析版本（pip freeze）
├─ transcribe.py             語音轉錄核心 CLI
├─ summarize_videos.py       選檔轉錄 + 本機／遠端 Ollama 重點節錄 CLI
├─ setup_env.bat
├─ run_summary.bat
├─ run_url.bat / run_file.bat / run_folder.bat
├─ input\                    yt-dlp 下載的暫存音檔（轉錄後自動刪除）
├─ output\                   產出的 .srt / .vtt / .txt / _重點節錄.md
└─ models\                   faster-whisper 模型快取（首次執行自動下載）
```

## 設定檔 `config.json`

### Whisper 語音轉錄設定

| 欄位 | 預設值 | 說明 |
|---|---|---|
| `model` | `large-v3-turbo` | 速度與品質兼顧（CPU 實測約 3 倍速）；追求最高品質且有 NVIDIA 顯卡可改為 `large-v3` |
| `device` | `cuda` | 無顯示卡時自動降為 `cpu` |
| `compute_type` | `auto` | 依可用顯示記憶體自動選 `float16` / `int8_float16` / `int8` |
| `language` | `zh` | 語言代碼。`zh` 繁中、`ja` 日本語、`en` 英文；空字串為自動判斷 |
| `beam_size` | `5` | 解碼品質，數字越大越準也越慢 |
| `vad_filter` | `true` | 語音活動偵測，自動跳過靜音段，長影片速度提升明顯 |
| `normalize_audio` | `true` | **音量過低時的關鍵**：用 ffmpeg 量測平均音量後自動增益，見下方「音量過低」 |
| `max_gain_db` | `25.0` | 音量正規化的最大增益（dB） |
| `hotwords` | `[]` | 專有名詞提示，填 `["LABVIEW", "YOLOv4"]` 可大幅改善術語辨識 |
| `initial_prompt` | `繁體中文。` | 用來誘導模型輸出繁體中文；**不要寫太長**，長提示詞在音訊模糊時會被整句複述 |
| `condition_on_previous_text` | `false` | 關閉可避免模型陷入「一直重複同一句」的迴圈 |
| `no_speech_threshold` | `0.6` | 提高此值讓模型寧可少輸出，也不要再編造無聲音段的內容 |
| `drop_repeated_segments` | `true` | 丟棄連續完全相同的字幕（幻覺的最後一道防線） |
| `refine_long_subtitles` | `true` | 依字詞時間戳把過長字幕切成好閱讀的短句 |
| `max_subtitle_chars` | `20` | 單則字幕字數上限（英文請調大到 60 左右） |
| `max_subtitle_seconds` | `8.0` | 單則字幕時間上限 |
| `output_formats` | `["srt"]` | 可加 `vtt`、`txt` |
| `opencc_config` | `s2twp` | 簡轉繁並套用台灣用語；想保留原文可設 `traditional_converter` 為 `none` |
| `cookies_from_browser` | 空字串 | Bilibili 高畫質或需登入的內容可填 `edge` 或 `chrome` |

### Ollama 重點節錄設定（`summary` 區塊）

| 欄位 | 預設值 | 說明 |
|---|---|---|
| `summary.enabled` | `true` | 是否啟用 Ollama 重點節錄；設為 `false` 時 `run_summary.bat` 只做語音轉錄 |
| `summary.provider` | `remote_ollama` | 切換 Ollama 來源：`remote_ollama`（遠端）、`local_ollama`（本機）或 `none`（關閉） |
| `summary.local_ollama_host` | `http://127.0.0.1:11434` | `provider` 為 `local_ollama` 時使用的本機位址 |
| `summary.remote_ollama_host` | 空字串 | `provider` 為 `remote_ollama` 時使用的遠端位址；留空時自動讀取 `.env` 的 `OLLAMA_HOST` |
| `summary.model` | `gemma4:12b` | 節錄用的 Ollama 模型名稱（可改為該主機已安裝的模型，如 `gemma4:e2b`、`qwen3.5:4b`） |
| `summary.num_ctx` | `16384` | 模型 Context 長度上限 |
| `summary.temperature` | `0.2` | 生成溫度，數值越低越忠實於逐字稿 |
| `summary.timeout_seconds` | `300` | 單次請求逾時秒數 |
| `summary.output_suffix` | `_重點節錄.md` | 節錄檔名後綴 |

## 進階用法

```bat
:: 臨時改用本機 Ollama 與指定模型節錄（不改 config.json）
run_summary.bat 影片.mp4 --provider local_ollama --summary-model qwen3.5:4b

:: 只做轉錄不節錄
run_summary.bat 影片.mp4 --no-summary

:: 輸出三種格式
run_file.bat 影片.mp4 --format srt,vtt,txt

:: 換較快的模型
run_file.bat 影片.mp4 --model large-v3-turbo

:: 指定輸出資料夾
run_file.bat 影片.mp4 --output-dir D:\字幕

:: 保留下載的音檔（不自動刪除）
run_url.bat https://www.youtube.com/watch?v=xxxx --keep-audio

:: 只轉錄前 5 分鐘（先確認音訊品質，推薦用這個試跑）
run_url.bat 影片網址 --clip 0,300

:: 提示專有名詞，術語辨識會明顯變準
run_url.bat 影片網址 --hotwords LABVIEW,YOLOv4,物件偵測

:: 完全繞過 bat，直接呼叫
"%USERPROFILE%\.conda\envs\whisper-subs\python.exe" transcribe.py 影片.mp4 --format srt
"%USERPROFILE%\.conda\envs\whisper-subs\python.exe" summarize_videos.py 影片.mp4
```

## 音量過低怎麼辦（重要）

**音量過低是產生「鬼話字幕」最主要的原因**：模型聽不到聲音時會自行編造文字，並且因為開著前後文關聯而一直重複同一句。

本工具會在轉錄前先用 ffmpeg 量測音量，必要時自動正規化：

```
[音量] 平均 -51.6 dB / 峰值 -9.8 dB -> 正規化後 -27.5 dB（增益 +25.0 dB）
```

判斷基準：

| 平均音量 | 意義 |
|---|---|
| -20 dB 以上 | 正常，不會做正規化 |
| -30 ~ -20 dB | 偏小，仍可正常辨識 |
| -45 ~ -30 dB | 明顯過小，會自動放大，辨識率下降 |
| 低於 -45 dB | 極小聲，放大後仍可能有錯字，建議換音量較大的原始檔 |

實測案例：38 分鐘的教學影片原始平均音量 **-51.6 dB**（只有一般語音的約 3% 音量）。
未做音量處理時產出 653 段重複的無意義文字；開啟音量正規化後同一支影片產出 127 段可讀字幕，完整轉錄僅需 25 秒。

若你的影片本身就是錄音音量太小，**最佳解仍是提高原始音量**，因為放大無法還原錄音時就已經遺失的細節。

## 本機實測數據

以 12.1 秒繁體中文語音、`large-v3` + `float16`、開啟 VAD 與字詞時間戳：

| 項目 | 實測值 |
|---|---|
| 顯卡記憶體峰值 | 約 6.2GB（其中桌面等背景約 2.0GB，模型與推論約 4.2GB） |
| 轉錄速度 | 約 6.3 倍速（12.1 秒音檔 1.9 秒完成） |
| 短檔準確度 | 逐字完全正確（以 Windows TTS 合成語音驗證） |

注意：短音檔的倍速會被模型載入與暖機時間拉低，長影片（數十分鐘以上）的實際倍速通常更高。
執行前建議關閉遊戲等佔用顯卡的程式，8GB 顯卡在 `large-v3` 下已接近上限。

另一組實測：38 分鐘 YouTube 教學影片（原始平均音量 -51.6 dB，需音量正規化），
`large-v3`（RTX 3050）完整轉錄耗時 24.6 秒（約 93 倍速），產出 127 段字幕。

本機 CPU 實測（Intel Core Ultra 5 228V、`large-v3-turbo` + `int8`）：
- 15 分 38 秒中文課程影片：耗時 268.6 秒（約 3.5 倍速），產出 409 段。
- 11 分 10 秒中文課程影片：耗時 215.3 秒（約 3.1 倍速），產出 298 段。

## 已知限制

- **極小音量**：見上方「音量過低怎麼辦」。原始音量低於 -45 dB 時，即使自動放大仍會有錯字，只能換來源。
- **YouTube 反爬蟲**：YouTube 會調整驗證機制，偶爾會出現下載失敗。程式已自動啟用 `node` 作為 JavaScript 執行環境；若仍失敗，可更新 `yt-dlp`（`pip install -U yt-dlp`）或改用 Bilibili。
- **只有 ffmpeg、沒有 ffprobe**：`imageio-ffmpeg` 只附帶 `ffmpeg.exe`。本工具只下載純音軌（`bestaudio`），正常情況不需要 ffprobe；若某些來源需要合併音視訊才會失敗。
- **非 NVIDIA 顯示卡**：`faster-whisper` 底層 `CTranslate2` 僅支援 NVIDIA CUDA 與 CPU，不支援 Intel Arc GPU 或 Intel AI Boost NPU；無 NVIDIA 顯卡時會自動切換至 CPU（`int8`）。
- **繁簡與台灣用語轉換**：模型輸出多為簡體，`s2twp` 會轉成繁體並套用台灣慣用詞，但偶爾會有不合語境的替換，正式使用前建議抽查。
- **字幕分段**：切分依賴模型給的字詞時間戳，無標點又講得很快的段落，切點可能落在字與字之間。
- **非逐字稿**：本工具輸出的是「以句為單位」的字幕，不是逐字對齊稿；短句、疊字、語速變化大的內容時間軸可能有 0.1–0.3 秒誤差。
- **版權**：字幕僅供個人使用，對外散布或商業使用須取得內容授權。

## 環境與套件版本

| 項目 | 版本 |
|---|---|
| conda 環境 | `whisper-subs`（Python 3.11.18） |
| faster-whisper | 1.2.1 |
| ctranslate2 | 4.9.1 |
| yt-dlp | 2026.8.19 |
| imageio-ffmpeg | 0.6.0 |
| opencc-python-reimplemented | 0.1.7 |
| Node.js | v24.16.0（供 `yt-dlp` 執行 YouTube JS 驗證） |
| GPU / CUDA | 有 NVIDIA 顯卡時由 `ctranslate2` 內附 CUDA 12 runtime（**不需另裝 CUDA Toolkit**）；無 NVIDIA 顯卡時自動切換 CPU `int8` |

重新建立環境：刪除 `models\` 快取後再次執行 `setup_env.bat` 即可。