import ctypes
import hashlib
import importlib
import io
import json
import os
import re
import shutil
import string
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from PIL import Image

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
for candidate_dir in (Path(CURRENT_DIR), *Path(CURRENT_DIR).parents):
    registry_dir = candidate_dir / "00_momonGA_master"
    registry_path = registry_dir / "momonGA_registry.py"
    if registry_path.exists():
        if str(registry_dir) not in sys.path:
            sys.path.insert(0, str(registry_dir))
        break
else:
    raise RuntimeError("00_momonGA_master/momonGA_registry.py が見つかりません。")

momonGA_registry = importlib.import_module("momonGA_registry")
load_module = momonGA_registry.load_module

metadata_store = load_module("metadata_store")
open_metadata_connection = metadata_store.open_metadata_connection
fetch_downloaded_ids = metadata_store.fetch_downloaded_ids
record_download_event = metadata_store.record_download_event
upsert_work = metadata_store.upsert_work

url_rules = load_module("url_rules")



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


def normalize_url(url: str) -> str:
    return url_rules.normalize_url(url)


def ensure_trailing_slash(url: str) -> str:
    parts = urlsplit(normalize_url(url))
    path = parts.path or "/"
    if not path.endswith("/"):
        path += "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def get_app_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_resume_file_path() -> str:
    return os.path.join(get_app_base_dir(), RESUME_FILE_NAME)


def get_work_id(url: str) -> str:
    return url_rules.get_work_id(url)


def contains_embedded_url(path: str) -> bool:
    return url_rules.contains_embedded_url(path)


def is_root_collection_path(path: str) -> bool:
    return url_rules.is_root_collection_path(path)


def is_metadata_collection_path(path: str) -> bool:
    return url_rules.is_metadata_collection_path(path)


def is_collection_path(path: str) -> bool:
    return url_rules.is_collection_path(path)


def get_url_kind(url: str) -> str:
    return url_rules.get_url_kind(url)


def is_search_result_url(url: str) -> bool:
    return url_rules.is_search_result_url(url)


def get_unique_path(path: str) -> str:
    base, ext = os.path.splitext(path)
    candidate = path
    index = 1

    while os.path.exists(candidate):
        candidate = f"{base} ({index}){ext}"
        index += 1

    return candidate


def create_session():
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def decode_response_html(response) -> str:
    content = response.content
    candidate_encodings = ["utf-8", "utf-8-sig"]

    if response.encoding and response.encoding.lower() not in {"iso-8859-1", "latin-1"}:
        candidate_encodings.append(response.encoding)

    if response.apparent_encoding:
        candidate_encodings.append(response.apparent_encoding)

    candidate_encodings.extend(["cp932", "shift_jis", "euc_jp"])

    tried_encodings = set()
    for encoding in candidate_encodings:
        if not encoding:
            continue
        normalized_encoding = encoding.lower()
        if normalized_encoding in tried_encodings:
            continue
        tried_encodings.add(normalized_encoding)

        try:
            return content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue

    return content.decode("utf-8", errors="replace")


def get_backoff_seconds(attempt: int) -> int:
    wait_seconds = INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1))
    return min(wait_seconds, MAX_BACKOFF_SECONDS)


def request_with_backoff(session, url: str, description: str, allow_not_found: bool = False):
    last_error = "不明なエラー"
    attempt = 1

    while True:
        response = None
        retry_reason = None

        try:
            response = session.get(url, timeout=TIMEOUT)
            status_code = response.status_code

            if status_code == 200:
                return response

            if allow_not_found and status_code == 404:
                response.close()
                return None

            if status_code == 404:
                raise RuntimeError(f"{description}: 404 Not Found")

            if status_code in RETRYABLE_STATUS_CODES:
                retry_reason = f"HTTP {status_code}"
            else:
                raise RuntimeError(f"{description}: HTTP {status_code}")

        except requests.RequestException as exc:
            retry_reason = f"{type(exc).__name__}: {exc}"

        finally:
            if response is not None and response.status_code != 200:
                response.close()

        if retry_reason is None:
            continue

        last_error = retry_reason
        wait_seconds = get_backoff_seconds(attempt)
        print(
            f"{description}: {retry_reason}。"
            f"{wait_seconds}秒待って再試行します"
            f" ({attempt}回目)"
        )
        time.sleep(wait_seconds)
        attempt += 1


