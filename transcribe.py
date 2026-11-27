"""YouTube / Bilibili / 本地影音檔 自動產生繁體中文字幕。

流程：yt-dlp 下載音軌（或直接使用本地檔） -> faster-whisper 轉錄 -> OpenCV/列表輸出 SRT/TXT/VTT。
所有產出一律寫入專案內的 output\\ 目錄，並先檢查路徑確實位於專案目錄內。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

# 專案根目錄（以本檔所在位置為準，避免依賴目前工作目錄）
PROJECT_DIR = Path(__file__).resolve().parent
INPUT_DIR = PROJECT_DIR / "input"
OUTPUT_DIR = PROJECT_DIR / "output"
MODELS_DIR = PROJECT_DIR / "models"
CONFIG_PATH = PROJECT_DIR / "config.json"

# Hugging Face / CTranslate2 的模型快取都放在專案內，避免寫入使用者家目錄
os.environ.setdefault("HF_HOME", str(MODELS_DIR))

# 允許處理的媒體副檔名（副檔名僅作第一層過濾，實際解碼由 PyAV 負責）
MEDIA_SUFFIXES = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".ts", ".m4v", ".wmv",
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", "wma", ".mpga",
}

# 使用者輸入（檔名、影片標題）只保留這些字元，避免路徑穿越或非法檔名
SAFE_NAME_PATTERN = re.compile(r"[^\w\-. 一-鿿぀-ヿ]")

# 夾在中文字之間時改用全形標點；句點因為容易誤判數值而保留原樣
CJK_PUNCTUATION_MAP = {",": "，", "?": "？", "!": "！", ";": "；", ":": "："}

# 模型偶爾會輸出直排（vertical presentation form）標點，字幕必須轉回橫排常見字形
VERTICAL_PUNCTUATION_MAP = {
    "﹐": "，",
    "﹑": "、",
    "﹒": "。",
    "﹔": "；",
    "﹕": "：",
    "﹖": "！",
    "﹗": "？",
    "﹐": "，",
    "﹑": "、",
    "﹒": "。",
    "﹔": "；",
    "﹕": "：",
    "﹖": "！",
    "﹗": "？",
}

# 字幕切分時偏好斷句的位置
BREAK_MARKS = "，。？！；：、,.?!;:"

DEFAULT_CONFIG: dict = {
    "model": "large-v3",
    "device": "cuda",
    "compute_type": "auto",
    "language": "zh",
    "task": "transcribe",
    "beam_size": 5,
    "vad_filter": True,
    "vad_parameters": {"min_silence_duration_ms": 500, "speech_pad_ms": 200},
    # 提示詞必須短，長提示詞在音訊模糊時會被模型整句複述成字幕
    "initial_prompt": "繁體中文。",
    "condition_on_previous_text": False,
    "no_speech_threshold": 0.6,
    "log_prob_threshold": -1.0,
    "compression_ratio_threshold": 2.4,
    "temperature": [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    "normalize_audio": True,
    "drop_repeated_segments": True,
    "refine_long_subtitles": True,
    "max_subtitle_chars": 20,
    "max_subtitle_seconds": 6.0,
    "min_break_chars": 8,
    "output_formats": ["srt"],
    "traditional_converter": "opencc",
    "opencc_config": "s2twp",
    "cookies_from_browser": "",
    "audio_format_preference": "bestaudio/best",
    "models_dir": "models",
}


def log(message: str) -> None:
    print(message, flush=True)


def warn(message: str) -> None:
    print(f"[警告] {message}", flush=True)


# ---------------------------------------------------------------------------
# 路徑安全處理
# ---------------------------------------------------------------------------
def is_inside(base: Path, target: Path) -> bool:
    """確認 target 位於 base 之內（防路徑穿越）。"""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except (ValueError, OSError):
        return False


def safe_output_stem(raw: str) -> str:
    """把不受信任的檔名／標題轉成安全的輸出檔名（不含路徑分隔符）。"""
    name = Path(raw).name  # 先丟掉任何目錄成分
    name = SAFE_NAME_PATTERN.sub("_", name).strip(" .")
    name = re.sub(r"_{3,}", "__", name)
    if len(name) > 80:
        name = name[:80].rstrip(" .")
    return name or "subtitle"


def safe_model_path(raw: str) -> str | None:
    """模型名稱若看起來像本機路徑，先確認檔案存在，不存在就當作名稱處理。"""
    if any(sep in raw for sep in ("/", "\\")):
        candidate = Path(raw).expanduser()
        if candidate.exists():
            return str(candidate.resolve())
        raise ValueError(f"找不到本機模型目錄：{raw}")
    return raw


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------
def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.is_file():
        loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("config.json 內容必須是 JSON 物件")
        config.update(loaded)
    return config


# ---------------------------------------------------------------------------
# 硬體 / 顯示卡
# ---------------------------------------------------------------------------
def query_gpu_memory_mb() -> tuple[int, int] | None:
    """回傳 (總顯示記憶體, 可用顯示記憶體) MB；查不到就回傳 None。"""
    command = [
        "nvidia-smi",
        "--query-gpu=memory.total,memory.free",
        "--format=csv,noheader,nounits",
    ]
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, timeout=10, check=True
        )
    except (OSError, subprocess.SubprocessError):
        return None

    first_line = completed.stdout.strip().splitlines()
    if not first_line:
        return None
    parts = [part.strip() for part in first_line[0].split(",")]
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return int(parts[0]), int(parts[1])


def resolve_compute_type(requested: str, device: str, free_mb: int | None) -> str:
    """把 compute_type=auto 依可用顯示記憶體換算成實際值。"""
    if requested and requested != "auto":
        return requested
    if device == "cpu":
        return "int8"
    if free_mb is None:
        return "float16"
    if free_mb >= 5000:
        return "float16"
    if free_mb >= 3000:
        return "int8_float16"
    if free_mb >= 1800:
        return "int8"
    return "int8_float16"


def build_load_candidates(device: str, compute_type: str) -> list[tuple[str, str]]:
    """依序嘗試的 (device, compute_type)，從最佳畫質到保證能跑。"""
    if device != "cuda":
        return [(device, compute_type)]

    preferred = [compute_type] + ["float16", "int8_float16", "int8"]
    ordered = list(dict.fromkeys(preferred))
    return [("cuda", item) for item in ordered] + [("cpu", "int8")]


def load_model(config: dict, model_name: str):
    """載入 faster-whisper 模型，必要時自動降級顯示卡精度或改用 CPU。"""
    from faster_whisper import WhisperModel

    device = config["device"]
    gpu_memory = query_gpu_memory_mb() if device == "cuda" else None
    free_mb = gpu_memory[1] if gpu_memory is not None else None
    compute_type = resolve_compute_type(config["compute_type"], device, free_mb)
    download_root = MODELS_DIR / "faster-whisper"
    download_root.mkdir(parents=True, exist_ok=True)

    last_error: Exception | None = None
    for candidate_device, candidate_type in build_load_candidates(device, compute_type):
        try:
            log(f"[模型] 載入 {model_name}（{candidate_device} / {candidate_type}）")
            model = WhisperModel(
                model_name,
                device=candidate_device,
                compute_type=candidate_type,
                download_root=str(download_root),
            )
            return model, candidate_device, candidate_type
        except Exception as error:  # noqa: BLE001 - 需要捕捉各版本 CTranslate2 的不同例外
            last_error = error
            warn(f"以 {candidate_device} / {candidate_type} 載入失敗：{error}")

    raise RuntimeError(f"所有設定皆無法載入模型：{last_error}")


# ---------------------------------------------------------------------------
# 繁體中文轉換
# ---------------------------------------------------------------------------
def build_converter(config: dict):
    """回傳繁簡轉換函式；無法使用 OpenCC 時回傳 None（保留原始輸出）。"""
    if config.get("traditional_converter") == "none":
        return None
    try:
        from opencc import OpenCC
    except ImportError:
        warn("未安裝 opencc，輸出將維持模型原始的簡體字")
        return None
    try:
        converter = OpenCC(config.get("opencc_config", "s2twp"))
    except Exception as error:  # noqa: BLE001 - OpenCC 設定值格式可能不同版本有差異
        warn(f"OpenCC 設定 {config.get('opencc_config')} 無效（{error}），改用 s2t")
        converter = OpenCC("s2t")

    def convert(text: str) -> str:
        return converter.convert(text)

    return convert


# ---------------------------------------------------------------------------
# 下載
# ---------------------------------------------------------------------------
def validate_url(raw_url: str) -> str:
    """只允許 http/https，並移除危險字元，避免把網址當成路徑或指令。"""
    candidate = raw_url.strip().strip('"').strip("'")
    if any(char in candidate for char in ("\n", "\r", "\t", "\x00")):
        raise ValueError("網址含有非法字元")
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"只支援 http/https 網址：{candidate}")
    if not parsed.netloc:
        raise ValueError(f"網址格式不正確：{candidate}")
    return candidate


def download_audio(url: str, config: dict) -> tuple[Path, str]:
    """用 yt-dlp Python API 下載最佳音軌到 input\\，回傳 (音檔路徑, 影片標題)。"""
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("未安裝 yt-dlp，無法下載網址內容") from None

    ffmpeg_location = get_ffmpeg_exe()

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    options: dict = {
        "format": config.get("audio_format_preference", "bestaudio/best"),
        "outtmpl": str(INPUT_DIR / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "windowsfilenames": True,
        "quiet": True,
        "no_warnings": False,
        "consoletitle": False,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        # YouTube 需要 JavaScript 執行環境才能正確解析，有 node 就直接用
        "remote_components": ["ejs:github"],
    }
    if shutil.which("node"):
        options["js_runtimes"] = {"node": {}}
    else:
        warn("找不到 node，YouTube 部分影片可能無法解析（可安裝 Deno 或 Node.js）")
    if ffmpeg_location:
        options["ffmpeg_location"] = ffmpeg_location
    cookies_browser = (config.get("cookies_from_browser") or "").strip()
    if cookies_browser:
        options["cookiesfrombrowser"] = (cookies_browser,)

    log(f"[下載] {url}")
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=True)
        if info is None:
            raise RuntimeError("yt-dlp 沒有回傳影片資訊")
        video_id = info.get("id") or "media"
        log(f"[下載] 標題：{info.get('title') or '(無)'}")

    expected_prefix = f"{safe_output_stem(str(video_id))}."
    candidates = sorted(INPUT_DIR.glob(f"{expected_prefix}*"))
    candidates = [item for item in candidates if item.is_file() and item.suffix != ".part"]
    if not candidates:
        raise FileNotFoundError(f"下載後找不到音檔：{expected_prefix}*")
    audio_path = candidates[-1]
    if not is_inside(INPUT_DIR, audio_path):
        raise RuntimeError("下載檔案位置異常，已中止")
    return audio_path, str(info.get("title") or "")


# ---------------------------------------------------------------------------
# 音量：過小的音訊會讓 Whisper 產生幻覺，必須先正規化
# ---------------------------------------------------------------------------
def get_ffmpeg_exe() -> str | None:
    """取得隨專案附帶的 ffmpeg 路徑；找不到就回傳 None。"""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as error:  # noqa: BLE001 - 缺少 ffmpeg 只影響音量處理
        warn(f"取得隨附 ffmpeg 失敗（{error}），音量正規化將略過")
        return None


def run_ffmpeg(arguments: list[str]) -> None:
    """以參數陣列呼叫 ffmpeg，不經過 shell。"""
    completed = subprocess.run(
        arguments, capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    if completed.returncode != 0:
        tail = (completed.stderr or "").strip().splitlines()[-3:]
        raise RuntimeError("ffmpeg 失敗：" + " / ".join(tail))


def measure_loudness(audio_path: Path, ffmpeg: str) -> tuple[float, float] | None:
    """用 volumedetect 量測平均與最大音量（dB）。"""
    try:
        completed = subprocess.run(
            [ffmpeg, "-hide_banner", "-nostats", "-i", str(audio_path),
             "-af", "volumedetect", "-f", "null", "-"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        return None

    mean = maximum = None
    for line in (completed.stderr or "").splitlines():
        if "mean_volume:" in line:
            mean = _parse_decibel(line)
        elif "max_volume:" in line:
            maximum = _parse_decibel(line)
    if mean is None:
        return None
    return mean, maximum if maximum is not None else mean


def _parse_decibel(line: str) -> float | None:
    for token in line.replace(":", " ").split():
        try:
            value = float(token)
        except ValueError:
            continue
        return value
    return None


def normalize_audio(audio_path: Path, ffmpeg: str, config_gain_limit: float = 25.0) -> Path:
    """把過小的音量拉回語音可辨識範圍，輸出 16kHz 單聲道 WAV。

    先依實測音量計算增益（受峰值限制避免爆音），再做 loudnorm 動態修正。
    """
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    target = INPUT_DIR / f"{audio_path.stem}_norm.wav"
    before = measure_loudness(audio_path, ffmpeg)
    if before and before[0] > -30.0:
        log(f"[音量] 平均 {before[0]:.1f} dB 屬正常範圍，略過正規化")
        return audio_path

    mean_volume, peak_volume = before if before else (-40.0, -10.0)
    # 以實測平均音量計算增益，讓語音回到可辨識範圍；峰值交給 alimiter 處理，避免硬削波失真
    gain_limit = float(config_gain_limit)
    gain = max(min(-18.0 - mean_volume, gain_limit), 1.0)

    run_ffmpeg([
        ffmpeg, "-y", "-hide_banner", "-nostats",
        "-i", str(audio_path),
        "-vn", "-ac", "1", "-ar", "16000",
        "-af", f"volume={gain:.1f}dB,alimiter=limit=0.891:attack=5:release=50",
        "-c:a", "pcm_s16le",
        str(target),
    ])
    after = measure_loudness(target, ffmpeg)
    if after:
        log(
            f"[音量] 平均 {before[0]:.1f} dB / 峰值 {before[1]:.1f} dB"
            f" -> 正規化後 {after[0]:.1f} dB（增益 {gain:+.1f} dB）"
        )
    else:
        log(f"[音量] 已正規化音訊（增益 {gain:+.1f} dB）-> {target.name}")

    if mean_volume < -45.0:
        warn(
            f"原始音量極低（平均 {mean_volume:.1f} dB），就算放大後仍可能辨識不準。"
            "建議改用音量較大的原始音檔，或在錄製時離麥克風近一點。"
        )
    return target


# ---------------------------------------------------------------------------
# 字幕輸出
# ---------------------------------------------------------------------------
def format_timestamp(seconds: float, comma: bool = True) -> str:
    milliseconds = max(0, int(round(seconds * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)
    separator = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{milliseconds:03d}"


@dataclass
class Segment:
    index: int
    start: float
    end: float
    text: str


@dataclass
class Target:
    kind: str  # "url" 或 "file"
    value: str
    display_name: str = ""
    cleanup_paths: list[Path] = field(default_factory=list)
    produced: list[Path] = field(default_factory=list)


def collect_targets(inputs: list[str]) -> list[Target]:
    targets: list[Target] = []
    for item in inputs:
        if item.lower().startswith(("http://", "https://")):
            url = validate_url(item)
            targets.append(Target(kind="url", value=url, display_name=url))
            continue

        path = Path(item).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"找不到檔案或資料夾：{item}")

        if path.is_dir():
            # 允許讀取專案外的資料夾（使用者自行拖放），但只挑出支援的媒體檔
            if not is_inside(PROJECT_DIR, path):
                log(f"[讀取] 專案外的資料夾：{path}")
            files = [
                child
                for child in sorted(path.iterdir())
                if child.is_file() and child.suffix.lower() in MEDIA_SUFFIXES
            ]
            if not files:
                warn(f"資料夾內沒有支援的媒體檔：{path}")
            for child in files:
                targets.append(
                    Target(kind="file", value=str(child), display_name=child.name)
                )
        elif path.suffix.lower() in MEDIA_SUFFIXES:
            targets.append(Target(kind="file", value=str(path), display_name=path.name))
        else:
            warn(f"不支援的檔案類型，已略過：{path}")
    return targets


def write_srt(segments: list[Segment], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="\n") as handle:
        for segment in segments:
            handle.write(
                f"{segment.index}\n"
                f"{format_timestamp(segment.start)} --> {format_timestamp(segment.end)}\n"
                f"{segment.text}\n\n"
            )


def write_vtt(segments: list[Segment], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="\n") as handle:
        handle.write("WEBVTT\n\n")
        for segment in segments:
            handle.write(
                f"{format_timestamp(segment.start, comma=False)}"
                f" --> {format_timestamp(segment.end, comma=False)}\n"
                f"{segment.text}\n\n"
            )


def write_txt(segments: list[Segment], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="\n") as handle:
        for segment in segments:
            handle.write(f"[{format_timestamp(segment.start)}] {segment.text}\n")


def is_cjk(char: str) -> bool:
    code = ord(char)
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFFEF
    )


def normalize_cjk_punctuation(text: str) -> str:
    """把中文字旁的半形標點換成全形，數字與英文之間的半形標點維持原樣。"""
    text = "".join(VERTICAL_PUNCTUATION_MAP.get(char, char) for char in text)
    result = list(text)
    for index, char in enumerate(result):
        replacement = CJK_PUNCTUATION_MAP.get(char)
        if not replacement:
            continue
        previous = text[index - 1] if index > 0 else ""
        following = text[index + 1] if index + 1 < len(text) else ""
        if is_cjk(previous) and (not following or following == " " or is_cjk(following)):
            result[index] = replacement
    return "".join(result)


def split_segment_for_subtitle(
    words,
    segment_start: float,
    segment_end: float,
    fallback_text: str,
    max_chars: int,
    max_seconds: float,
    min_chars: int,
) -> list[tuple[float, float, str]]:
    """在字詞時間戳邊界切分過長的字幕，優先在標點後斷句。"""
    if not words:
        return [(segment_start, segment_end, fallback_text)]

    # 硬上限：超過就必須斷，避免無標點的長句變成整行字幕
    hard_chars = max(int(max_chars * 1.5), max_chars + 1)
    hard_seconds = max_seconds * 1.5

    chunks: list[tuple[float, float, str]] = []
    buffer: list = []
    buffer_text = ""

    for word in words:
        buffer.append(word)
        # faster-whisper 的 Word 欄位名稱是 word，不是 text
        buffer_text = "".join(getattr(item, "word", "") for item in buffer).strip()
        length = len(buffer_text)
        # 時間長度必須相對於「目前這一組」計算，否則會從整段開頭算而每個字都斷一次
        chunk_span = word.end - buffer[0].start
        ends_with_mark = buffer_text[-1:] in BREAK_MARKS

        if ends_with_mark and length >= min_chars:
            should_break = True
        elif chunk_span >= max_seconds and length >= min_chars:
            should_break = True
        else:
            should_break = length >= hard_chars or chunk_span >= hard_seconds

        if should_break:
            chunks.append((buffer[0].start, word.end, buffer_text))
            buffer = []
            buffer_text = ""

    if buffer:
        buffer_text = "".join(getattr(item, "word", "") for item in buffer).strip()
        chunks.append((buffer[0].start, words[-1].end, buffer_text))

    return chunks or [(segment_start, segment_end, fallback_text)]


def transcribe_one(
    target: Target,
    model,
    config: dict,
    convert,
    output_dir: Path,
) -> list[Path]:
    media_title = ""
    if target.kind == "url":
        audio_path, media_title = download_audio(target.value, config)
    else:
        audio_path = Path(target.value)
    if not audio_path.is_file():
        raise FileNotFoundError(f"找不到音檔：{audio_path}")
    source_path = audio_path

    # 網址來源以影片標題命名輸出，本地來源以檔名命名
    base_name = media_title or target.display_name or audio_path.name
    stem = safe_output_stem(Path(base_name).stem)
    log(f"[轉錄] {audio_path.name} -> {output_dir / (stem + '.srt')}")

    # 音量過低是 Whisper 產生幻覺最主要的原因，先做常態音量正規化
    normalized_path: Path | None = None
    if config.get("normalize_audio", True):
        ffmpeg = get_ffmpeg_exe()
        if ffmpeg is None:
            warn("沒有 ffmpeg，略過音量正規化；音量過低時可能產生幻覺字幕")
        else:
            normalized_path = normalize_audio(
                audio_path, ffmpeg, float(config.get("max_gain_db", 25.0))
            )
            if normalized_path != audio_path:
                audio_path = normalized_path

    refine = bool(config.get("refine_long_subtitles", True))
    max_chars = int(config.get("max_subtitle_chars", 20))
    max_seconds = float(config.get("max_subtitle_seconds", 6.0))
    min_chars = int(config.get("min_break_chars", 8))
    drop_repeats = bool(config.get("drop_repeated_segments", True))

    transcribe_options: dict = {
        "language": config.get("language") or None,
        "task": config.get("task", "transcribe"),
        "beam_size": int(config.get("beam_size", 5)),
        "vad_filter": bool(config.get("vad_filter", True)),
        "vad_parameters": config.get("vad_parameters") or None,
        "initial_prompt": config.get("initial_prompt") or None,
        "condition_on_previous_text": bool(config.get("condition_on_previous_text", False)),
        "word_timestamps": refine,
        # 提高無語音判定門檻，讓模型寧可少輸出也不要編造內容
        "no_speech_threshold": float(config.get("no_speech_threshold", 0.6)),
        "log_prob_threshold": float(config.get("log_prob_threshold", -1.0)),
        "compression_ratio_threshold": float(config.get("compression_ratio_threshold", 2.4)),
        "temperature": config.get("temperature") or [0.0, 0.2, 0.4, 0.6, 0.8, 1.0],
    }
    clip = config.get("_clip_timestamps")
    if clip:
        transcribe_options["clip_timestamps"] = clip
    hotwords = config.get("hotwords") or []
    if hotwords:
        # faster-whisper 的 hotwords 參數是字串，不是清單
        transcribe_options["hotwords"] = ", ".join(str(item) for item in hotwords)
        log(f"[專有名詞] {hotwords}")

    segments_iter, info = model.transcribe(str(audio_path), **transcribe_options)

    duration = float(getattr(info, "duration", 0.0) or 0.0)
    detected = str(getattr(info, "language", "")) or config.get("language", "")
    log(f"[轉錄] 語言={detected} 長度={duration:.1f} 秒")

    # 逐段寫入，避免長音檔中途中斷導致整份字幕遺失
    srt_path = output_dir / f"{stem}.srt"
    started = time.perf_counter()
    segments: list[Segment] = []
    with srt_path.open("w", encoding="utf-8-sig", newline="\n") as handle:
        for segment in segments_iter:
            text = (segment.text or "").strip()
            if not text:
                continue

            if refine:
                pieces = split_segment_for_subtitle(
                    getattr(segment, "words", None),
                    segment.start,
                    segment.end,
                    text,
                    max_chars,
                    max_seconds,
                    min_chars,
                )
            else:
                pieces = [(segment.start, segment.end, text)]

            for piece_start, piece_end, piece_text in pieces:
                piece_text = piece_text.strip()
                if not piece_text:
                    continue
                # 字詞切分是從 word 文字重建的，繁簡與標點必須在切分後才處理
                if convert:
                    piece_text = convert(piece_text)
                piece_text = normalize_cjk_punctuation(piece_text)
                # 連續完全相同的字幕多半是模型幻覺，直接丟棄
                if drop_repeats and segments and piece_text == segments[-1].text:
                    continue
                item = Segment(
                    index=len(segments) + 1,
                    start=piece_start,
                    end=max(piece_end, piece_start + 0.05),
                    text=piece_text,
                )
                segments.append(item)
                handle.write(
                    f"{item.index}\n"
                    f"{format_timestamp(item.start)} --> {format_timestamp(item.end)}\n"
                    f"{item.text}\n\n"
                )
                handle.flush()
                if len(segments) % 25 == 0:
                    log(f"[轉錄] 已輸出 {len(segments)} 段（{item.end:.0f} 秒）")

    # 完全沒有語音時不要留下 0 位元組的字幕檔，避免誤以為轉錄成功
    if not segments:
        srt_path.unlink(missing_ok=True)
        raise RuntimeError(
            "沒有辨識到任何語音。若影片確實有聲音，代表音量過低或幾乎無聲，"
            "請提高原始音量後再試；已是可聽見音量時可改用較大的模型或調整 config.json。"
        )

    produced = [srt_path]
    formats = config.get("output_formats") or ["srt"]
    if "vtt" in formats:
        vtt_path = output_dir / f"{stem}.vtt"
        write_vtt(segments, vtt_path)
        produced.append(vtt_path)
    if "txt" in formats:
        txt_path = output_dir / f"{stem}.txt"
        write_txt(segments, txt_path)
        produced.append(txt_path)

    elapsed = time.perf_counter() - started
    if duration > 0:
        log(f"[完成] {len(segments)} 段，耗時 {elapsed:.1f} 秒（{duration / elapsed:.1f} 倍速）")
    else:
        log(f"[完成] {len(segments)} 段，耗時 {elapsed:.1f} 秒")

    if target.kind == "url":
        # 網址來源的下載檔與正規化暫存檔都要清掉；本地檔只清正規化暫存檔
        target.cleanup_paths.append(source_path)
        if normalized_path is not None and normalized_path != source_path:
            target.cleanup_paths.append(normalized_path)
    elif normalized_path is not None and normalized_path != source_path:
        target.cleanup_paths.append(normalized_path)
    return produced


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def read_targets_interactively() -> list[str]:
    """沒有帶參數時，讓使用者直接貼上網址或檔案路徑。"""
    log("請貼上 YouTube / Bilibili 網址，或本地影音檔路徑。")
    log("可連續貼多行，每行一個；直接按 Enter 結束。")
    log("-" * 50)

    items: list[str] = []
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            log("")
            break
        if not line:
            break
        items.append(line.strip('"').strip("'"))
    return items


def parse_clip(raw: str) -> list[float]:
    """把 --clip 參數轉成秒數清單。"""
    parts = [item.strip() for item in raw.split(",") if item.strip()]
    try:
        values = [float(item) for item in parts]
    except ValueError as error:
        raise ValueError(f"--clip 格式錯誤：{raw}") from error
    if not values or any(value < 0 for value in values):
        raise ValueError(f"--clip 必須是非負數字：{raw}")
    return values


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="YouTube / Bilibili / 本地影音檔 自動產生繁體中文字幕"
    )
    parser.add_argument("inputs", nargs="*", help="網址、影音檔或資料夾（留空則互動式輸入）")
    parser.add_argument("--model", help="覆寫模型名稱或本機模型目錄")
    parser.add_argument("--device", choices=["cuda", "cpu"], help="覆寫執行裝置")
    parser.add_argument(
        "--compute-type",
        help="覆寫精度，例如 float16 / int8_float16 / int8 / auto",
    )
    parser.add_argument("--language", help="語言代碼，例如 zh、ja、en")
    parser.add_argument("--format", dest="formats", help="輸出格式，逗號分隔，例如 srt,vtt,txt")
    parser.add_argument("--output-dir", help="輸出資料夾（預設為專案 output）")
    parser.add_argument(
        "--clip",
        help="只轉錄片段，格式為起點,終點（秒），例如 --clip 0,300；也接受單一數字表示起點",
    )
    parser.add_argument(
        "--hotwords", help="專有名詞提示，逗號分隔，例如 --hotwords LABVIEW,YOLOv4"
    )
    parser.add_argument(
        "--keep-audio", action="store_true", help="保留下載的音檔，不刪除"
    )
    return parser


def main() -> int:
    # Windows 主控台預設為 cp950，強制 UTF-8 避免中文路徑或輸出報錯
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args()
    config = load_config()
    if args.model:
        config["model"] = args.model
    if args.device:
        config["device"] = args.device
    if args.compute_type:
        config["compute_type"] = args.compute_type
    if args.language:
        config["language"] = args.language
    if args.formats:
        config["output_formats"] = [
            item.strip().lower() for item in args.formats.split(",") if item.strip()
        ]
    if args.clip:
        config["_clip_timestamps"] = parse_clip(args.clip)
        log(f"[範圍] 只轉錄 {config['_clip_timestamps']} 秒區間")
    if args.hotwords:
        config["hotwords"] = [
            item.strip() for item in args.hotwords.split(",") if item.strip()
        ]

    if shutil.which("nvidia-smi") is None and config["device"] == "cuda":
        warn("找不到 nvidia-smi，將以 CPU 模式執行")
        config["device"] = "cpu"

    memory = query_gpu_memory_mb()
    if memory:
        log(f"[顯示卡] 總記憶體 {memory[0]} MB / 可用 {memory[1]} MB")

    output_dir = Path(args.output_dir).expanduser() if args.output_dir else OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = list(args.inputs)
    if not inputs:
        inputs = read_targets_interactively()

    targets = collect_targets(inputs)
    if not targets:
        warn("沒有可處理的檔案")
        return 1
    log(f"[任務] 共 {len(targets)} 個項目")

    model_name = safe_model_path(str(config["model"]))
    model, device, compute_type = load_model(config, model_name)
    log(f"[設定] device={device} compute_type={compute_type} language={config['language']}")
    convert = build_converter(config)

    succeeded = 0
    failed: list[str] = []
    produced_all: list[Path] = []
    for index, target in enumerate(targets, start=1):
        log(f"===== [{index}/{len(targets)}] {target.display_name} =====")
        try:
            target.produced = transcribe_one(target, model, config, convert, output_dir)
            produced_all.extend(target.produced)
            succeeded += 1
        except Exception as error:  # noqa: BLE001 - 單一檔案失敗不應中止整批
            failed.append(f"{target.display_name}: {error}")
            warn(f"處理失敗：{error}")
        finally:
            # 暫存音檔於轉錄後清除，除非使用者要求保留
            if not args.keep_audio:
                for cleanup in target.cleanup_paths:
                    if is_inside(INPUT_DIR, cleanup):
                        try:
                            cleanup.unlink()
                        except OSError as error:
                            warn(f"暫存音檔刪除失敗：{error}")

    log("===== 結果 =====")
    log(f"成功 {succeeded} / {len(targets)}")
    # 只列出本次實際產出的檔案，避免把舊檔算成新結果
    for path in dict.fromkeys(produced_all):
        log(f"產出：{path}")
    if failed:
        log("失敗清單：")
        for item in failed:
            log(f"  - {item}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())