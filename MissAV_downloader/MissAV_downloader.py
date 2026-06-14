from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence
from urllib.parse import urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

try:
    from yt_dlp import YoutubeDL
    from yt_dlp.cookies import CookieLoadError, SUPPORTED_BROWSERS, SUPPORTED_KEYRINGS
    from yt_dlp.utils import DownloadError
except ImportError as exc:  # pragma: no cover - import guard
    raise SystemExit(
        "yt-dlp is required. Install it with: python -m pip install -U yt-dlp"
    ) from exc


SCRIPT_DIR = Path(__file__).resolve().parent
SINGLE_OUTPUT_DIR_NAME = "MissAV_download"
ALL_QUALITY_OUTPUT_DIR_NAME = "MissAV_all_quality"
PROGRAM_NAME = Path(sys.argv[0]).name
PROGRAM_STEM = Path(sys.argv[0]).stem.casefold()
ALL_QUALITY_MODE = "all_quality" in PROGRAM_STEM
DEFAULT_OUTPUT_DIR = Path.home() / "Downloads" / (ALL_QUALITY_OUTPUT_DIR_NAME if ALL_QUALITY_MODE else SINGLE_OUTPUT_DIR_NAME)
DEFAULT_OUTPUT_TEMPLATE = "%(title).180B.%(ext)s"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)
DEFAULT_FORMAT_SELECTOR = "bestvideo+bestaudio/best"
SUPPORTED_MEDIA_SUFFIXES = {
    ".m3u8",
    ".mp4",
    ".m4v",
    ".webm",
    ".mkv",
    ".mpd",
    ".ts",
}
SUPPORTED_PAGE_HOSTS = (
    "missav.live",
    "missav.ws",
    "missav.ai",
    "njavtv.com",
    "missav123.com",
)
METADATA_FALLBACK_HOSTS = (
    "njavtv.com",
    "missav123.com",
    "missav.ws",
    "missav.ai",
    "missav.live",
)
GENERIC_PAGE_TITLES = {
    "任意の検索 JAV",
    "MissAV | オンラインで無料ハイビジョンAV映画が見られる | 飽きるまで映画が存分に見られる",
    "nJAV | オンラインで無料ハイビジョンAV映画が見られる | 飽きるまで映画が存分に見られる",
}
GENERIC_STREAM_TITLES = {"video", "index", "playlist", "master"}
DIRECT_FFMPEG_PROTOCOLS = {"m3u8", "m3u8_native", "http", "https"}
DIRECT_FFMPEG_VIDEO_PREFIXES = ("avc", "h264", "hevc", "hvc1", "hev1", "av01", "av1")
DIRECT_FFMPEG_AUDIO_PREFIXES = ("aac", "mp4a", "ac-3", "ec-3")
COOKIE_BROWSER_PATTERN = re.compile(
    r"""(?x)
    (?P<name>[^+:]+)
    (?:\s*\+\s*(?P<keyring>[^:]+))?
    (?:\s*:\s*(?!:)(?P<profile>.+?))?
    (?:\s*::\s*(?P<container>.+))?
    """
)


@dataclass
class PageMetadata:
    title: str
    thumbnail_url: str | None
    source_url: str


@dataclass
class DownloadJob:
    page_url: str
    media_input: str