def download_binary(session, url: str, description: str, allow_not_found: bool = False):
    response = request_with_backoff(session, url, description, allow_not_found=allow_not_found)
    if response is None:
        return None

    try:
        return response.content
    finally:
        response.close()


def fetch_soup(session, url: str, description: str):
    response = request_with_backoff(session, url, description)
    try:
        return BeautifulSoup(decode_response_html(response), "html.parser")
    finally:
        response.close()


def parse_pages(text: str):
    match = re.search(r"(\d+)\s*ページ", text)
    if match:
        return int(match.group(1))
    return None


def parse_latest_date(text: str):
    candidates = []
    for match in DATE_PATTERN.finditer(text):
        year, month, day = map(int, match.groups())
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue

    if not candidates:
        return None

    return max(candidates)


def extract_author(soup: BeautifulSoup) -> str:
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and "content" in meta.attrs:
        match = re.search(r"【作者】([^【]+)", meta["content"])
        if match:
            return match.group(1).strip()

    author_link = soup.select_one('a[href*="/cartoonist/"]')
    if author_link:
        author_text = author_link.get_text(strip=True)
        if author_text:
            return author_text

    return ""


def extract_text_by_id(soup: BeautifulSoup, element_id: str):
    element = soup.find(id=element_id)
    if element:
        text = element.get_text(strip=True)
        if text:
            return text
    return None


def extract_tag_lists(soup: BeautifulSoup):
    tag_lists = {
        "parody": [],
        "circle": [],
        "author": [],
        "characters": [],
        "content": [],
    }
    title_map = {
        "パロディ": "parody",
        "サークル": "circle",
        "作者": "author",
        "キャラ": "characters",
        "内容": "content",
    }

    for table in soup.find_all(class_="post-tag-table"):
        title_tag = table.find(class_="post-tag-title")
        if not title_tag:
            continue

        normalized_title = title_tag.get_text(strip=True)
        target_key = title_map.get(normalized_title)
        if not target_key:
            continue

        tag_lists[target_key] = [
            link.get_text(strip=True)
            for link in table.find_all("a")
            if link.get_text(strip=True)
        ]

    return tag_lists


def is_not_found_page(soup: BeautifulSoup) -> bool:
    h1 = soup.find("h1")
    if not h1:
        return False
    return "ページが見つかりませんでした" in h1.get_text(strip=True)


def work_to_db_record(work: WorkSummary):
    return {
        "id": int(work.work_id),
        "title": work.title,
        "date": work.date_text,
        "type": work.work_type,
        "pages": work.total_pages,
        "parody": work.parody,
        "circle": work.circle,
        "author": work.authors if work.authors else ([work.author] if work.author else []),
        "characters": work.characters,
        "content": work.content,
        "url": work.source_url,
        "final_url": work.final_url,
        "status": work.status,
    }


