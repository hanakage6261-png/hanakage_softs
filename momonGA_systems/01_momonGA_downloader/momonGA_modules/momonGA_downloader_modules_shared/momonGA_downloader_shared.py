from __future__ import annotations

import ctypes
import os
import re
import string
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import momonGA_url_rules as url_rules


DOWNLOADER_DIR = Path(__file__).resolve().parents[2]
MODULES_DIR = DOWNLOADER_DIR / "momonGA_modules"
QUEUE_MODULE_DIR = MODULES_DIR / "momonGA_downloader_modules_queue"

IMG_URL_TEMPLATE = "https://z3.momon-ga.com/galleries/{}/{}.webp"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}
TIMEOUT = 10
APP_FOLDER_NAME = "momonGA_Download"
RESUME_FILE_NAME = "momonGA_downloader_resume.json"
RESUME_TEMP_SUFFIX = ".tmp"
RESUME_SAVE_RETRY_ATTEMPTS = 10
RESUME_SAVE_RETRY_SECONDS = 0.2
RETRYABLE_STATUS_CODES = {403, 408, 429, 500, 502, 503, 504}
INITIAL_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 180
MAX_RETRY_ATTEMPTS = 8
UNKNOWN_PAGE_LIMIT = 1000
MAX_COLLECTION_PAGES = 200

ALLOWED_SITE_HOST = url_rules.ALLOWED_SITE_HOST
ROOT_COLLECTION_SEGMENTS = url_rules.ROOT_COLLECTION_SEGMENTS
METADATA_COLLECTION_SEGMENTS = url_rules.METADATA_COLLECTION_SEGMENTS
WORK_PATH_PATTERN = url_rules.WORK_PATH_PATTERN
WORK_ID_PATTERN = url_rules.WORK_ID_PATTERN
DATE_PATTERN = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


class FatalNetworkError(RuntimeError):
    pass


@dataclass
class WorkSummary:
    source_url: str
    final_url: str
    work_id: str
    title: str
    author: str
    total_pages: int | None
    date_text: str | None = None
    work_type: str | None = None
    parody: list[str] = field(default_factory=list)
    circle: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    characters: list[str] = field(default_factory=list)
    content: list[str] = field(default_factory=list)
    status: str = "found"
    updated_at: date | None = None
    first_image_hash: str | None = None
    order_index: int = -1


normalize_url = url_rules.normalize_url
get_work_id = url_rules.get_work_id
contains_embedded_url = url_rules.contains_embedded_url
is_root_collection_path = url_rules.is_root_collection_path
is_metadata_collection_path = url_rules.is_metadata_collection_path
is_collection_path = url_rules.is_collection_path
get_url_kind = url_rules.get_url_kind
is_search_result_url = url_rules.is_search_result_url
filter_supported_urls = url_rules.filter_supported_urls


def get_volume_label(drive_letter):
    volume_name_buffer = ctypes.create_unicode_buffer(1024)

    ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(drive_letter),
        volume_name_buffer,
        ctypes.sizeof(volume_name_buffer),
        None,
        None,
        None,
        None,
        0,
    )

    return volume_name_buffer.value if volume_name_buffer.value else "名称なし"


def list_non_c_drives():
    drives = []
    for drive_letter in string.ascii_uppercase:
        drive_path = f"{drive_letter}:\\"
        if os.path.exists(drive_path) and drive_letter != "C":
            label = get_volume_label(drive_path)
            drives.append((drive_path, label))
    return drives


def sanitize_filename(value: str, fallback: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|]', "_", value).strip().rstrip(". ")
    if not cleaned:
        cleaned = fallback
    if cleaned.split(".")[0].upper() in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:180]


def ensure_trailing_slash(url: str) -> str:
    parts = urlsplit(normalize_url(url))
    path = parts.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def get_app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.fspath(DOWNLOADER_DIR)


def get_resume_directory_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(
            get_app_base_dir(),
            "momonGA_modules",
            "momonGA_downloader_modules_queue",
        )
    return os.fspath(QUEUE_MODULE_DIR)


def ensure_resume_directory_exists():
    os.makedirs(get_resume_directory_path(), exist_ok=True)


def get_resume_file_path() -> str:
    return os.path.join(get_resume_directory_path(), RESUME_FILE_NAME)


def get_legacy_resume_file_path() -> str:
    return os.path.join(get_app_base_dir(), RESUME_FILE_NAME)


def get_unique_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    candidate = path
    index = 1

    while os.path.exists(candidate):
        candidate = f"{base} ({index}){ext}"
        index += 1

    return candidate