@dataclass
class DownloadStats:
    transfer_seconds: float | None = None
    average_speed_bps: float | None = None
    saved_path: Path | None = None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    description = (
        "Download every detected quality for media referenced by a page URL plus a direct m3u8/mp4 URL or browser Copy as cURL input."
        if ALL_QUALITY_MODE
        else "Download media referenced by a page URL plus a direct m3u8/mp4 URL or browser Copy as cURL input."
    )
    parser = argparse.ArgumentParser(
        description=description,
        epilog=(
            "Examples:\n"
            f"  python {PROGRAM_NAME} --page-url \"https://missav.live/ja/example\"\n"
            f"  python {PROGRAM_NAME} --page-url PAGE --curl-file request.txt\n"
            f"  python {PROGRAM_NAME} --page-url PAGE \"https://cdn.example.com/playlist.m3u8\""
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("urls", nargs="*", help="One direct media URL such as playlist.m3u8 or video.m3u8.")
    parser.add_argument("--page-url", metavar="URL", help="The watch page URL used to fetch title and thumbnail metadata.")
    parser.add_argument("-f", "--url-file", action="append", default=[], metavar="PATH", help="Read direct media URLs from a text file.")
    parser.add_argument("-o", "--output-dir", default=str(DEFAULT_OUTPUT_DIR), metavar="DIR", help=f"Directory where files are saved. Default: {DEFAULT_OUTPUT_DIR}")
    parser.add_argument("--filename", metavar="NAME", help="Optional output filename. If omitted, the page title is used.")
    parser.add_argument("--referer", metavar="URL", help="Optional Referer header. If omitted, the page URL is used.")
    parser.add_argument("--format", dest="format_selector", metavar="SELECTOR", help="yt-dlp format selector. If omitted, the script shows streams and prompts.")
    parser.add_argument("--header", action="append", default=[], metavar="KEY:VALUE", help="Add a custom HTTP header. Can be used multiple times.")
    parser.add_argument("--cookies-from-browser", "--browser", dest="cookies_from_browser", metavar="BROWSER[:PROFILE]", help=("Load login cookies from a browser profile. Supported browsers: " f"{', '.join(sorted(SUPPORTED_BROWSERS))}"))
    parser.add_argument("--cookies", metavar="FILE", help="Path to a Netscape-format cookies.txt file.")
    parser.add_argument("--curl-file", metavar="FILE", help="Path to a text file containing one browser 'Copy as cURL' command.")
    parser.add_argument("--proxy", metavar="URL", help="Optional proxy URL passed to yt-dlp.")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite an existing output file.")
    parser.add_argument("--dry-run", action="store_true", help="Resolve metadata and stream list only. No media is downloaded.")
    parser.add_argument("--auto-best", action="store_true", help="Skip the prompt and select the best stream automatically.")
    parser.add_argument("--no-thumbnail", action="store_true", help="Skip downloading and embedding the page thumbnail. This is faster on large files.")
    parser.add_argument("--sleep-between-jobs", type=float, default=0.0, metavar="SECONDS", help="Optional fixed pause after each completed job in interactive queue mode.")
    parser.add_argument("--slow-threshold-kib", type=float, default=700.0, metavar="KIB_PER_SEC", help="If the measured average transfer speed falls below this value, wait before the next queued job. Set 0 to disable. Default: 700")
    parser.add_argument("--slow-sleep-seconds", type=float, default=120.0, metavar="SECONDS", help="Pause length when a slow transfer is detected in interactive queue mode. Set 0 to disable. Default: 120")
    args = parser.parse_args(argv)

    if args.cookies and args.cookies_from_browser:
        parser.error("Use either --cookies or --cookies-from-browser, not both.")

    args.urls = collect_urls(args.urls, args.url_file)

    if args.curl_file:
        if args.urls:
            parser.error("Use either URLs/url-file or --curl-file, not both.")
        curl_path = Path(args.curl_file).expanduser()
        if not curl_path.is_file():
            parser.error(f"cURL file was not found: {curl_path}")
        apply_curl_command_to_args(args, read_text_file(curl_path))

    if args.filename and len(args.urls) > 1:
        parser.error("--filename can only be used when downloading one URL.")

    return args


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise SystemExit(f"Could not decode URL file: {path}")


def collect_urls(direct_urls: Sequence[str], url_files: Sequence[str]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add_url(raw_value: str) -> None:
        value = raw_value.strip()
        if not value or value.startswith("#") or value in seen:
            return
        seen.add(value)
        urls.append(value)

    for url in direct_urls:
        add_url(url)

    for file_name in url_files:
        path = Path(file_name).expanduser()
        if not path.is_file():
            raise SystemExit(f"URL file was not found: {path}")
        for line in read_text_file(path).splitlines():
            add_url(line)

    return urls

def sanitize_filename(value: str) -> str:
    trimmed = Path(value.strip()).name
    cleaned = "".join("_" if ch in '<>:"/\\|?*' or ord(ch) < 32 else ch for ch in trimmed)
    cleaned = cleaned.strip(" .")
    if cleaned in {"", ".", ".."}:
        raise ValueError("Filename must contain at least one visible character.")
    return cleaned


def build_output_template(filename: str | None) -> str:
    if not filename:
        return DEFAULT_OUTPUT_TEMPLATE
    safe_name = sanitize_filename(filename)
    stem = Path(safe_name).stem if Path(safe_name).suffix else Path(safe_name).name
    if not stem:
        raise ValueError("Filename must contain a base name before the extension.")
    return f"{stem}.%(ext)s"


def build_literal_output_template(title_text: str) -> str:
    return f"{sanitize_filename(title_text)}.%(ext)s"


def iter_ffmpeg_search_dirs() -> list[Path]:
    directories: list[Path] = []
    seen: set[Path] = set()
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass))
        candidates.append(Path(sys.executable).resolve().parent)

    candidates.append(SCRIPT_DIR)

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        directories.append(resolved)
    return directories


def find_ffmpeg_path() -> Path | None:
    for directory in iter_ffmpeg_search_dirs():
        for executable_name in ("ffmpeg.exe", "ffmpeg"):
            candidate = directory / executable_name
            if candidate.is_file():
                return candidate
    ffmpeg_path = shutil.which("ffmpeg")
    return Path(ffmpeg_path).resolve() if ffmpeg_path else None


def find_ffmpeg_location() -> str | None:
    ffmpeg_path = find_ffmpeg_path()
    return str(ffmpeg_path.parent) if ffmpeg_path else None


def resolve_ffmpeg_path() -> Path:
    ffmpeg_path = find_ffmpeg_path()
    if ffmpeg_path is None:
        raise ValueError(
            "ffmpeg was not found. Rebuild the exe with bundled ffmpeg or install ffmpeg and make sure it is available in PATH."
        )
    return ffmpeg_path


def normalize_header_key(value: str) -> str:
    parts = [segment for segment in value.strip().split("-") if segment]
    if not parts:
        raise ValueError("Header name cannot be empty.")
    return "-".join(part[:1].upper() + part[1:] for part in parts)


def parse_header_values(values: Sequence[str]) -> dict[str, str]:
    headers: dict[str, str] = {"User-Agent": DEFAULT_USER_AGENT}
    for raw_value in values:
        if ":" not in raw_value:
            raise ValueError(f"Invalid --header value: {raw_value!r}")
        key, value = raw_value.split(":", 1)
        normalized_key = normalize_header_key(key)
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError(f"Header {normalized_key!r} must have a value.")
        headers[normalized_key] = normalized_value
    return headers


def parse_browser_spec(value: str) -> tuple[str, str | None, str | None, str | None]:
    match = COOKIE_BROWSER_PATTERN.fullmatch(value.strip())
    if not match:
        raise ValueError("Invalid browser spec. Use BROWSER[:PROFILE] or BROWSER+KEYRING[:PROFILE][::CONTAINER].")

    browser_name, keyring, profile, container = match.group("name", "keyring", "profile", "container")
    browser_name = browser_name.strip().lower()
    if browser_name not in SUPPORTED_BROWSERS:
        supported = ", ".join(sorted(SUPPORTED_BROWSERS))
        raise ValueError(f'Unsupported browser "{browser_name}". Supported browsers: {supported}')

    normalized_keyring: str | None = None
    if keyring is not None:
        normalized_keyring = keyring.strip().upper()
        if normalized_keyring not in SUPPORTED_KEYRINGS:
            supported = ", ".join(sorted(SUPPORTED_KEYRINGS))
            raise ValueError(f'Unsupported keyring "{normalized_keyring}". Supported keyrings: {supported}')

    normalized_profile = profile.strip() if isinstance(profile, str) and profile.strip() else None
    normalized_container = container.strip() if isinstance(container, str) and container.strip() else None
    return browser_name, normalized_profile, normalized_keyring, normalized_container


def normalize_curl_text(value: str) -> str:
    text = value.strip()
    replacements = (
        ("\\\r\n", " "),
        ("\\\n", " "),
        ("^\r\n", " "),
        ("^\n", " "),
        ("`\r\n", " "),
        ("`\n", " "),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def parse_curl_command(value: str) -> dict[str, object]:
    text = normalize_curl_text(value)
    if not text:
        raise ValueError("The cURL command is empty.")
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError as error:
        raise ValueError(f"Could not parse the cURL command: {error}") from error
    if not tokens or tokens[0].lower() != "curl":
        raise ValueError("Expected a command copied with 'Copy as cURL'.")

    headers: list[str] = []
    url: str | None = None
    single_value_options = {"-A", "--user-agent", "-b", "--cookie", "-e", "--referer", "-H", "--header", "-X", "--request", "-o", "--output", "--url"}
    flag_only_options = {"--compressed", "-L", "--location", "--globoff", "-k", "--insecure", "-s", "--silent"}

    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-H", "--header"}:
            if index + 1 >= len(tokens):
                raise ValueError("The cURL command ended after a header option.")
            headers.append(tokens[index + 1])
            index += 2
            continue
        if token in {"-A", "--user-agent"}:
            if index + 1 >= len(tokens):
                raise ValueError("The cURL command ended after a user-agent option.")
            headers.append(f"User-Agent: {tokens[index + 1]}")
            index += 2
            continue
        if token in {"-b", "--cookie"}:
            if index + 1 >= len(tokens):
                raise ValueError("The cURL command ended after a cookie option.")
            headers.append(f"Cookie: {tokens[index + 1]}")
            index += 2
            continue
        if token in {"-e", "--referer"}:
            if index + 1 >= len(tokens):
                raise ValueError("The cURL command ended after a referer option.")
            headers.append(f"Referer: {tokens[index + 1]}")
            index += 2
            continue
        if token == "--url":
            if index + 1 >= len(tokens):
                raise ValueError("The cURL command ended after --url.")
            url = tokens[index + 1]
            index += 2
            continue
        if token.startswith("http://") or token.startswith("https://"):
            if url is None:
                url = token
            index += 1
            continue
        if token in single_value_options:
            index += 2
            continue
        if token in flag_only_options or token.startswith("--http"):
            index += 1
            continue
        index += 1

    if not url:
        raise ValueError("No URL was found in the cURL command.")
    return {"url": url, "headers": headers}


def apply_curl_command_to_args(args: argparse.Namespace, value: str) -> None:
    parsed = parse_curl_command(value)
    args.urls = collect_urls([str(parsed["url"])], [])
    args.header.extend(str(header) for header in parsed["headers"])
    if not args.referer:
        for header in parsed["headers"]:
            key, _, header_value = str(header).partition(":")
            if key.strip().casefold() == "referer":
                args.referer = header_value.strip()
                break


def validate_direct_media_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Only http/https URLs are supported: {url}")
    if not (parsed.hostname or "").strip("."):
        raise ValueError(f"Could not determine the hostname: {url}")
    suffix = Path(parsed.path).suffix.casefold()
    if suffix not in SUPPORTED_MEDIA_SUFFIXES:
        allowed = ", ".join(sorted(SUPPORTED_MEDIA_SUFFIXES))
        raise ValueError("This script only accepts direct media URLs, not webpage URLs. " f"Allowed suffixes: {allowed}. Rejected URL: {url}")


def resolve_output_dir(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = SCRIPT_DIR / path
    return path.resolve()


def is_usable_page_title(value: str | None) -> bool:
    if value is None:
        return False
    text = value.strip()
    if not text:
        return False
    return text not in GENERIC_PAGE_TITLES


def build_page_url_candidates(page_url: str) -> list[str]:
    parsed = urlparse(page_url)
    host = (parsed.hostname or "").lower()
    candidates: list[str] = []

    def rebuild(target_host: str) -> str:
        return urlunparse((parsed.scheme or "https", target_host, parsed.path, parsed.params, parsed.query, parsed.fragment))

    if host in SUPPORTED_PAGE_HOSTS:
        candidates.append(rebuild(host))
        for fallback_host in METADATA_FALLBACK_HOSTS:
            if fallback_host != host:
                candidates.append(rebuild(fallback_host))
    else:
        candidates.append(page_url)

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            deduped.append(candidate)
    return deduped


def get_meta_content(soup: BeautifulSoup, *, property_name: str | None = None, name: str | None = None) -> str | None:
    attrs: dict[str, str] = {}
    if property_name:
        attrs["property"] = property_name
    if name:
        attrs["name"] = name
    tag = soup.find("meta", attrs=attrs)
    if tag is None:
        return None
    content = tag.get("content")
    if content is None:
        return None
    text = str(content).strip()
    return text or None


def get_h1_text(soup: BeautifulSoup) -> str | None:
    tag = soup.find("h1", class_=re.compile("text-base|text-lg")) or soup.find("h1")
    if tag is None:
        return None
    text = tag.get_text(" ", strip=True)
    return text or None


def extract_page_metadata(html_text: str, source_url: str) -> PageMetadata | None:
    soup = BeautifulSoup(html_text, "html.parser")
    title_candidates = [get_meta_content(soup, property_name="og:title"), get_meta_content(soup, name="twitter:title"), get_h1_text(soup)]
    title = next((value.strip() for value in title_candidates if is_usable_page_title(value)), None)
    thumbnail = get_meta_content(soup, property_name="og:image") or get_meta_content(soup, name="twitter:image")
    if not title:
        return None
    return PageMetadata(title=title, thumbnail_url=thumbnail.strip() if thumbnail else None, source_url=source_url)


def fetch_page_metadata(page_url: str) -> PageMetadata:
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    errors: list[str] = []
    for candidate_url in build_page_url_candidates(page_url):
        try:
            response = requests.get(candidate_url, headers=headers, timeout=20)
        except requests.RequestException as error:
            errors.append(f"{candidate_url}: {type(error).__name__}: {error}")
            continue
        if response.status_code != 200:
            errors.append(f"{candidate_url}: HTTP {response.status_code}")
            continue
        metadata = extract_page_metadata(response.text, candidate_url)
        if metadata is not None:
            return metadata
        errors.append(f"{candidate_url}: no usable title metadata found")
    error_text = "\n  ".join(errors) if errors else "no candidate URLs were tried"
    raise ValueError(f"Could not fetch page metadata.\n  {error_text}")

def looks_like_generic_stream_title(title_text: str, source_url: str) -> bool:
    normalized = title_text.strip().casefold()
    if not normalized:
        return True
    if normalized in GENERIC_STREAM_TITLES:
        return True
    source_stem = Path(urlparse(source_url).path).stem.strip().casefold()
    return bool(source_stem and normalized == source_stem)


def choose_effective_title(info_dict: dict[str, object], source_url: str, page_metadata: PageMetadata | None) -> str:
    if page_metadata is not None and page_metadata.title:
        return page_metadata.title
    raw_title = str(info_dict.get("title") or "").strip()
    if raw_title and not looks_like_generic_stream_title(raw_title, source_url):
        return raw_title
    return raw_title or source_url


def build_run_output_template(args: argparse.Namespace, info_dict: dict[str, object], source_url: str, page_metadata: PageMetadata | None) -> str:
    if args.filename:
        return build_output_template(args.filename)
    if page_metadata is not None and page_metadata.title:
        return build_literal_output_template(page_metadata.title)
    raw_title = str(info_dict.get("title") or "").strip()
    if raw_title and not looks_like_generic_stream_title(raw_title, source_url):
        return DEFAULT_OUTPUT_TEMPLATE
    return build_literal_output_template(raw_title or source_url)


def build_ydl_options(args: argparse.Namespace, *, format_selector: str | None = None, output_template: str | None = None) -> tuple[Path, dict[str, object]]:
    output_dir = resolve_output_dir(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    headers = parse_header_values(args.header)
    if args.referer:
        headers["Referer"] = args.referer

    ydl_options: dict[str, object] = {
        "paths": {"home": str(output_dir)},
        "outtmpl": {"default": output_template or build_output_template(args.filename)},
        "http_headers": headers,
        "force_generic_extractor": True,
        "format": format_selector or args.format_selector or DEFAULT_FORMAT_SELECTOR,
        "noplaylist": True,
        "skip_download": args.dry_run,
        "windowsfilenames": True,
        "continuedl": True,
        "retries": 20,
        "fragment_retries": 20,
        "file_access_retries": 10,
        "extractor_retries": 5,
        "concurrent_fragment_downloads": 1,
        "merge_output_format": "mp4",
        "overwrites": args.overwrite,
        "progress_hooks": [build_progress_hook()],
    }

    ffmpeg_location = find_ffmpeg_location()
    if ffmpeg_location:
        ydl_options["ffmpeg_location"] = ffmpeg_location

    if args.cookies:
        cookie_path = Path(args.cookies).expanduser().resolve()
        if not cookie_path.is_file():
            raise ValueError(f"Cookie file was not found: {cookie_path}")
        ydl_options["cookiefile"] = str(cookie_path)
    elif args.cookies_from_browser:
        ydl_options["cookiesfrombrowser"] = parse_browser_spec(args.cookies_from_browser)

    if args.proxy:
        ydl_options["proxy"] = args.proxy

    return output_dir, ydl_options


def build_progress_hook() -> Callable[[dict[str, object]], None]:
    state = {"notified": False}

    def hook(status: dict[str, object]) -> None:
        if state["notified"]:
            return
        if status.get("status") == "finished":
            print("\nDownload complete. yt-dlp is finalizing the MP4 container...")
            state["notified"] = True

    return hook

def build_request_headers(args: argparse.Namespace) -> dict[str, str]:
    headers = parse_header_values(args.header)
    if args.referer:
        headers["Referer"] = args.referer
    return headers


def build_ffmpeg_header_arguments(headers: dict[str, str]) -> list[str]:
    arguments: list[str] = []
    user_agent = headers.get("User-Agent")
    referer = headers.get("Referer")
    if user_agent:
        arguments.extend(["-user_agent", user_agent])
    if referer:
        arguments.extend(["-referer", referer])
    remaining_headers = [
        f"{key}: {value}\r\n"
        for key, value in headers.items()
        if value and key not in {"User-Agent", "Referer"}
    ]
    if remaining_headers:
        arguments.extend(["-headers", "".join(remaining_headers)])
    return arguments


def cookie_domain_matches(cookie_domain: str, host: str) -> bool:
    normalized_domain = cookie_domain.lstrip(".").casefold()
    normalized_host = host.casefold()
    return normalized_host == normalized_domain or normalized_host.endswith(f".{normalized_domain}")


def merge_cookie_file_into_headers(headers: dict[str, str], cookie_path: Path, media_url: str) -> None:
    parsed_url = urlparse(media_url)
    host = parsed_url.hostname or ""
    request_path = parsed_url.path or "/"
    is_https = parsed_url.scheme.casefold() == "https"
    cookie_pairs: list[str] = []

    for raw_line in read_text_file(cookie_path).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue
        parts = line.split("	")
        if len(parts) < 7:
            continue
        domain, _, cookie_path_text, secure_flag, _, name, value = parts[:7]
        if not cookie_domain_matches(domain, host):
            continue
        cookie_path_text = cookie_path_text or "/"
        if not request_path.startswith(cookie_path_text):
            continue
        if secure_flag.casefold() == "true" and not is_https:
            continue
        cookie_pairs.append(f"{name}={value}")

    if not cookie_pairs:
        return

    existing_cookie = headers.get("Cookie")
    merged_cookie = "; ".join(cookie_pairs)
    headers["Cookie"] = f"{existing_cookie}; {merged_cookie}" if existing_cookie else merged_cookie


def looks_like_compatible_codec(codec_value: object, prefixes: tuple[str, ...]) -> bool:
    normalized = str(codec_value or "").strip().casefold()
    if normalized in {"", "none", "-"}:
        return False
    return any(normalized.startswith(prefix) for prefix in prefixes)


def can_direct_ffmpeg_download_format(format_info: dict[str, object]) -> bool:
    media_url = str(format_info.get("url") or "").strip()
    protocol = str(format_info.get("protocol") or "").strip().casefold()
    if not protocol and media_url.startswith(("http://", "https://")):
        protocol = urlparse(media_url).scheme.casefold()
    if protocol not in DIRECT_FFMPEG_PROTOCOLS or not media_url:
        return False
    if not looks_like_compatible_codec(format_info.get("vcodec"), DIRECT_FFMPEG_VIDEO_PREFIXES):
        return False
    if not looks_like_compatible_codec(format_info.get("acodec"), DIRECT_FFMPEG_AUDIO_PREFIXES):
        return False
    return True


def choose_direct_ffmpeg_format(info_dict: dict[str, object], selected_format: str | None) -> dict[str, object] | None:
    formats = [item for item in info_dict.get("formats") or [] if isinstance(item, dict)]
    if selected_format:
        for item in formats:
            if str(item.get("format_id") or "").strip() == selected_format and can_direct_ffmpeg_download_format(item):
                return item
        return None
    for item in reversed(formats):
        if can_direct_ffmpeg_download_format(item):
            return item
    return None


def build_probe_options(download_options: dict[str, object]) -> dict[str, object]:
    probe_options = dict(download_options)
    probe_options["skip_download"] = True
    return probe_options


def prompt_page_url(prompt_text: str) -> str:
    return input(prompt_text).strip()


def read_media_input() -> str:
    print("Paste a direct media URL on one line.")
    print("If you paste browser Copy as cURL, paste the whole block. Continuation lines are read automatically.")
    first_line = input("m3u8 URL or Copy as cURL: ").rstrip()
    if not first_line.strip():
        return ""

    lines = [first_line]
    if first_line.lstrip().lower().startswith("curl "):
        while lines[-1].rstrip().endswith(("\\", "^", "`")):
            next_line = input("... ").rstrip()
            if not next_line:
                break
            lines.append(next_line)
    return "\n".join(lines).strip()


def prompt_if_missing(args: argparse.Namespace) -> argparse.Namespace:
    if not args.page_url:
        if not sys.stdin.isatty() and not args.urls:
            raise SystemExit("No page URL was provided.")
        args.page_url = prompt_page_url("Page URL: ")
        if not args.page_url:
            raise SystemExit("No page URL was provided.")

    if not args.urls:
        media_input = read_media_input()
        if not media_input:
            raise SystemExit("No media URL was provided.")
        if media_input.lower().startswith("curl "):
            apply_curl_command_to_args(args, media_input)
        else:
            args.urls = collect_urls([media_input], [])

    if not args.referer and args.page_url:
        args.referer = args.page_url

    return args


def should_run_interactive_session(args: argparse.Namespace) -> bool:
    return bool(sys.stdin.isatty() and not args.page_url and not args.urls and not args.curl_file)


def build_job_args(base_args: argparse.Namespace, job: DownloadJob) -> argparse.Namespace:
    values = vars(base_args).copy()
    values["page_url"] = job.page_url
    values["urls"] = []
    values["url_file"] = []
    values["curl_file"] = None
    values["referer"] = None
    values["header"] = list(base_args.header)
    job_args = argparse.Namespace(**values)

    if job.media_input.lower().startswith("curl "):
        apply_curl_command_to_args(job_args, job.media_input)
    else:
        job_args.urls = collect_urls([job.media_input], [])

    if not job_args.referer:
        job_args.referer = job.page_url
    return job_args


def prompt_job_queue() -> list[DownloadJob]:
    print("\nQueue input mode")
    print("Enter one page URL and one m3u8/cURL block per job.")
    print("Queued m3u8 or cURL values can expire, so smaller batches are safer.")
    jobs: list[DownloadJob] = []

    while True:
        prompt_text = f"Page URL #{len(jobs) + 1} (blank to {'start downloads' if jobs else 'exit'}): "
        page_url = prompt_page_url(prompt_text)
        if not page_url:
            return jobs

        while True:
            media_input = read_media_input()
            if media_input:
                break
            print("A media URL or cURL block is required for this job.")

        jobs.append(DownloadJob(page_url=page_url, media_input=media_input))


def print_summary(args: argparse.Namespace, output_dir: Path, page_metadata: PageMetadata | None) -> None:
    print(f"Page URL: {args.page_url}")
    print(f"URLs: {len(args.urls)}")
    print(f"Output directory: {output_dir}")
    print(f"Mode: {'metadata check only' if args.dry_run else 'download'}")
    print("Direct media validation: enabled")
    print(f"Referer: {args.referer or 'not set'}")
    if ALL_QUALITY_MODE:
        print("Format selector: all detected audio/video qualities")
    elif args.format_selector:
        print(f"Format selector: {args.format_selector}")
    elif args.auto_best:
        print("Format selector: automatic best")
    else:
        print("Format selector: interactive when multiple streams are available")
    print(f"Thumbnail embedding: {'disabled (faster)' if args.no_thumbnail else 'enabled'}")
    if args.sleep_between_jobs > 0:
        print(f"Fixed pause after queued jobs: {args.sleep_between_jobs:.0f}s")
    if args.slow_sleep_seconds > 0 and args.slow_threshold_kib > 0:
        print(f"Adaptive pause: {args.slow_sleep_seconds:.0f}s when average speed falls below {args.slow_threshold_kib:.0f} KiB/s")
    if page_metadata is not None:
        print(f"Metadata source: {page_metadata.source_url}")
        print(f"Page title: {page_metadata.title}")
        print(f"Page thumbnail: {page_metadata.thumbnail_url or 'not found'}")
    if args.cookies_from_browser:
        print(f"Cookies from browser: {args.cookies_from_browser}")
    elif args.cookies:
        print(f"Cookies file: {Path(args.cookies).expanduser()}")
    elif args.curl_file:
        print(f"Request source: cURL file {Path(args.curl_file).expanduser()}")
    else:
        print("Cookies: not set")


def calculate_average_speed(saved_path: Path | None, transfer_seconds: float | None) -> float | None:
    if saved_path is None or transfer_seconds is None or transfer_seconds <= 0:
        return None
    if not saved_path.is_file():
        return None
    return saved_path.stat().st_size / transfer_seconds


def format_speed(value: float | None) -> str:
    if value is None or value <= 0:
        return "-"
    size = float(value)
    units = ("B/s", "KiB/s", "MiB/s", "GiB/s")
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == "B/s":
        return f"{int(size)} {unit}"
    return f"{size:.2f} {unit}"


def maybe_pause_between_jobs(args: argparse.Namespace, stats: DownloadStats | None, remaining_jobs: int) -> None:
    if remaining_jobs <= 0:
        return

    reasons: list[str] = []
    delay_seconds = 0.0

    if args.sleep_between_jobs > 0:
        delay_seconds = max(delay_seconds, float(args.sleep_between_jobs))
        reasons.append(f"fixed pause {args.sleep_between_jobs:.0f}s")

    if (
        stats is not None
        and stats.average_speed_bps is not None
        and args.slow_threshold_kib > 0
        and args.slow_sleep_seconds > 0
        and stats.average_speed_bps < float(args.slow_threshold_kib) * 1024
    ):
        delay_seconds = max(delay_seconds, float(args.slow_sleep_seconds))
        reasons.append(
            f"average speed {format_speed(stats.average_speed_bps)} below {args.slow_threshold_kib:.0f} KiB/s"
        )

    if delay_seconds <= 0:
        return

    reason_text = "; ".join(reasons) if reasons else "queue pacing"
    print(f"Cooling down for {delay_seconds:.0f}s before the next queued job ({reason_text})...")
    time.sleep(delay_seconds)


def format_cell(value: object) -> str:
    if value in (None, "", "none"):
        return "-"
    return str(value)


def format_size(value: object) -> str:
    if not isinstance(value, (int, float)) or value <= 0:
        return "-"
    size = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    unit = units[0]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            break
        size /= 1024
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"


def build_format_rows(info_dict: dict[str, object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in info_dict.get("formats") or []:
        if not isinstance(item, dict):
            continue
        resolution = item.get("resolution")
        if not resolution:
            width = item.get("width")
            height = item.get("height")
            if width and height:
                resolution = f"{width}x{height}"
            else:
                resolution = item.get("format_note") or item.get("quality")
        rows.append(
            {
                "format_id": format_cell(item.get("format_id")),
                "ext": format_cell(item.get("ext")),
                "resolution": format_cell(resolution),
                "vcodec": format_cell(item.get("vcodec")),
                "acodec": format_cell(item.get("acodec")),
                "protocol": format_cell(item.get("protocol")),
                "size": format_size(item.get("filesize") or item.get("filesize_approx")),
                "note": format_cell(item.get("format_note")),
            }
        )
    return rows


def print_format_table(info_dict: dict[str, object]) -> None:
    rows = build_format_rows(info_dict)
    if not rows:
        print("No stream list was exposed by the media URL. yt-dlp will use its default selection.")
        return
    columns = (("No", None), ("ID", "format_id"), ("Ext", "ext"), ("Resolution", "resolution"), ("VCodec", "vcodec"), ("ACodec", "acodec"), ("Protocol", "protocol"), ("Size", "size"), ("Note", "note"))
    widths: dict[str, int] = {}
    for header, key in columns:
        values = [header]
        if key is None:
            values.extend(str(index) for index in range(1, len(rows) + 1))
        else:
            values.extend(row[key] for row in rows)
        widths[header] = max(len(value) for value in values)
    print("\nAvailable streams:")
    print("  ".join(header.ljust(widths[header]) for header, _ in columns))
    print("  ".join("-" * widths[header] for header, _ in columns))
    for index, row in enumerate(rows, start=1):
        values = []
        for header, key in columns:
            cell = str(index) if key is None else row[key]
            values.append(cell.ljust(widths[header]))
        print("  ".join(values))


def choose_format_selector(args: argparse.Namespace, info_dict: dict[str, object]) -> str | None:
    if args.format_selector:
        return args.format_selector
    rows = build_format_rows(info_dict)
    if not rows:
        return None
    print_format_table(info_dict)
    if len(rows) == 1:
        print("\nOnly one stream is available. Selecting it automatically.")
        return rows[0]["format_id"]
    if args.auto_best or not sys.stdin.isatty():
        print("\nSelecting best stream automatically.")
        return None
    valid_ids = {row["format_id"] for row in rows}
    while True:
        choice = input("\nSelect a stream number, enter a format ID, or press Enter for best: ").strip()
        if not choice:
            return None
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(rows):
                return rows[index - 1]["format_id"]
        if choice in valid_ids:
            return choice
        print("Invalid selection.")


def get_int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def get_format_height(format_info: dict[str, object]) -> int | None:
    height = get_int_value(format_info.get("height"))
    if height:
        return height

    for key in ("resolution", "format_note", "quality"):
        value = str(format_info.get(key) or "").strip()
        if not value or value == "-":
            continue
        p_match = re.search(r"(?i)(\d{3,4})\s*p", value)
        if p_match:
            return int(p_match.group(1))
        resolution_match = re.search(r"(?i)\b\d{3,5}\s*x\s*(\d{3,4})\b", value)
        if resolution_match:
            return int(resolution_match.group(1))
    return None


def get_format_bitrate(format_info: dict[str, object]) -> float:
    for key in ("tbr", "vbr", "abr"):
        value = format_info.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return 0.0


def build_quality_label(format_info: dict[str, object]) -> str:
    height = get_format_height(format_info)
    if height:
        return f"{height}p"

    for key in ("format_note", "resolution", "format_id"):
        raw_value = str(format_info.get(key) or "").strip()
        if not raw_value or raw_value == "-":
            continue
        return sanitize_filename(raw_value)
    return "unknown"


def is_audio_video_format(format_info: dict[str, object]) -> bool:
    format_id = str(format_info.get("format_id") or "").strip()
    if not format_id or format_id == "-":
        return False

    vcodec = str(format_info.get("vcodec") or "").strip().casefold()
    acodec = str(format_info.get("acodec") or "").strip().casefold()
    if vcodec in {"", "none", "-"}:
        return False
    if acodec in {"", "none", "-"}:
        return False
    return True


def format_rank(format_info: dict[str, object]) -> tuple[int, float, int, int]:
    height = get_format_height(format_info) or 0
    bitrate = get_format_bitrate(format_info)
    width = get_int_value(format_info.get("width")) or 0
    filesize = get_int_value(format_info.get("filesize") or format_info.get("filesize_approx")) or 0
    return (height, bitrate, width, filesize)


def get_all_quality_formats(info_dict: dict[str, object]) -> list[dict[str, object]]:
    best_by_label: dict[str, dict[str, object]] = {}
    for item in info_dict.get("formats") or []:
        if not isinstance(item, dict) or not is_audio_video_format(item):
            continue
        label = build_quality_label(item)
        existing = best_by_label.get(label)
        if existing is None or format_rank(item) > format_rank(existing):
            best_by_label[label] = item
    return sorted(best_by_label.values(), key=format_rank, reverse=True)


def print_all_quality_plan(formats: Sequence[dict[str, object]]) -> None:
    print("\nAll-quality download plan:")
    print("No  Quality  ID    Resolution  VCodec       ACodec")
    print("--  -------  ----  ----------  -----------  ---------")
    for index, item in enumerate(formats, start=1):
        label = build_quality_label(item)
        resolution = item.get("resolution")
        if not resolution:
            width = item.get("width")
            height = item.get("height")
            resolution = f"{width}x{height}" if width and height else "-"
        print(
            f"{index:<2}  {label:<7}  {format_cell(item.get('format_id')):<4}  "
            f"{format_cell(resolution):<10}  {format_cell(item.get('vcodec')):<11}  {format_cell(item.get('acodec'))}"
        )
def probe_media_info(url: str, download_options: dict[str, object]) -> dict[str, object]:
    with YoutubeDL(build_probe_options(download_options)) as probe:
        info_dict = probe.extract_info(url, download=False)
        if not info_dict:
            raise ValueError(f"Could not resolve media metadata: {url}")
        return info_dict

def download_thumbnail_file(thumbnail_url: str, output_dir: Path, title_text: str, referer: str | None) -> Path:
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    if referer:
        headers["Referer"] = referer
    response = requests.get(thumbnail_url, headers=headers, timeout=30)
    response.raise_for_status()
    suffix = Path(urlparse(thumbnail_url).path).suffix.casefold()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        content_type = response.headers.get("content-type", "").casefold()
        if "png" in content_type:
            suffix = ".png"
        elif "webp" in content_type:
            suffix = ".webp"
        else:
            suffix = ".jpg"
    thumbnail_path = output_dir / f"{sanitize_filename(title_text)}.cover{suffix}"
    thumbnail_path.write_bytes(response.content)
    return thumbnail_path


def embed_thumbnail(video_path: Path, thumbnail_path: Path) -> None:
    ffmpeg_path = resolve_ffmpeg_path()
    if not video_path.is_file():
        raise ValueError(f"Video file was not found: {video_path}")
    if not thumbnail_path.is_file():
        raise ValueError(f"Thumbnail file was not found: {thumbnail_path}")

    temp_path = video_path.with_name(f"{video_path.stem}.with-cover{video_path.suffix}")
    image_codec = "png" if thumbnail_path.suffix.casefold() == ".png" else "mjpeg"
    command = [
        ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(thumbnail_path),
        "-map",
        "0",
        "-map",
        "1",
        "-c",
        "copy",
        "-c:v:1",
        image_codec,
        "-disposition:v:1",
        "attached_pic",
        "-metadata:s:v:1",
        "title=Cover",
        "-metadata:s:v:1",
        "comment=Cover (front)",
        str(temp_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True)
    except subprocess.CalledProcessError as error:
        if temp_path.exists():
            temp_path.unlink()
        if error.stderr:
            stderr_text = error.stderr.decode("utf-8", errors="replace").strip()
        else:
            stderr_text = "unknown ffmpeg error"
        raise ValueError(f"Failed to embed thumbnail: {stderr_text}") from error

    video_path.unlink()
    temp_path.replace(video_path)


def build_final_video_path(output_dir: Path, title_text: str, filename: str | None = None) -> Path:
    if filename:
        safe_name = sanitize_filename(filename)
        stem = Path(safe_name).stem if Path(safe_name).suffix else Path(safe_name).name
        return output_dir / f"{stem}.mp4"
    return output_dir / f"{sanitize_filename(title_text)}.mp4"


def download_with_ffmpeg_one_pass(args: argparse.Namespace, format_info: dict[str, object], output_dir: Path, title_text: str, thumbnail_url: str) -> Path:
    ffmpeg_path = resolve_ffmpeg_path()
    media_url = str(format_info.get("url") or "").strip()
    if not media_url:
        raise ValueError("The selected stream did not expose a direct media URL for ffmpeg.")

    headers = build_request_headers(args)
    if args.cookies:
        merge_cookie_file_into_headers(headers, Path(args.cookies).expanduser().resolve(), media_url)

    thumbnail_path = download_thumbnail_file(thumbnail_url, output_dir, title_text, args.page_url)
    output_path = build_final_video_path(output_dir, title_text, args.filename)
    partial_path = output_path.with_name(f"{output_path.stem}.download{output_path.suffix}")

    if partial_path.exists():
        partial_path.unlink()
    if output_path.exists():
        if args.overwrite:
            output_path.unlink()
        else:
            thumbnail_path.unlink(missing_ok=True)
            raise ValueError(f"Output file already exists: {output_path}. Use --overwrite to replace it.")

    image_codec = "png" if thumbnail_path.suffix.casefold() == ".png" else "mjpeg"
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-stats",
        "-y" if args.overwrite else "-n",
        "-protocol_whitelist",
        "file,http,https,tcp,tls,crypto,data",
        "-allowed_extensions",
        "ALL",
        "-allowed_segment_extensions",
        "ALL",
        "-extension_picky",
        "0",
        "-reconnect",
        "1",
        "-reconnect_streamed",
        "1",
        "-reconnect_on_network_error",
        "1",
        "-reconnect_on_http_error",
        "4xx,5xx",
        "-reconnect_delay_max",
        "10",
        "-seg_max_retry",
        "20",
        *build_ffmpeg_header_arguments(headers),
        "-i",
        media_url,
        "-i",
        str(thumbnail_path),
        "-map",
        "0:v",
        "-map",
        "0:a?",
        "-map",
        "1",
        "-c",
        "copy",
        "-c:v:1",
        image_codec,
        "-disposition:v:1",
        "attached_pic",
        "-metadata:s:v:1",
        "title=Cover",
        "-metadata:s:v:1",
        "comment=Cover (front)",
        str(partial_path),
    ]

    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as error:
        if partial_path.exists():
            partial_path.unlink()
        thumbnail_path.unlink(missing_ok=True)
        raise ValueError(f"ffmpeg one-pass download failed with exit code {error.returncode}.") from error

    thumbnail_path.unlink(missing_ok=True)
    partial_path.replace(output_path)
    return output_path


def pause_before_exit() -> None:
    if not getattr(sys, "frozen", False):
        return
    if not sys.stdin or not sys.stdin.isatty():
        return
    try:
        input("\nPress Enter to close...")
    except EOFError:
        pass


def execute_downloads(args: argparse.Namespace) -> tuple[int, DownloadStats | None]:
    args = prompt_if_missing(args)
    page_metadata = fetch_page_metadata(args.page_url) if args.page_url else None

    for url in args.urls:
        validate_direct_media_url(url)

    output_dir, base_ydl_options = build_ydl_options(args)
    print_summary(args, output_dir, page_metadata)

    result = 0
    last_stats: DownloadStats | None = None
    for url in args.urls:
        print(f"\nProcessing media URL: {url}")
        info_dict = probe_media_info(url, base_ydl_options)
        effective_title = choose_effective_title(info_dict, url, page_metadata)
        print(f"Title: {effective_title}")
        print(f"Thumbnail: {page_metadata.thumbnail_url if page_metadata else 'not available'}")

        selected_format = choose_format_selector(args, info_dict)
        direct_format = None
        if not args.dry_run and page_metadata and page_metadata.thumbnail_url and not args.no_thumbnail and not args.cookies_from_browser:
            direct_format = choose_direct_ffmpeg_format(info_dict, selected_format)
        if selected_format:
            print(f"Selected format: {selected_format}")
        elif direct_format is not None:
            print(f"Selected format: {direct_format.get('format_id') or 'best'}")
        else:
            print(f"Selected format: {DEFAULT_FORMAT_SELECTOR}")

        transfer_started = time.perf_counter()
        saved_path: Path | None = None

        if direct_format is not None:
            print("Download mode: one-pass ffmpeg with automatic thumbnail embedding.")
            try:
                saved_path = download_with_ffmpeg_one_pass(args, direct_format, output_dir, effective_title, page_metadata.thumbnail_url)
                print(f"Saved file: {saved_path.name}")
            except ValueError as error:
                print(f"One-pass ffmpeg failed. Falling back to yt-dlp download plus thumbnail post-processing. Reason: {error}")
                direct_format = None
                transfer_started = time.perf_counter()

        if direct_format is None:
            run_output_template = build_run_output_template(args, info_dict, url, page_metadata)
            _, run_options = build_ydl_options(args, format_selector=selected_format, output_template=run_output_template)
            print("Download mode: yt-dlp download plus thumbnail post-processing.")
            with YoutubeDL(run_options) as downloader:
                result = max(result, int(downloader.download([url]) or 0))

            saved_path = build_final_video_path(output_dir, effective_title, args.filename)
            if not args.dry_run and page_metadata and page_metadata.thumbnail_url and not args.no_thumbnail:
                print("Post-processing: embedding the thumbnail into the MP4. This rewrites the file and can take time on large videos...")
                thumbnail_path = download_thumbnail_file(page_metadata.thumbnail_url, output_dir, effective_title, args.page_url)
                embed_thumbnail(saved_path, thumbnail_path)
                thumbnail_path.unlink(missing_ok=True)
                print(f"Embedded thumbnail: {thumbnail_path.name}")

        transfer_seconds = None if args.dry_run else time.perf_counter() - transfer_started
        average_speed_bps = calculate_average_speed(saved_path, transfer_seconds)
        last_stats = DownloadStats(
            transfer_seconds=transfer_seconds,
            average_speed_bps=average_speed_bps,
            saved_path=saved_path,
        )
        if average_speed_bps is not None:
            print(f"Average transfer speed: {format_speed(average_speed_bps)}")

        if args.dry_run:
            print("Metadata check passed.")
    return int(result or 0), last_stats


def execute_all_quality_downloads(args: argparse.Namespace) -> tuple[int, DownloadStats | None]:
    args = prompt_if_missing(args)
    page_metadata = fetch_page_metadata(args.page_url) if args.page_url else None

    for url in args.urls:
        validate_direct_media_url(url)

    output_root = resolve_output_dir(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    _, base_ydl_options = build_ydl_options(args)
    print_summary(args, output_root, page_metadata)
    print("All-quality mode: every detected audio/video quality will be downloaded.")

    result = 0
    last_stats: DownloadStats | None = None
    for url in args.urls:
        print(f"\nProcessing media URL: {url}")
        info_dict = probe_media_info(url, base_ydl_options)
        effective_title = choose_effective_title(info_dict, url, page_metadata)
        print(f"Title: {effective_title}")
        print(f"Thumbnail: {page_metadata.thumbnail_url if page_metadata else 'not available'}")

        formats = get_all_quality_formats(info_dict)
        if not formats:
            raise ValueError("No combined audio/video quality variants were exposed by the media URL.")
        print_all_quality_plan(formats)

        title_folder = output_root / sanitize_filename(effective_title)
        title_folder.mkdir(parents=True, exist_ok=True)
        print(f"Output folder: {title_folder}")

        if args.dry_run:
            print("Metadata check passed. No media was downloaded.")
            continue

        base_filename = args.filename or effective_title
        for index, format_info in enumerate(formats, start=1):
            quality_label = build_quality_label(format_info)
            format_id = str(format_info.get("format_id") or "").strip()
            is_best_quality = index == 1
            file_title = base_filename if is_best_quality else f"{quality_label} {base_filename}"
            quality_args = argparse.Namespace(**vars(args))
            quality_args.urls = [url]
            quality_args.output_dir = str(title_folder)
            quality_args.format_selector = format_id
            quality_args.filename = file_title
            quality_args.auto_best = True

            print(f"\nDownloading {quality_label} ({index}/{len(formats)}) -> {sanitize_filename(file_title)}.mp4")
            quality_result = 1
            quality_stats: DownloadStats | None = None
            try:
                quality_result, quality_stats = execute_downloads(quality_args)
            except (DownloadError, ValueError, OSError, requests.RequestException) as error:
                print(f"Quality {quality_label} failed: {error}", file=sys.stderr)
            result = max(result, int(quality_result or 0))
            last_stats = quality_stats
            maybe_pause_between_jobs(args, quality_stats, len(formats) - index)

    return int(result or 0), last_stats


def run_interactive_session(base_args: argparse.Namespace, executor: Callable[[argparse.Namespace], tuple[int, DownloadStats | None]]) -> int:
    overall_result = 0

    while True:
        jobs = prompt_job_queue()
        if not jobs:
            return overall_result

        print(f"\nStarting {len(jobs)} queued job(s)...")
        for index, job in enumerate(jobs, start=1):
            print(f"\n=== Job {index}/{len(jobs)} ===")
            job_args = build_job_args(base_args, job)
            job_result = 1
            job_stats: DownloadStats | None = None
            try:
                job_result, job_stats = executor(job_args)
            except CookieLoadError:
                print("Could not load cookies from the selected browser. Close the browser and try again, or use --cookies cookies.txt.", file=sys.stderr)
            except DownloadError as error:
                print(f"Download failed: {error}", file=sys.stderr)
            except (ValueError, OSError, requests.RequestException) as error:
                print(f"Error: {error}", file=sys.stderr)
            except KeyboardInterrupt:
                print("\nStopped by user.", file=sys.stderr)
                return max(overall_result, 130)
            except Exception as error:  # pragma: no cover - defensive fallback
                print(f"Unexpected error: {type(error).__name__}: {error}", file=sys.stderr)
            overall_result = max(overall_result, job_result)
            maybe_pause_between_jobs(base_args, job_stats, len(jobs) - index)


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        executor = execute_all_quality_downloads if ALL_QUALITY_MODE else execute_downloads
        if should_run_interactive_session(args):
            return run_interactive_session(args, executor)
        result_code, _ = executor(args)
        return result_code
    except CookieLoadError:
        print("Could not load cookies from the selected browser. Close the browser and try again, or use --cookies cookies.txt.", file=sys.stderr)
        return 1
    except DownloadError as error:
        print(f"Download failed: {error}", file=sys.stderr)
        return 1
    except (ValueError, OSError, requests.RequestException) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped by user.", file=sys.stderr)
        return 130
    except Exception as error:  # pragma: no cover - defensive fallback
        print(f"Unexpected error: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    exit_code = main()
    if exit_code:
        pause_before_exit()
    raise SystemExit(exit_code)