def fetch_work_summary(session, work_url: str) -> WorkSummary:
    normalized_url = normalize_url(work_url)
    response = request_with_backoff(session, normalized_url, "作品ページの取得")
    final_url = normalize_url(response.url)
    try:
        soup = BeautifulSoup(decode_response_html(response), "html.parser")
    finally:
        response.close()

    if is_not_found_page(soup):
        raise RuntimeError("作品ページが見つかりませんでした。")

    work_id = get_work_id(final_url)
    page_text = soup.get_text(" ", strip=True)

    title = work_id
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)

    tag_lists = extract_tag_lists(soup)
    authors = tag_lists["author"]
    author = authors[0] if authors else extract_author(soup)
    total_pages = parse_pages(page_text)
    updated_at = parse_latest_date(page_text)
    date_text = extract_text_by_id(soup, "post-time")
    work_type = extract_text_by_id(soup, "post-category")

    return WorkSummary(
        source_url=normalized_url,
        final_url=final_url,
        work_id=work_id,
        title=title,
        author=author,
        total_pages=total_pages,
        date_text=date_text,
        work_type=work_type,
        parody=tag_lists["parody"],
        circle=tag_lists["circle"],
        authors=authors,
        characters=tag_lists["characters"],
        content=tag_lists["content"],
        status="found",
        updated_at=updated_at,
    )


def get_first_image_hash(session, work: WorkSummary):
    if work.first_image_hash is not None:
        return work.first_image_hash

    image_url = IMG_URL_TEMPLATE.format(work.work_id, 1)
    try:
        image_bytes = download_binary(
            session,
            image_url,
            f"1ページ目画像の取得 mo{work.work_id}",
            allow_not_found=True,
        )
    except FatalNetworkError:
        raise
    except Exception as exc:
        print(
            f"警告: mo{work.work_id} の1ページ目画像を重複判定用に取得できませんでした。"
            f" この作品は画像比較なしで扱います。詳細: {exc}"
        )
        work.first_image_hash = ""
        return work.first_image_hash

    if not image_bytes:
        print(
            f"警告: mo{work.work_id} の1ページ目画像が存在しません。"
            " この作品は画像比較なしで扱います。"
        )
        work.first_image_hash = ""
        return work.first_image_hash

    with Image.open(io.BytesIO(image_bytes)) as image:
        normalized_image = image.convert("RGB")
        digest = hashlib.sha1()
        digest.update(f"{normalized_image.width}x{normalized_image.height}".encode("ascii"))
        digest.update(normalized_image.tobytes())

    work.first_image_hash = digest.hexdigest()
    return work.first_image_hash


def choose_preferred_work(existing: WorkSummary, candidate: WorkSummary) -> WorkSummary:
    existing_pages = existing.total_pages if existing.total_pages is not None else -1
    candidate_pages = candidate.total_pages if candidate.total_pages is not None else -1

    if existing_pages != candidate_pages:
        return existing if existing_pages > candidate_pages else candidate

    if existing.updated_at != candidate.updated_at:
        if existing.updated_at is None:
            return candidate
        if candidate.updated_at is None:
            return existing
        return existing if existing.updated_at > candidate.updated_at else candidate

    return existing if int(existing.work_id) >= int(candidate.work_id) else candidate


def is_collection_page_url(candidate_url: str, root_url: str) -> bool:
    root_parts = urlsplit(root_url)
    candidate_parts = urlsplit(candidate_url)

    if candidate_parts.netloc.lower() != root_parts.netloc.lower():
        return False

    if WORK_PATH_PATTERN.search(candidate_parts.path):
        return False

    root_query = parse_qs(root_parts.query)
    candidate_query = parse_qs(candidate_parts.query)
    root_search = root_query.get("s", [""])[0]
    candidate_search = candidate_query.get("s", [""])[0]
    candidate_path = candidate_parts.path or "/"

    if root_search and candidate_search == root_search:
        if candidate_path == "/":
            return True
        if re.match(r"^/page/\d+/?$", candidate_path):
            return True

    root_path = root_parts.path if root_parts.path.endswith("/") else f"{root_parts.path}/"

    if candidate_path == root_parts.path and candidate_parts.query and candidate_parts.query != root_parts.query:
        return True

    return candidate_path.startswith(f"{root_path}page/")


