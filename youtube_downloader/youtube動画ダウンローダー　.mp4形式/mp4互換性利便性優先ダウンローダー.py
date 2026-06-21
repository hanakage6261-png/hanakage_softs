import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
import yt_dlp


BASE_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "mp4_downloader")
VIDEO_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "youtube_mp4")
THUMB_DIR = os.path.join(BASE_DIR, "thumbs")
ARCHIVE_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "MKV_archive_from_youtube")
PENDING_FILE = os.path.join(BASE_DIR, "pending_urls.json")

MAX_CONCURRENT_DOWNLOADS = 2
THUMB_DOWNLOAD_WORKERS = 8
FRAGMENT_DOWNLOADS = 4
DOWNLOAD_POLL_SECONDS = 0.3
KEEP_ARCHIVE_RAW_STREAMS = False
COOKIE_BROWSER_ENV = "YTDLP_COOKIE_BROWSER"
COOKIE_BROWSER_CANDIDATES = ("edge", "chrome", "firefox")
VIDEO_CODEC_EFFICIENCY = {
    "AV1": 1.35,
    "H.265": 1.25,
    "VP9": 1.15,
    "H.264": 1.0,
    "OTHER": 0.85,
}
VIDEO_CODEC_PREFERENCE = {
    "AV1": 4,
    "H.265": 3,
    "VP9": 2,
    "H.264": 1,
    "OTHER": 0,
}
AUDIO_CODEC_EFFICIENCY = {
    "OPUS": 1.25,
    "AAC": 1.0,
    "OTHER": 0.85,
}
AUDIO_CODEC_PREFERENCE = {
    "OPUS": 2,
    "AAC": 1,
    "OTHER": 0,
}

os.makedirs(VIDEO_DIR, exist_ok=True)
os.makedirs(ARCHIVE_DIR, exist_ok=True)


def resolve_tool_path(name):
    candidates = []

    if getattr(sys, "frozen", False):
        candidates.append(os.path.join(os.path.dirname(sys.executable), f"{name}.exe"))
        candidates.append(os.path.join(os.path.dirname(sys.executable), name))

    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        candidates.append(os.path.join(bundle_dir, f"{name}.exe"))
        candidates.append(os.path.join(bundle_dir, name))

    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(script_dir, f"{name}.exe"))
    candidates.append(os.path.join(script_dir, name))

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    found = shutil.which(name)
    if found:
        return found

    found_exe = shutil.which(f"{name}.exe")
    if found_exe:
        return found_exe

    return name


FFMPEG_PATH = resolve_tool_path("ffmpeg")
NODE_PATH = resolve_tool_path("node")