def extract_work_urls_from_soup(soup: BeautifulSoup, base_url: str):
    work_urls = []
    seen_urls = set()

    for link in soup.select("a[href]"):
        href = link.get("href", "").strip()
        if not href:
            continue

        candidate_url = normalize_url(urljoin(base_url, href))
        candidate_path = urlsplit(candidate_url).path
        if not WORK_PATH_PATTERN.search(candidate_path):
            continue

        if candidate_url in seen_urls:
            continue

        seen_urls.add(candidate_url)
        work_urls.append(candidate_url)

    return work_urls


def iter_collection_pages(session, collection_url: str):
    root_url = ensure_trailing_slash(collection_url)
    pending_urls = [root_url]
    queued_urls = {root_url}
    seen_urls = set()

    while pending_urls:
        if len(seen_urls) >= MAX_COLLECTION_PAGES:
            raise RuntimeError(
                f"一覧ページの巡回が {MAX_COLLECTION_PAGES} ページを超えたため中断しました。"
            )

        page_url = pending_urls.pop(0)
        queued_urls.discard(page_url)
        if page_url in seen_urls:
            continue

        seen_urls.add(page_url)
        soup = fetch_soup(session, page_url, "作者/サークルページの取得")
        yield page_url, soup

        for link in soup.select("a[href]"):
            href = link.get("href", "").strip()
            if not href:
                continue

            candidate_url = normalize_url(urljoin(page_url, href))
            if candidate_url in seen_urls or candidate_url in queued_urls:
                continue

            if is_collection_page_url(candidate_url, root_url):
                pending_urls.append(candidate_url)
                queued_urls.add(candidate_url)


def resolve_collection_targets(session, metadata_connection, collection_url: str):
    normalized_collection_url = ensure_trailing_slash(collection_url)
    discovered_work_urls = []
    discovered_work_ids = set()

    print("作者/サークルページを巡回して作品URLを集めます。")

    page_count = 0
    for page_count, (page_url, soup) in enumerate(iter_collection_pages(session, normalized_collection_url), 1):
        page_work_urls = extract_work_urls_from_soup(soup, page_url)
        print(f"一覧ページ {page_count}: {len(page_work_urls)} 件の作品URLを検出")

        for work_url in page_work_urls:
            work_id = get_work_id(work_url)
            if work_id in discovered_work_ids:
                continue
            discovered_work_ids.add(work_id)
            discovered_work_urls.append(work_url)

    if not discovered_work_urls:
        raise RuntimeError("作者/サークルページから作品URLを取得できませんでした。")

    print(f"重複除去前の作品数: {len(discovered_work_urls)} 件")

    selected_by_title = {}
    selected_order = []

    for index, work_url in enumerate(discovered_work_urls, 1):
        work = fetch_work_summary(session, work_url)
        upsert_work(metadata_connection, work_to_db_record(work))
        same_title_entries = selected_by_title.setdefault(work.title, [])

        if not same_title_entries:
            work.order_index = len(selected_order)
            selected_order.append(work)
            same_title_entries.append(work)
            print(f"[{index} / {len(discovered_work_urls)}] 採用: {work.title} (mo{work.work_id})")
            continue

        candidate_hash = get_first_image_hash(session, work)
        replaced_existing = False

        for entry_index, existing in enumerate(same_title_entries):
            existing_hash = get_first_image_hash(session, existing)
            if not candidate_hash or not existing_hash:
                continue
            if existing_hash != candidate_hash:
                continue

            preferred = choose_preferred_work(existing, work)
            if preferred is existing:
                print(
                    f"[{index} / {len(discovered_work_urls)}] 同一候補として除外: "
                    f"{work.title} (mo{work.work_id})"
                )
            else:
                work.order_index = existing.order_index
                selected_order[existing.order_index] = work
                same_title_entries[entry_index] = work
                print(
                    f"[{index} / {len(discovered_work_urls)}] 同一候補を置換: "
                    f"{work.title} (mo{existing.work_id} -> mo{work.work_id})"
                )

            replaced_existing = True
            break

        if replaced_existing:
            continue

        work.order_index = len(selected_order)
        selected_order.append(work)
        same_title_entries.append(work)
        print(
            f"[{index} / {len(discovered_work_urls)}] タイトルは重複しているが一枚目の画像が異なるため別作品として採用: "
            f"{work.title} (mo{work.work_id})"
        )

    selected_works = [work for work in selected_order if work is not None]
    print(f"最終的なダウンロード対象: {len(selected_works)} 件")
    return selected_works


def resolve_download_targets(session, metadata_connection, input_url: str):
    normalized_url = normalize_url(input_url)
    url_kind = get_url_kind(normalized_url)

    if url_kind == "work":
        work = fetch_work_summary(session, normalized_url)
        upsert_work(metadata_connection, work_to_db_record(work))
        return [work]

    return resolve_collection_targets(session, metadata_connection, normalized_url)


def download_image(session, url: str, path: str) -> bool:
    image_bytes = download_binary(
        session,
        url,
        f"画像取得 {os.path.basename(path)}",
        allow_not_found=True,
    )
    if image_bytes is None:
        return False

    with open(path, "wb") as file:
        file.write(image_bytes)
    return True


def download_gallery_images(session, work_id: str, total_pages, temp_dir: str):
    image_paths = []
    reached_gallery_end = False

    if total_pages:
        page_numbers = range(1, total_pages + 1)
    else:
        page_numbers = range(1, UNKNOWN_PAGE_LIMIT + 1)

    for page_number in page_numbers:
        image_url = IMG_URL_TEMPLATE.format(work_id, page_number)
        image_path = os.path.join(temp_dir, f"{page_number:03}.webp")
        image_downloaded = download_image(session, image_url, image_path)

        if not image_downloaded:
            if total_pages:
                raise RuntimeError(
                    f"{page_number}ページ目の画像を取得できませんでした。"
                    "不完全なPDFになるため、この作品は破棄します。"
                )
            reached_gallery_end = True
            break

        image_paths.append(image_path)

        if total_pages:
            print(f"[{page_number} / {total_pages}] ダウンロード完了")
        else:
            print(f"[{page_number}] ダウンロード完了")

    if not image_paths:
        raise RuntimeError("画像を1枚も取得できませんでした。")

    if total_pages and len(image_paths) != total_pages:
        raise RuntimeError("全ページを取得できなかったため、この作品は破棄します。")

    if not total_pages and not reached_gallery_end:
        raise RuntimeError(
            f"ページ数不明のまま {UNKNOWN_PAGE_LIMIT} ページに達しました。"
            "上限に達したため、この作品は破棄します。"
        )

    return image_paths


def build_cbz(image_paths, cbz_path: str):
    with zipfile.ZipFile(cbz_path, "w", compression=zipfile.ZIP_STORED) as archive:
        for image_path in image_paths:
            archive.write(image_path, arcname=os.path.basename(image_path))


def process_work(session, save_root: str, metadata_connection, work: WorkSummary):
    print("\n画像ダウンロード開始")
    print(f"作品名: {work.title}")
    print(f"作者名: {work.author}")
    print(f"作品URL: {work.final_url}")
    if work.total_pages:
        print(f"ページ数: {work.total_pages}ページ")
    else:
        print("ページ数: 作品ページから取得できませんでした")
    if work.updated_at:
        print(f"更新日: {work.updated_at.isoformat()}")
    print("")

    final_archive = None

    with tempfile.TemporaryDirectory(prefix=f"momonGA_{work.work_id}_") as temp_dir:
        images = download_gallery_images(session, work.work_id, work.total_pages, temp_dir)
        safe_title = sanitize_filename(work.title, f"work_{work.work_id}")
        safe_author = sanitize_filename(work.author, "")
        local_archive = os.path.join(temp_dir, f"{safe_title} {work.work_id}.cbz")
        build_cbz(images, local_archive)

        final_archive = get_unique_path(
            os.path.join(save_root, f"[{safe_author}] {safe_title} {work.work_id}.cbz")
        )
        try:
            shutil.move(local_archive, final_archive)
        except Exception:
            if final_archive and os.path.exists(final_archive):
                os.remove(final_archive)
            raise

    upsert_work(metadata_connection, work_to_db_record(work))
    record_download_event(metadata_connection, int(work.work_id))

    print(f"\n保存先: {final_archive}\n")