def safe_filename(name, max_length=100):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name or "")
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "video"

    reserved_names = {
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    if name.upper() in reserved_names:
        name = f"_{name}"

    return name[:max_length].rstrip(" .") or "video"


def unique_folder(path):
    if not os.path.exists(path):
        return path

    index = 2
    while True:
        candidate = f"{path} ({index})"
        if not os.path.exists(candidate):
            return candidate
        index += 1


def format_size(num_bytes):
    if not num_bytes:
        return "?"

    size = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def format_date(raw_date):
    if not raw_date or len(raw_date) != 8:
        return ""

    try:
        return datetime.strptime(raw_date, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def simplify_vcodec(vcodec):
    value = (vcodec or "").lower()
    if value.startswith("avc"):
        return "H.264"
    if value.startswith("vp9"):
        return "VP9"
    if value.startswith("av01"):
        return "AV1"
    if value.startswith("hev") or value.startswith("hvc"):
        return "H.265"
    return value or "?"


def simplify_acodec(acodec):
    value = (acodec or "").lower()
    if value.startswith("mp4a"):
        return "AAC"
    if value.startswith("opus"):
        return "OPUS"
    return value or "?"


def is_mp4_compatible_video(fmt):
    return (fmt.get("vcodec") or "").startswith("avc") and fmt.get("ext") == "mp4"


def is_mp4_compatible_audio(fmt):
    return (fmt.get("acodec") or "").startswith("mp4a") and fmt.get("ext") == "m4a"


def ask_int(prompt, valid_numbers):
    valid_numbers = set(valid_numbers)

    while True:
        value = input(prompt).strip()

        if not re.fullmatch(r"[0-9]+", value):
            print("数字だけを入力してください。")
            continue

        number = int(value)
        if number in valid_numbers:
            return number

        print("表示されている番号を入力してください。")


def collect_urls():
    print("\nURLを1行ずつ入力してください。")
    print("動画URL、プレイリストURL、チャンネルURL、いいね/履歴などの一覧URLを入力できます。")
    print("空行で受付終了します。最初から空行なら終了です。")

    urls = []
    while True:
        prompt = "URL: " if not urls else f"URL {len(urls) + 1}: "
        url = input(prompt).strip()
        if not url:
            return urls
        urls.append(url)



def load_pending_items():
    if not os.path.exists(PENDING_FILE):
        return []

    try:
        with open(PENDING_FILE, "r", encoding="utf-8") as file_obj:
            data = json.load(file_obj)
    except (OSError, json.JSONDecodeError):
        return []

    if not isinstance(data, list):
        return []

    items = []
    seen = set()
    for item in data:
        if isinstance(item, str):
            item = {"url": item, "cookie_browser": None}
        if not isinstance(item, dict):
            continue
        url = item.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        items.append({"url": url, "cookie_browser": item.get("cookie_browser")})
    return items


def save_pending_items(items):
    os.makedirs(BASE_DIR, exist_ok=True)
    compact_items = []
    seen = set()

    for item in items:
        url = item.get("url") if isinstance(item, dict) else str(item)
        if not url or url in seen:
            continue
        seen.add(url)
        compact_items.append(
            {
                "url": url,
                "cookie_browser": item.get("cookie_browser") if isinstance(item, dict) else None,
            }
        )

    if not compact_items:
        try:
            os.remove(PENDING_FILE)
        except FileNotFoundError:
            pass
        return

    with open(PENDING_FILE, "w", encoding="utf-8") as file_obj:
        json.dump(compact_items, file_obj, ensure_ascii=False, indent=2)


def merge_pending_items(existing_items, new_items):
    merged = []
    seen = set()

    for item in [*existing_items, *new_items]:
        url = item.get("url") if isinstance(item, dict) else str(item)
        if not url or url in seen:
            continue
        seen.add(url)
        merged.append(
            {
                "url": url,
                "cookie_browser": item.get("cookie_browser") if isinstance(item, dict) else None,
            }
        )

    return merged


def remove_pending_url(url):
    if not url:
        return
    save_pending_items([item for item in load_pending_items() if item.get("url") != url])
def cookie_browser_candidates(preferred=None):
    env_browser = os.environ.get(COOKIE_BROWSER_ENV, "").strip()
    browsers = []

    for browser in (preferred, env_browser, *COOKIE_BROWSER_CANDIDATES):
        if browser and browser not in browsers:
            browsers.append(browser)

    return browsers


def add_cookie_option(opts, cookie_browser):
    opts = dict(opts)
    if cookie_browser:
        opts["cookiesfrombrowser"] = (cookie_browser,)
    return opts


def extract_info_with_fallback(url, opts, preferred_cookie_browser=None):
    errors = []
    attempts = [None, *cookie_browser_candidates(preferred_cookie_browser)]

    for cookie_browser in attempts:
        try:
            with yt_dlp.YoutubeDL(add_cookie_option(opts, cookie_browser)) as ydl:
                info = ydl.extract_info(url, download=False)
                if info:
                    return info, cookie_browser
                raise RuntimeError("no extractable info returned")
        except Exception as exc:
            label = cookie_browser or "no-cookie"
            errors.append(f"{label}: {exc}")

    raise RuntimeError(" / ".join(errors))


def base_ydl_opts(**overrides):
    opts = {
        "quiet": True,
        "ignoreerrors": True,
        "js_runtimes": {"node": {"path": NODE_PATH}},
    }
    opts.update(overrides)
    return opts


def get_info(url, preferred_cookie_browser=None):
    return extract_info_with_fallback(
        url,
        base_ydl_opts(noplaylist=True),
        preferred_cookie_browser=preferred_cookie_browser,
    )



def is_collection_like_url(url):
    lower_url = (url or "").lower()
    return any(
        token in lower_url
        for token in [
            "playlist?",
            "list=",
            "/@",
            "/channel/",
            "/c/",
            "/user/",
            "/feed/",
        ]
    )

def normalize_collection_url(url):
    lower_url = url.lower()
    if "youtube.com" not in lower_url and "youtu.be" not in lower_url:
        return url

    if any(token in lower_url for token in ["/watch", "playlist?", "/feed/", "/shorts/"]):
        return url

    channel_markers = ["youtube.com/@", "youtube.com/channel/", "youtube.com/c/", "youtube.com/user/"]
    if any(marker in lower_url for marker in channel_markers):
        base_url = url.split("?")[0].split("#")[0]
        if any(tab in lower_url for tab in ["/videos", "/streams", "/shorts", "/playlists"]):
            return base_url
        return base_url.rstrip("/") + "/videos"

    return url


def entry_to_url(entry):
    if not entry:
        return None

    webpage_url = entry.get("webpage_url") or entry.get("original_url")
    if webpage_url:
        return webpage_url

    raw_url = entry.get("url")
    if raw_url and raw_url.startswith("http"):
        return raw_url
    if raw_url and raw_url.startswith("/"):
        return "https://www.youtube.com" + raw_url
    if raw_url and raw_url.startswith("watch?"):
        return "https://www.youtube.com/" + raw_url

    video_id = entry.get("id") or raw_url
    if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", str(video_id)):
        return f"https://www.youtube.com/watch?v={video_id}"

    return None


def expand_input_url(url):
    collection_url = normalize_collection_url(url)
    opts = base_ydl_opts(
        extract_flat=True,
        noplaylist=False,
        skip_download=True,
    )

    try:
        info, cookie_browser = extract_info_with_fallback(collection_url, opts)
    except Exception as exc:
        if is_collection_like_url(url):
            print(f"一覧URLの展開に失敗したためスキップします: {url}")
            print(f"詳細: {exc}")
            return []
        print(f"URL展開に失敗したため単体URLとして扱います: {url}")
        print(f"詳細: {exc}")
        return [{"url": url, "cookie_browser": None}]

    entries = list(info.get("entries") or []) if isinstance(info, dict) else []
    if not entries:
        if is_collection_like_url(collection_url):
            print(f"一覧URLから動画を見つけられなかったためスキップします: {url}")
            return []
        return [{"url": url, "cookie_browser": cookie_browser}]

    expanded = []
    for entry in entries:
        video_url = entry_to_url(entry)
        if video_url:
            expanded.append({"url": video_url, "cookie_browser": cookie_browser})

    if expanded:
        title = info.get("title") or collection_url
        print(f"展開: {title} -> {len(expanded)} 件")
        return expanded

    return [{"url": url, "cookie_browser": cookie_browser}]


def expand_all_urls(input_urls):
    seen = set()
    expanded_urls = []

    for input_url in input_urls:
        for item in expand_input_url(input_url):
            url = item["url"]
            if url in seen:
                continue
            seen.add(url)
            expanded_urls.append(item)

    print(f"\n処理対象: {len(expanded_urls)} 件")
    return expanded_urls


def split_streams(info):
    videos = []
    audios = []
    combined = []

    for fmt in info.get("formats", []):
        has_video = fmt.get("vcodec") != "none"
        has_audio = fmt.get("acodec") != "none"

        if has_video and not has_audio:
            videos.append(fmt)
        elif has_audio and not has_video:
            audios.append(fmt)
        elif has_video and has_audio:
            combined.append(fmt)

    return videos, audios, combined


def video_sort_key(fmt):
    return (
        fmt.get("height") or 0,
        fmt.get("width") or 0,
        fmt.get("fps") or 0,
        fmt.get("tbr") or 0,
        fmt.get("filesize") or fmt.get("filesize_approx") or 0,
    )


def audio_sort_key(fmt):
    return (
        fmt.get("abr") or 0,
        fmt.get("asr") or 0,
        fmt.get("audio_channels") or 0,
        fmt.get("filesize") or fmt.get("filesize_approx") or 0,
    )


def combined_sort_key(fmt):
    return (
        fmt.get("height") or 0,
        fmt.get("width") or 0,
        fmt.get("fps") or 0,
        fmt.get("tbr") or 0,
        fmt.get("abr") or 0,
        fmt.get("filesize") or fmt.get("filesize_approx") or 0,
    )


def build_video_rows(info):
    videos, _, _ = split_streams(info)
    videos.sort(key=video_sort_key, reverse=True)

    rows = []
    seen_codecs = set()
    for number, fmt in enumerate(videos, 1):
        codec_family = codec_family_from_vcodec(fmt.get("vcodec"))
        codec_best = codec_family not in seen_codecs
        seen_codecs.add(codec_family)
        rows.append(
            {
                "number": number,
                "format": fmt,
                "compatible": is_mp4_compatible_video(fmt),
                "codec_best": codec_best,
            }
        )
    return rows


def build_audio_rows(info):
    _, audios, _ = split_streams(info)
    audios.sort(key=audio_sort_key, reverse=True)

    rows = []
    for number, fmt in enumerate(audios, 1):
        rows.append(
            {
                "number": number,
                "format": fmt,
                "compatible": is_mp4_compatible_audio(fmt),
            }
        )
    return rows


def build_combined_rows(info):
    _, _, combined = split_streams(info)
    combined.sort(key=combined_sort_key, reverse=True)

    rows = []
    for number, fmt in enumerate(combined, 1):
        rows.append({"number": number, "format": fmt})
    return rows


def choose_auto_video(video_rows):
    for row in video_rows:
        if row["compatible"]:
            return row
    return None


def choose_auto_audio(audio_rows):
    for row in audio_rows:
        if row["compatible"]:
            return row
    return None



def get_file_size(fmt):
    return fmt.get("filesize") or fmt.get("filesize_approx") or 0


def get_video_bitrate(fmt):
    return fmt.get("tbr") or fmt.get("vbr") or 0


def get_audio_bitrate(fmt):
    return fmt.get("abr") or fmt.get("tbr") or 0


def codec_family_from_vcodec(vcodec):
    value = (vcodec or "").lower()
    if value.startswith("av01"):
        return "AV1"
    if value.startswith("vp9"):
        return "VP9"
    if value.startswith("avc"):
        return "H.264"
    if value.startswith("hev") or value.startswith("hvc"):
        return "H.265"
    return "OTHER"


def codec_family_from_acodec(acodec):
    value = (acodec or "").lower()
    if value.startswith("opus"):
        return "OPUS"
    if value.startswith("mp4a"):
        return "AAC"
    return "OTHER"


def is_hdr_format(fmt):
    text = " ".join(
        str(fmt.get(key) or "")
        for key in ["dynamic_range", "format_note", "format", "color_transfer", "color_primaries"]
    ).lower()
    return any(token in text for token in ["hdr", "hlg", "pq", "smpte2084", "bt2020"])


def archive_video_score(fmt):
    width = fmt.get("width") or 0
    height = fmt.get("height") or 0
    pixels = width * height
    fps = fmt.get("fps") or 0
    hdr_score = 1 if is_hdr_format(fmt) else 0
    codec_family = codec_family_from_vcodec(fmt.get("vcodec"))
    bitrate = get_video_bitrate(fmt)
    effective_bitrate = bitrate * VIDEO_CODEC_EFFICIENCY.get(codec_family, VIDEO_CODEC_EFFICIENCY["OTHER"])

    return (
        pixels,
        fps,
        hdr_score,
        effective_bitrate,
        bitrate,
        get_file_size(fmt),
        VIDEO_CODEC_PREFERENCE.get(codec_family, VIDEO_CODEC_PREFERENCE["OTHER"]),
    )


def archive_audio_score(fmt):
    codec_family = codec_family_from_acodec(fmt.get("acodec"))
    bitrate = get_audio_bitrate(fmt)
    effective_bitrate = bitrate * AUDIO_CODEC_EFFICIENCY.get(codec_family, AUDIO_CODEC_EFFICIENCY["OTHER"])

    return (
        fmt.get("audio_channels") or 0,
        effective_bitrate,
        bitrate,
        fmt.get("asr") or 0,
        get_file_size(fmt),
        AUDIO_CODEC_PREFERENCE.get(codec_family, AUDIO_CODEC_PREFERENCE["OTHER"]),
    )


def select_archive_streams(info):
    videos, audios, combined = split_streams(info)
    video_candidates = [fmt for fmt in videos if fmt.get("format_id") and fmt.get("height")]
    audio_candidates = [fmt for fmt in audios if fmt.get("format_id")]

    selected_video = max(video_candidates, key=archive_video_score) if video_candidates else None
    selected_audio = max(audio_candidates, key=archive_audio_score) if audio_candidates else None

    if selected_video and selected_audio:
        return {
            "mode": "separate",
            "format_selector": f"{selected_video['format_id']}+{selected_audio['format_id']}",
            "video": selected_video,
            "audio": selected_audio,
            "combined": None,
            "video_score": archive_video_score(selected_video),
            "audio_score": archive_audio_score(selected_audio),
        }

    combined_candidates = [fmt for fmt in combined if fmt.get("format_id") and fmt.get("height")]
    selected_combined = max(combined_candidates, key=combined_sort_key) if combined_candidates else None
    if selected_combined:
        return {
            "mode": "combined",
            "format_selector": str(selected_combined["format_id"]),
            "video": None,
            "audio": None,
            "combined": selected_combined,
            "video_score": None,
            "audio_score": None,
        }

    return None


def describe_video_format(fmt):
    if not fmt:
        return "none"
    width = fmt.get("width") or "?"
    height = fmt.get("height") or "?"
    fps = fmt.get("fps") or "?"
    codec = simplify_vcodec(fmt.get("vcodec"))
    bitrate = int(get_video_bitrate(fmt) or 0)
    hdr = "HDR" if is_hdr_format(fmt) else "SDR"
    return f"format_id={fmt.get('format_id')} {width}x{height} {fps}fps {hdr} {codec} {bitrate}kbps"


def describe_audio_format(fmt):
    if not fmt:
        return "none"
    codec = simplify_acodec(fmt.get("acodec"))
    bitrate = int(get_audio_bitrate(fmt) or 0)
    asr = fmt.get("asr") or "?"
    channels = fmt.get("audio_channels") or "?"
    return f"format_id={fmt.get('format_id')} {codec} {bitrate}kbps {asr}Hz {channels}ch"


def show_archive_selection(selection):
    print("\n=== ARCHIVE MKV AUTO SELECTION ===")
    print("Algorithm: resolution pixels -> fps -> HDR -> codec-adjusted bitrate -> raw bitrate -> size")
    print("Video codec multipliers: AV1=1.35, H.265=1.25, VP9=1.15, H.264=1.00")
    print("Audio algorithm: channels -> codec-adjusted bitrate -> raw bitrate -> sample rate")

    if not selection:
        print("Archive selection: none")
        return

    if selection["mode"] == "separate":
        video = selection["video"]
        audio = selection["audio"]
        print(f"Archive video: {describe_video_format(video)}")
        print(f"Archive audio: {describe_audio_format(audio)}")
        print(f"Archive format selector: {selection['format_selector']}")
        print(
            "Archive video score: "
            f"pixels={selection['video_score'][0]} fps={selection['video_score'][1]} "
            f"hdr={selection['video_score'][2]} effective_bitrate={selection['video_score'][3]:.1f}"
        )
        return

    combined = selection["combined"]
    print(f"Archive combined fallback: {describe_video_format(combined)} / {describe_audio_format(combined)}")
    print(f"Archive format selector: {selection['format_selector']}")
def show_combined_table(combined_rows):
    if not combined_rows:
        return

    print("\n=== MUXED STREAMS ===")
    print("No  ID     Resolution   FPS  Video   Audio   Bitrate")
    print("-" * 62)

    for row in combined_rows:
        fmt = row["format"]
        width = fmt.get("width")
        height = fmt.get("height")
        resolution = f"{width}x{height}" if width and height else "?"
        bitrate = int(fmt.get("tbr") or 0)
        print(
            f"{row['number']:<3} {str(fmt.get('format_id') or '?'):<6} {resolution:<12} "
            f"{fmt.get('fps') or '?':<4} {simplify_vcodec(fmt.get('vcodec')):<7} "
            f"{simplify_acodec(fmt.get('acodec')):<7} {bitrate}k"
        )

def show_stream_table(video_rows, audio_rows, selected_video_row, selected_audio_row):
    print("\n=== VIDEO-ONLY STREAMS ===")
    print("No  ID     Resolution   FPS  Codec   Bitrate  Mark")
    print("-" * 61)

    for row in video_rows:
        fmt = row["format"]
        width = fmt.get("width")
        height = fmt.get("height")
        resolution = f"{width}x{height}" if width and height else "?"
        bitrate = int(fmt.get("tbr") or fmt.get("vbr") or 0)
        marks = []
        if row.get("codec_best"):
            marks.append("codec-best")
        if selected_video_row and row["number"] == selected_video_row["number"]:
            marks.append("MP4-auto")
        print(
            f"{row['number']:<3} {str(fmt.get('format_id') or '?'):<6} {resolution:<12} "
            f"{fmt.get('fps') or '?':<4} {simplify_vcodec(fmt.get('vcodec')):<7} "
            f"{bitrate:<7} {'/'.join(marks)}"
        )

    print("\n=== AUDIO-ONLY STREAMS ===")
    print("No  ID     Codec   Bitrate  Hz     Ch  Mark")
    print("-" * 54)

    for row in audio_rows:
        fmt = row["format"]
        bitrate = int(fmt.get("abr") or fmt.get("tbr") or 0)
        mark = "MP4-auto" if selected_audio_row and row["number"] == selected_audio_row["number"] else ""
        print(
            f"{row['number']:<3} {str(fmt.get('format_id') or '?'):<6} "
            f"{simplify_acodec(fmt.get('acodec')):<7} {bitrate:<7} "
            f"{fmt.get('asr') or '?':<6} {fmt.get('audio_channels') or '?':<3} {mark}"
        )

def get_thumb_ext(url):
    ext = url.split("?")[0].split(".")[-1].lower()
    if re.fullmatch(r"[a-z0-9]{2,5}", ext):
        return ext
    return "jpg"


def fetch_thumbnail(sort_index, thumb, folder):
    url = thumb.get("url")
    if not url:
        return None

    ext = get_thumb_ext(url)
    temp_path = os.path.join(folder, f"_tmp_{sort_index}.{ext}")

    try:
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            return None

        with open(temp_path, "wb") as file_obj:
            file_obj.write(response.content)

        return {
            "sort_index": sort_index,
            "path": temp_path,
            "width": thumb.get("width"),
            "height": thumb.get("height"),
            "ext": ext,
            "file_size": os.path.getsize(temp_path),
        }
    except (OSError, requests.RequestException):
        return None


def download_thumbs(info, folder):
    os.makedirs(folder, exist_ok=True)

    thumbs = list(info.get("thumbnails") or [])
    thumbs.sort(
        key=lambda item: (
            item.get("height") or 0,
            item.get("width") or 0,
            item.get("preference") or 0,
        ),
        reverse=True,
    )

    if not thumbs:
        return []

    downloaded = []
    max_workers = min(THUMB_DOWNLOAD_WORKERS, len(thumbs))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(fetch_thumbnail, index, thumb, folder)
            for index, thumb in enumerate(thumbs, 1)
        ]

        for future in as_completed(futures):
            result = future.result()
            if result:
                downloaded.append(result)

    downloaded.sort(
        key=lambda item: (
            item.get("file_size") or 0,
            item.get("height") or 0,
            item.get("width") or 0,
        ),
        reverse=True,
    )

    results = []
    for number, thumb in enumerate(downloaded, 1):
        new_path = os.path.join(folder, f"{number:03d}_{format_size(thumb['file_size'])}.{thumb['ext']}")
        if thumb["path"] != new_path:
            os.replace(thumb["path"], new_path)

        results.append(
            {
                "number": number,
                "path": new_path,
                "filename": os.path.basename(new_path),
                "width": thumb.get("width"),
                "height": thumb.get("height"),
                "ext": thumb.get("ext"),
                "file_size": thumb.get("file_size"),
            }
        )

    return results


def show_thumbs(thumbs, folder):
    print("\n=== THUMBNAILS ===")
    print(f"保存先: {folder}")
    print("No  File               Res        Size      Type")
    print("-" * 64)

    for thumb in thumbs:
        width = thumb.get("width")
        height = thumb.get("height")
        resolution = f"{width}x{height}" if width and height else "?"
        print(
            f"{thumb['number']:<3} {thumb['filename']:<18} {resolution:<10} "
            f"{format_size(thumb.get('file_size')):<8} {thumb.get('ext')}"
        )


def open_thumb_folder(folder):
    try:
        subprocess.Popen(["explorer.exe", folder])
        ps_folder = folder.replace("'", "''")
        script = f"""
$path = '{ps_folder}'
Start-Sleep -Milliseconds 800
$shell = New-Object -ComObject Shell.Application
foreach ($window in $shell.Windows()) {{
    try {{
        if ($window.Document.Folder.Self.Path -eq $path) {{
            $window.Document.CurrentViewMode = 1
            $window.Document.IconSize = 256
            try {{ $window.Document.SortColumns = 'prop:-System.Size;' }} catch {{}}
        }}
    }} catch {{}}
}}
"""
        subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except OSError:
        return False


def convert_to_jpg(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in [".jpg", ".jpeg"]:
        return path

    out = os.path.splitext(path)[0] + ".jpg"
    result = subprocess.run(
        [FFMPEG_PATH, "-y", "-i", path, "-q:v", "2", out],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    if result.returncode != 0 or not os.path.exists(out):
        return None

    return out


def canonical_video_url(info):
    video_id = info.get("id")
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return info.get("webpage_url") or info.get("original_url") or ""


def list_text(value):
    if not value:
        return ""
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(item) for item in value if item not in (None, ""))
    return str(value)


def archive_metadata_snapshot(info, archive_selection):
    sanitized = yt_dlp.YoutubeDL.sanitize_info(info)
    sanitized["archive"] = {
        "downloaded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "canonical_video_url": canonical_video_url(info),
        "selected_mode": archive_selection.get("mode") if archive_selection else None,
        "selected_format": archive_selection.get("format_selector") if archive_selection else None,
        "selected_video": archive_selection.get("video") if archive_selection else None,
        "selected_audio": archive_selection.get("audio") if archive_selection else None,
        "selected_combined": archive_selection.get("combined") if archive_selection else None,
    }
    return yt_dlp.YoutubeDL.sanitize_info(sanitized)


def metadata_args(info):
    upload_date = info.get("upload_date") or ""
    formatted_date = format_date(upload_date)
    downloaded_at = datetime.now().astimezone().isoformat(timespec="seconds")
    canonical_url = canonical_video_url(info)
    subtitle_languages = sorted((info.get("subtitles") or {}).keys())
    automatic_caption_languages = sorted((info.get("automatic_captions") or {}).keys())
    chapters = info.get("chapters") or []

    pairs = {
        "title": info.get("title", ""),
        "artist": info.get("channel") or info.get("uploader") or "",
        "author": info.get("channel") or info.get("uploader") or "",
        "creator": info.get("channel") or info.get("uploader") or "",
        "album_artist": info.get("channel") or info.get("uploader") or "",
        "date": formatted_date,
        "description": info.get("description", ""),
        "synopsis": info.get("description", ""),
        "comment": canonical_url,
        "purl": canonical_url,
        "encoder": "yt-dlp + ffmpeg",
        "youtube_id": info.get("id", ""),
        "canonical_url": canonical_url,
        "channel": info.get("channel", ""),
        "channel_id": info.get("channel_id", ""),
        "channel_url": info.get("channel_url", ""),
        "uploader": info.get("uploader", ""),
        "uploader_id": info.get("uploader_id", ""),
        "upload_date": upload_date,
        "upload_date_display": upload_date[:4] + "/" + upload_date[4:6] + "/" + upload_date[6:8] if len(upload_date) == 8 else upload_date,
        "release_date": info.get("release_date", ""),
        "downloaded_at": downloaded_at,
        "duration_seconds": info.get("duration", ""),
        "age_limit": info.get("age_limit", ""),
        "availability": info.get("availability", ""),
        "license": info.get("license", ""),
        "language": info.get("language", ""),
        "tags": list_text(info.get("tags")),
        "categories": list_text(info.get("categories")),
        "genres": list_text(info.get("genres")),
        "track": info.get("track", ""),
        "track_number": info.get("track_number", ""),
        "artists": list_text(info.get("artists") or info.get("creators")),
        "album": info.get("album", ""),
        "release_year": info.get("release_year", ""),
        "chapter_count": len(chapters),
        "subtitle_languages": list_text(subtitle_languages),
        "automatic_caption_languages": list_text(automatic_caption_languages),
        "view_count_at_download": info.get("view_count", ""),
        "like_count_at_download": info.get("like_count", ""),
        "comment_count_at_download": info.get("comment_count", ""),
    }

    args = []
    for key, value in pairs.items():
        if value in (None, ""):
            continue
        text = str(value).replace("\0", "")
        limit = 4000 if key in {"description", "synopsis"} else 1200
        args.extend(["-metadata", f"{key}={text[:limit]}"])
    return args

def mp4_metadata_args(info):
    pairs = {
        "title": info.get("title", ""),
        "artist": info.get("uploader", ""),
        "date": format_date(info.get("upload_date")),
        "comment": canonical_video_url(info),
    }

    args = []
    for key, value in pairs.items():
        if value not in (None, ""):
            args.extend(["-metadata", f"{key}={str(value)[:1200]}"])
    return args

def download_mp4(url, video_format_id, audio_format_id, title, cookie_browser=None):
    outtmpl = os.path.join(VIDEO_DIR, f"{title}.mp4")

    ydl_opts = base_ydl_opts(
        format=f"{video_format_id}+{audio_format_id}",
        outtmpl=outtmpl,
        merge_output_format="mp4",
        noplaylist=True,
        concurrent_fragment_downloads=FRAGMENT_DOWNLOADS,
    )
    ydl_opts = add_cookie_option(ydl_opts, cookie_browser)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    if not os.path.exists(outtmpl):
        return None

    return outtmpl


def embed_thumb_mp4(mp4_path, jpg_path, info):
    temp = mp4_path + ".tmp.mp4"
    cmd = [
        FFMPEG_PATH,
        "-y",
        "-i",
        mp4_path,
        "-i",
        jpg_path,
        "-map",
        "0:v",
        "-map",
        "0:a?",
        "-map",
        "1",
        "-c",
        "copy",
        "-disposition:v:1",
        "attached_pic",
        *mp4_metadata_args(info),
        temp,
    ]

    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode != 0 or not os.path.exists(temp):
        return False

    os.replace(temp, mp4_path)
    return True


def find_mkv_file(folder, title):
    expected = os.path.join(folder, f"{title}.mkv")
    if os.path.exists(expected):
        return expected

    mkv_files = [
        os.path.join(folder, name)
        for name in os.listdir(folder)
        if name.lower().endswith(".mkv")
    ]
    if not mkv_files:
        return None

    mkv_files.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    return mkv_files[0]


def remux_mkv_metadata(mkv_path, jpg_path, info, archive_selection):
    temp = mkv_path + ".tmp.mkv"
    metadata_json_path = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".json",
            prefix="youtube_metadata_",
            delete=False,
        ) as file_obj:
            json.dump(
                archive_metadata_snapshot(info, archive_selection),
                file_obj,
                ensure_ascii=False,
                indent=2,
            )
            metadata_json_path = file_obj.name

        cmd = [
            FFMPEG_PATH,
            "-y",
            "-i",
            mkv_path,
            "-map",
            "0",
            "-c",
            "copy",
            "-attach",
            jpg_path,
            "-metadata:s:t",
            "mimetype=image/jpeg",
            "-metadata:s:t",
            "filename=cover.jpg",
            "-attach",
            metadata_json_path,
            "-metadata:s:t:1",
            "mimetype=application/json",
            "-metadata:s:t:1",
            "filename=youtube_metadata.json",
            *metadata_args(info),
            temp,
        ]

        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode != 0 or not os.path.exists(temp):
            return False

        os.replace(temp, mkv_path)
        return True
    finally:
        if metadata_json_path:
            try:
                os.remove(metadata_json_path)
            except OSError:
                pass
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass

def cleanup_archive_sidecars(archive_folder):
    if not os.path.isdir(archive_folder):
        return

    removable_names = {"archive_stream_selection.json", "metadata_summary.txt"}
    removable_suffixes = (".info.json", ".description")

    for name in os.listdir(archive_folder):
        lower_name = name.lower()
        if name in removable_names or lower_name.endswith(removable_suffixes):
            try:
                os.remove(os.path.join(archive_folder, name))
            except OSError:
                pass
def download_archive_mkv(url, title, info, jpg_path, archive_folder, archive_selection, cookie_browser=None):
    os.makedirs(archive_folder, exist_ok=True)
    cleanup_archive_sidecars(archive_folder)
    cover_path = os.path.join(archive_folder, "cover.jpg")
    shutil.copy2(jpg_path, cover_path)

    outtmpl = os.path.join(archive_folder, f"{title}.%(ext)s")
    postprocessors = [
        {"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"},
        {"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False},
        {"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True, "add_infojson": False},
    ]
    ydl_opts = base_ydl_opts(
        format=archive_selection["format_selector"],
        outtmpl=outtmpl,
        merge_output_format="mkv",
        noplaylist=True,
        concurrent_fragment_downloads=FRAGMENT_DOWNLOADS,
        keepvideo=KEEP_ARCHIVE_RAW_STREAMS,
        writesubtitles=True,
        writeautomaticsub=True,
        subtitleslangs=["all", "-live_chat"],
        postprocessors=postprocessors,
    )
    ydl_opts = add_cookie_option(ydl_opts, cookie_browser)

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    mkv_path = find_mkv_file(archive_folder, title)
    if not mkv_path:
        return None
    if not remux_mkv_metadata(mkv_path, cover_path, info, archive_selection):
        return None
    cleanup_archive_sidecars(archive_folder)
    return mkv_path

def start_worker(result_box, func, *args, **kwargs):
    def worker():
        try:
            result_box["path"] = func(*args, **kwargs)
        except Exception as exc:
            result_box["error"] = str(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return thread


def cleanup_folder(path):
    shutil.rmtree(path, ignore_errors=True)


def prepare_job(item, item_index, total_items):
    url = item["url"]
    preferred_cookie_browser = item.get("cookie_browser")
    print(f"\n[{item_index}/{total_items}] 動画情報を取得しています...")

    try:
        info, cookie_browser = get_info(url, preferred_cookie_browser=preferred_cookie_browser)
    except Exception as exc:
        print(f"[{item_index}/{total_items}] 動画情報の取得に失敗しました: {exc}")
        return None

    if not info:
        print(f"[{item_index}/{total_items}] 動画情報の取得に失敗しました。")
        return None

    title = safe_filename(info.get("title", "video"))
    archive_title = safe_filename(f"{title[:84]} [{info.get('id', '')}]" if info.get("id") else title)
    thumb_folder = unique_folder(os.path.join(THUMB_DIR, f"{item_index:03d}_{title}"))
    archive_folder = os.path.join(ARCHIVE_DIR, archive_title)

    combined_rows = build_combined_rows(info)
    video_rows = build_video_rows(info)
    audio_rows = build_audio_rows(info)
    selected_video_row = choose_auto_video(video_rows)
    selected_audio_row = choose_auto_audio(audio_rows)

    if not selected_video_row:
        print(f"[{item_index}/{total_items}] H.264 / mp4 の動画ストリームが見つかりません。")
        cleanup_folder(thumb_folder)
        return None

    if not selected_audio_row:
        print(f"[{item_index}/{total_items}] AAC / m4a の音声ストリームが見つかりません。")
        cleanup_folder(thumb_folder)
        return None


    print(f"[{item_index}/{total_items}] サムネイルを取得しています...")
    thumbs = download_thumbs(info, thumb_folder)
    if not thumbs:
        print(f"[{item_index}/{total_items}] 取得できるサムネイルがありません。")
        cleanup_folder(thumb_folder)
        return None

    return {
        "item_index": item_index,
        "total_items": total_items,
        "url": url,
        "info": info,
        "cookie_browser": cookie_browser,
        "title": title,
        "thumb_folder": thumb_folder,
        "archive_folder": archive_folder,
        "combined_rows": combined_rows,
        "video_rows": video_rows,
        "audio_rows": audio_rows,
        "selected_video_row": selected_video_row,
        "selected_audio_row": selected_audio_row,
        "thumbs": thumbs,
    }



def choose_manual_archive_streams(job):
    video_map = {row["number"]: row["format"] for row in job["video_rows"]}
    audio_map = {row["number"]: row["format"] for row in job["audio_rows"]}
    muxed_map = {row["number"]: row["format"] for row in job["combined_rows"]}

    print("\n=== MKV MODE ===")
    print("0: MKVを作らない")
    print("1: VIDEO-ONLY + AUDIO-ONLYを自由に組み合わせる")
    print("2: MUXEDストリームをそのままMKVへ収納する")
    mode = ask_int("MKV mode: ", {0, 1, 2})

    if mode == 0:
        return None

    if mode == 2:
        if not muxed_map:
            print("MUXEDストリームがないため、個別選択へ切り替えます。")
            mode = 1
        else:
            muxed_number = ask_int("MKV muxed No: ", muxed_map.keys())
            selected_muxed = muxed_map[muxed_number]
            print(
                f"MKV muxed: No.{muxed_number} "
                f"{describe_video_format(selected_muxed)} / {describe_audio_format(selected_muxed)}"
            )
            return {
                "mode": "muxed",
                "format_selector": str(selected_muxed["format_id"]),
                "video": None,
                "audio": None,
                "combined": selected_muxed,
                "muxed_number": muxed_number,
            }

    video_number = ask_int("MKV video No: ", video_map.keys())
    audio_number = ask_int("MKV audio No: ", audio_map.keys())
    selected_video = video_map[video_number]
    selected_audio = audio_map[audio_number]
    print(f"MKV video: No.{video_number} {describe_video_format(selected_video)}")
    print(f"MKV audio: No.{audio_number} {describe_audio_format(selected_audio)}")
    return {
        "mode": "separate",
        "format_selector": f"{selected_video['format_id']}+{selected_audio['format_id']}",
        "video": selected_video,
        "audio": selected_audio,
        "combined": None,
        "video_number": video_number,
        "audio_number": audio_number,
    }

def show_job_and_choose_thumbnail(job):
    print(f"\n[{job['item_index']}/{job['total_items']}] {job['title']}")
    show_combined_table(job["combined_rows"])
    show_stream_table(
        job["video_rows"],
        job["audio_rows"],
        job["selected_video_row"],
        job["selected_audio_row"],
    )

    selected_video = job["selected_video_row"]["format"]
    selected_audio = job["selected_audio_row"]["format"]
    print(
        "\n自動選択: "
        f"video No.{job['selected_video_row']['number']} (format_id={selected_video.get('format_id')}) / "
        f"audio No.{job['selected_audio_row']['number']} (format_id={selected_audio.get('format_id')})"
    )

    show_thumbs(job["thumbs"], job["thumb_folder"])
    if open_thumb_folder(job["thumb_folder"]):
        print("サムネイル保存フォルダをエクスプローラーで開きました。")
    else:
        print("エクスプローラーを開けなかったため、保存先を直接確認してください。")

    thumb_numbers = {thumb["number"] for thumb in job["thumbs"]}
    selected_thumb_number = ask_int("\nサムネイル番号: ", thumb_numbers)
    selected_thumb = next(
        thumb for thumb in job["thumbs"] if thumb["number"] == selected_thumb_number
    )

    jpg_path = convert_to_jpg(selected_thumb["path"])
    if not jpg_path:
        print(f"[{job['item_index']}/{job['total_items']}] サムネイルの JPEG 変換に失敗しました。")
        cleanup_folder(job["thumb_folder"])
        return False

    job["selected_video"] = selected_video
    job["selected_audio"] = selected_audio
    job["jpg_path"] = jpg_path
    return True


def start_job_download(job):
    job["mp4_result"] = {"path": None, "error": None}
    job["archive_result"] = {"path": None, "error": None, "skipped": False}

    job["mp4_thread"] = start_worker(
        job["mp4_result"],
        download_mp4,
        job["url"],
        job["selected_video"]["format_id"],
        job["selected_audio"]["format_id"],
        job["title"],
        cookie_browser=job.get("cookie_browser"),
    )
    print(f"[{job['item_index']}/{job['total_items']}] H.264 + AAC のMP4ダウンロードを開始しました。")

    job["archive_selection"] = choose_manual_archive_streams(job)
    if job["archive_selection"] is None:
        job["archive_result"]["skipped"] = True
        job["archive_thread"] = None
        print(f"[{job['item_index']}/{job['total_items']}] MKVは作成しません。")
        return

    job["archive_thread"] = start_worker(
        job["archive_result"],
        download_archive_mkv,
        job["url"],
        job["title"],
        job["info"],
        job["jpg_path"],
        job["archive_folder"],
        job["archive_selection"],
        cookie_browser=job.get("cookie_browser"),
    )
    print(f"[{job['item_index']}/{job['total_items']}] 選択したストリームでMKVダウンロードを開始しました。")

def job_is_alive(job):
    mp4_alive = job["mp4_thread"].is_alive()
    archive_thread = job.get("archive_thread")
    archive_alive = archive_thread.is_alive() if archive_thread else False
    return mp4_alive or archive_alive

def finalize_job(job):
    job["mp4_thread"].join()
    if job.get("archive_thread"):
        job["archive_thread"].join()

    mp4_path = job["mp4_result"]["path"]
    if job["mp4_result"]["error"]:
        print(
            f"[{job['item_index']}/{job['total_items']}] MP4ダウンロードに失敗しました: "
            f"{job['mp4_result']['error']}"
        )
    elif not mp4_path:
        print(f"[{job['item_index']}/{job['total_items']}] MP4ダウンロードに失敗しました。")
    elif embed_thumb_mp4(mp4_path, job["jpg_path"], job["info"]):
        print(f"[{job['item_index']}/{job['total_items']}] MP4完了: {mp4_path}")
    else:
        print(f"[{job['item_index']}/{job['total_items']}] MP4は完了しましたが、サムネイル埋め込みに失敗しました: {mp4_path}")

    archive_skipped = job["archive_result"].get("skipped", False)
    archive_path = job["archive_result"]["path"]
    if archive_skipped:
        print(f"[{job['item_index']}/{job['total_items']}] MKVスキップ")
    elif job["archive_result"]["error"]:
        print(
            f"[{job['item_index']}/{job['total_items']}] MKV作成に失敗しました: "
            f"{job['archive_result']['error']}"
        )
    elif not archive_path:
        print(f"[{job['item_index']}/{job['total_items']}] MKV作成に失敗しました。")
    else:
        print(f"[{job['item_index']}/{job['total_items']}] MKV完了: {archive_path}")

    archive_ok = archive_skipped or (archive_path and not job["archive_result"]["error"])
    if mp4_path and not job["mp4_result"]["error"] and archive_ok:
        remove_pending_url(job.get("url"))

    cleanup_folder(job["thumb_folder"])

def drain_completed_jobs(active_jobs):
    remaining_jobs = []

    for job in active_jobs:
        if job_is_alive(job):
            remaining_jobs.append(job)
        else:
            finalize_job(job)

    return remaining_jobs


def wait_for_download_slot(active_jobs):
    active_jobs = drain_completed_jobs(active_jobs)
    notified = False

    while len(active_jobs) >= MAX_CONCURRENT_DOWNLOADS:
        if not notified:
            print("同時ダウンロード上限に達したため、空きを待っています...")
            notified = True
        time.sleep(DOWNLOAD_POLL_SECONDS)
        active_jobs = drain_completed_jobs(active_jobs)

    return active_jobs


def wait_for_all_jobs(active_jobs):
    while active_jobs:
        time.sleep(DOWNLOAD_POLL_SECONDS)
        active_jobs = drain_completed_jobs(active_jobs)


def process_items(items):
    active_jobs = []
    total_items = len(items)

    for item_index, item in enumerate(items, 1):
        active_jobs = wait_for_download_slot(active_jobs)

        job = prepare_job(item, item_index, total_items)
        if not job:
            continue

        if not show_job_and_choose_thumbnail(job):
            active_jobs = drain_completed_jobs(active_jobs)
            continue

        start_job_download(job)
        active_jobs.append(job)
        active_jobs = drain_completed_jobs(active_jobs)

    if active_jobs:
        print("\n残りのダウンロード完了を待っています...")
        wait_for_all_jobs(active_jobs)


def main():
    pending_items = load_pending_items()
    if pending_items:
        print(f"\n前回未完了のURLが {len(pending_items)} 件あります。先に再開します。")
        process_items(pending_items)
        remaining = load_pending_items()
        if remaining:
            print(f"未完了URLが {len(remaining)} 件残っています。次回起動時に再試行します。")

    while True:
        input_urls = collect_urls()
        if not input_urls:
            print("終了します。")
            break

        expanded_items = expand_all_urls(input_urls)
        if not expanded_items:
            print("処理できるURLがありません。")
            continue

        save_pending_items(merge_pending_items(load_pending_items(), expanded_items))
        process_items(expanded_items)

        print("\nこのバッチの処理が完了しました。次のURL入力へ戻ります。")


if __name__ == "__main__":
    main()