def select_save_location():
    downloads_path = os.path.join(os.path.expanduser("~"), "Downloads", APP_FOLDER_NAME)
    other_drives = list_non_c_drives()

    print("保存先を選んでください\n")
    print("[0] このコンピューターの Downloads フォルダー")

    for index, (drive_path, label) in enumerate(other_drives, 1):
        print(f"[{index}] {drive_path}  {label} (外付けドライブ)")

    while True:
        choice = input("\n保存先の番号を入力してください: ").strip()
        if choice.isdigit():
            selected_index = int(choice)
            if selected_index == 0:
                return downloads_path
            if 1 <= selected_index <= len(other_drives):
                return os.path.join(other_drives[selected_index - 1][0], APP_FOLDER_NAME)

        print("有効な番号を入力してください。")


def collect_input_urls():
    print("URLを入力してください。")
    print("空Enterで入力を終了し、そのまま処理を開始します。")

    collected_urls = []

    while True:
        prompt = f"URL {len(collected_urls) + 1}: "
        input_url = input(prompt).strip()
        if not input_url:
            return collected_urls

        normalized_url = normalize_url(input_url)
        try:
            get_url_kind(normalized_url)
        except RuntimeError as exc:
            print(f"入力URLエラー: {exc}")
            continue

        collected_urls.append(normalized_url)


def dedupe_urls(urls):
    unique_urls = []
    seen_urls = set()

    for url in urls:
        normalized_url = normalize_url(url)
        if not normalized_url or normalized_url in seen_urls:
            continue
        seen_urls.add(normalized_url)
        unique_urls.append(normalized_url)

    return unique_urls


def filter_supported_urls(urls, source_label: str):
    return url_rules.filter_supported_urls(urls, source_label)


def format_work_brief(work: WorkSummary) -> str:
    parts = [f"mo{work.work_id}", work.title]
    if work.total_pages:
        parts.append(f"{work.total_pages}p")
    if work.updated_at:
        parts.append(work.updated_at.isoformat())
    return " | ".join(parts)


def parse_excluded_indexes(raw_text: str, max_index: int):
    excluded_indexes = set()
    tokens = re.split(r"[\s,、]+", raw_text.strip())

    for token in tokens:
        if not token:
            continue
        if not token.isdigit():
            raise ValueError(f"番号ではない入力があります: {token}")

        index = int(token)
        if index < 1 or index > max_index:
            raise ValueError(f"範囲外の番号があります: {index}")

        excluded_indexes.add(index)

    return excluded_indexes


def prompt_excluded_works(collection_url: str, works):
    if not works:
        return works

    print("\n作者/サークルURLから作品URLを抽出しています。")
    print(f"元URL: {collection_url}")

    for index, work in enumerate(works, 1):
        print(f"[{index}] {format_work_brief(work)}")

    print("")
    print("除外したい作品の番号を入力してください。")
    print("複数ある場合は半角スペースまたはカンマ区切りで入力できます。")
    print("空Enterで全件ダウンロードします。")

    while True:
        raw_text = input("除外番号: ").strip()
        if not raw_text:
            return works

        try:
            excluded_indexes = parse_excluded_indexes(raw_text, len(works))
        except ValueError as exc:
            print(f"入力エラー: {exc}")
            continue

        selected_works = [
            work for index, work in enumerate(works, 1)
            if index not in excluded_indexes
        ]

        print(
            f"{len(works)} 件中 {len(excluded_indexes)} 件を除外し、"
            f"{len(selected_works)} 件をダウンロード対象にします。"
        )
        return selected_works


def prompt_exclude_downloaded_works(metadata_connection, works):
    if not works:
        return works

    work_ids = [int(work.work_id) for work in works]
    downloaded_ids = fetch_downloaded_ids(metadata_connection, work_ids)

    if not downloaded_ids:
        return works

    downloaded_works = [
        work for work in works
        if int(work.work_id) in downloaded_ids
    ]

    print("\n過去にダウンロード済みの作品が見つかりました。")
    for work in downloaded_works:
        print(f"- {format_work_brief(work)}")

    while True:
        answer = input(
            f"ダウンロード済み {len(downloaded_works)} 件を候補から除外しますか？ [Y/n]: "
        ).strip().lower()
        if answer in {"", "y", "yes"}:
            return [
                work for work in works
                if int(work.work_id) not in downloaded_ids
            ]
        if answer in {"n", "no"}:
            return works
        print("y または n を入力してください。")


def load_resume_queue():
    resume_file_path = get_resume_file_path()
    temp_resume_file_path = f"{resume_file_path}{RESUME_TEMP_SUFFIX}"

    candidate_paths = []
    if os.path.exists(resume_file_path):
        candidate_paths.append(resume_file_path)
    if os.path.exists(temp_resume_file_path):
        candidate_paths.append(temp_resume_file_path)

    if not candidate_paths:
        return []

    candidate_paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    state = None

    for candidate_path in candidate_paths:
        try:
            with open(candidate_path, "r", encoding="utf-8") as file:
                state = json.load(file)
            if candidate_path.endswith(RESUME_TEMP_SUFFIX):
                print("前回の一時再開ファイルを復元に使用します。")
            break
        except Exception:
            continue

    if state is None:
        print("再開情報の読み込みに失敗したため、再開キューは無視します。")
        return []

    restored_urls = []
    current_url = state.get("current_url")
    pending_urls = state.get("pending_urls", [])

    if current_url:
        restored_urls.append(current_url)
    restored_urls.extend(pending_urls)
    restored_urls = dedupe_urls(restored_urls)

    if restored_urls:
        print(f"前回未完了のURLを {len(restored_urls)} 件復元しました。")

    return filter_supported_urls(restored_urls, "再開キュー")


def save_resume_state(current_url, pending_urls):
    resume_file_path = get_resume_file_path()
    state = {
        "current_url": normalize_url(current_url) if current_url else None,
        "pending_urls": dedupe_urls(pending_urls),
    }
    temp_path = f"{resume_file_path}{RESUME_TEMP_SUFFIX}"

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)

    last_error = None
    for attempt in range(1, RESUME_SAVE_RETRY_ATTEMPTS + 1):
        try:
            os.replace(temp_path, resume_file_path)
            return True
        except PermissionError as exc:
            last_error = exc
            if attempt < RESUME_SAVE_RETRY_ATTEMPTS:
                time.sleep(RESUME_SAVE_RETRY_SECONDS)
                continue
        except OSError as exc:
            last_error = exc
            break

    print(
        "警告: 再開情報ファイルの更新に失敗しました。"
        " 今回の処理は継続しますが、次回再開が正しくできない可能性があります。"
        f" 詳細: {last_error}"
    )
    return False


def clear_resume_state():
    resume_file_path = get_resume_file_path()
    temp_resume_file_path = f"{resume_file_path}{RESUME_TEMP_SUFFIX}"

    for path in (resume_file_path, temp_resume_file_path):
        if not os.path.exists(path):
            continue

        for attempt in range(1, RESUME_SAVE_RETRY_ATTEMPTS + 1):
            try:
                os.remove(path)
                break
            except PermissionError:
                if attempt < RESUME_SAVE_RETRY_ATTEMPTS:
                    time.sleep(RESUME_SAVE_RETRY_SECONDS)
                    continue
                print(f"警告: 再開情報ファイルを削除できませんでした: {path}")
                break


def build_pending_input_queue():
    resumed_urls = load_resume_queue()
    if resumed_urls:
        print("空Enterでそのまま前回の続きから再開できます。")
        print("新しいURLを追加すると、復元したURLに続けて処理します。")

    new_urls = collect_input_urls()
    if resumed_urls and new_urls:
        print("新しいURLを先に処理し、前回未完了のURLはその後に回します。")
    combined_urls = dedupe_urls(new_urls + resumed_urls)
    return filter_supported_urls(combined_urls, "入力URL")


def process_input_queue(session, save_root: str, metadata_connection, input_urls):
    if not input_urls:
        return

    print(f"\n{len(input_urls)} 件の入力URLを順番に処理します。\n")
    remaining_urls = list(input_urls)

    while remaining_urls:
        current_url = remaining_urls[0]
        save_resume_state(current_url, remaining_urls[1:])

        print(f"=== キュー残り {len(remaining_urls)} 件 ===")
        print(f"URL: {current_url}")

        try:
            current_kind = get_url_kind(current_url)

            if current_kind == "collection":
                target_works = resolve_collection_targets(session, metadata_connection, current_url)
                target_works = prompt_exclude_downloaded_works(
                    metadata_connection,
                    target_works,
                )
                target_works = prompt_excluded_works(current_url, target_works)
                if not target_works:
                    print("この作者/サークルURLはすべて除外されたため、次へ進みます。\n")
                    remaining_urls.pop(0)
                    if remaining_urls:
                        save_resume_state(None, remaining_urls)
                    else:
                        clear_resume_state()
                    continue

                expanded_work_urls = dedupe_urls(
                    [work.source_url for work in target_works] + remaining_urls[1:]
                )

                if not expanded_work_urls:
                    raise RuntimeError("作者/サークルURLから作品URLを展開できませんでした。")

                remaining_urls = expanded_work_urls
                save_resume_state(remaining_urls[0], remaining_urls[1:])
                print(
                    f"作者/サークルURLを {len(target_works)} 件の作品URLへ展開し、"
                    "作品単位のキューに置き換えました。"
                )
                continue

            work = fetch_work_summary(session, current_url)
            upsert_work(metadata_connection, work_to_db_record(work))
            process_work(session, save_root, metadata_connection, work)

        except KeyboardInterrupt:
            print("\n中断を検知しました。次回起動時はこのURLから再開します。")
            raise

        except FatalNetworkError as exc:
            print(f"\nネットワークエラー: {exc}")
            print("現在のURLは次回起動時に再開できるよう保持したまま終了します。\n")
            raise

        except Exception as exc:
            print(f"\nエラー: {exc}")
            print("このURLはスキップして次へ進みます。\n")

        remaining_urls.pop(0)
        if remaining_urls:
            save_resume_state(None, remaining_urls)
        else:
            clear_resume_state()


def main():
    print("=== momonGA Downloader ===\n")

    save_root = select_save_location()
    os.makedirs(save_root, exist_ok=True)
    print(f"\n保存先: {save_root}\n")

    session = create_session()
    metadata_connection = open_metadata_connection()
    try:
        while True:
            input_urls = build_pending_input_queue()
            if not input_urls:
                break

            process_input_queue(session, save_root, metadata_connection, input_urls)
            print("入力されたURLの処理が終わりました。")
            print("次のURLを入力できます。空Enterで終了します。\n")

    except KeyboardInterrupt:
        print("\n処理を中断しました。")

    except FatalNetworkError:
        pass

    finally:
        session.close()
        metadata_connection.close()

    print("\nすべての処理を終了しました。")
    input("Enterキーで終了します...")


if __name__ == "__main__":
    main()
