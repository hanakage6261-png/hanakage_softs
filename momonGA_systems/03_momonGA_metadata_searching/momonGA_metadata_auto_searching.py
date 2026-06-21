import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from momonGA_registry import load_module

metadata_store = load_module("metadata_store")
open_metadata_connection = metadata_store.open_metadata_connection
overwrite_work_metadata = metadata_store.overwrite_work_metadata
upsert_work = metadata_store.upsert_work


REQUEST_URL_TEMPLATE = "https://momon-ga.com/fanzine/mo{}/"
PROGRESS_FILE_NAME = "momonGA_searching_state.json"
PROGRESS_TEMP_SUFFIX = ".tmp"
PROGRESS_SAVE_RETRY_ATTEMPTS = 10
PROGRESS_SAVE_RETRY_SECONDS = 0.2
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}
TIMEOUT = 10
REQUEST_INTERVAL_SECONDS = 0.12
RETRYABLE_STATUS_CODES = {403, 408, 429, 500, 502, 503, 504}
INITIAL_BACKOFF_SECONDS = 3
MAX_BACKOFF_SECONDS = 180
WORK_PATH_PATTERN = re.compile(r"/(?:magazine|fanzine)/mo(\d+)/?$", re.IGNORECASE)
DATE_TEXT_PATTERN = re.compile(r"^\d{4}\D+\d{1,2}\D+\d{1,2}")
SUSPICIOUS_CYRILLIC_PATTERN = re.compile(r"[А-Яа-яЁё]")
MOJIBAKE_MARKERS = (
    "�",
    "Ã",
    "Â",
    "Ð",
    "Ñ",
    "Á",
    "Ü",
    "Ś",
    "ľ",
    "ť",
    "Ā",
    "ď",
    "ґ",
    "ғ",
    "ө",
    "Ә",
    "җ",
    "ң",
    "Ұ",
    "і",
)


def get_progress_path() -> str:
    return os.path.join(CURRENT_DIR, PROGRESS_FILE_NAME)


def load_next_id() -> int:
    progress_path = get_progress_path()
    temp_progress_path = f"{progress_path}{PROGRESS_TEMP_SUFFIX}"

    candidate_paths = []
    if os.path.exists(progress_path):
        candidate_paths.append(progress_path)
    if os.path.exists(temp_progress_path):
        candidate_paths.append(temp_progress_path)

    if not candidate_paths:
        return 0

    candidate_paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    state = None

    for candidate_path in candidate_paths:
        try:
            with open(candidate_path, "r", encoding="utf-8") as file:
                state = json.load(file)
            if candidate_path.endswith(PROGRESS_TEMP_SUFFIX):
                print("前回の一時進捗ファイルを復元に使用します。")
            break
        except Exception:
            continue

    if state is None:
        print("進捗ファイルの読み込みに失敗したため、ID 0 から開始します。")
        return 0

    next_id = state.get("next_id", 0)
    return int(next_id) if isinstance(next_id, int) or str(next_id).isdigit() else 0


def save_next_id(next_id: int):
    progress_path = get_progress_path()
    temp_path = f"{progress_path}{PROGRESS_TEMP_SUFFIX}"
    state = {"next_id": int(next_id)}

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)

    last_error = None
    for attempt in range(1, PROGRESS_SAVE_RETRY_ATTEMPTS + 1):
        try:
            os.replace(temp_path, progress_path)
            return True
        except PermissionError as exc:
            last_error = exc
            if attempt < PROGRESS_SAVE_RETRY_ATTEMPTS:
                time.sleep(PROGRESS_SAVE_RETRY_SECONDS)
                continue
        except OSError as exc:
            last_error = exc
            break

    print(
        "警告: 進捗ファイルの更新に失敗しました。"
        " 現在の処理は続行しますが、次回起動位置がずれる可能性があります。"
        f" 詳細: {last_error}"
    )
    return False


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


def request_with_backoff(
    session,
    url: str,
    description: str,
    allow_not_found: bool = False,
    allow_redirects: bool = True,
):
    attempt = 1

    while True:
        response = None
        retry_reason = None

        try:
            response = session.get(
                url,
                timeout=TIMEOUT,
                allow_redirects=allow_redirects,
            )
            status_code = response.status_code

            if status_code == 200:
                return response

            if not allow_redirects and status_code in {301, 302, 303, 307, 308}:
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

        wait_seconds = get_backoff_seconds(attempt)
        print(
            f"{description}: {retry_reason}。"
            f"{wait_seconds}秒待って再試行します。"
            f" ({attempt}回目)"
        )
        time.sleep(wait_seconds)
        attempt += 1


def fetch_page(session, work_id: int):
    requested_url = REQUEST_URL_TEMPLATE.format(work_id)
    response = request_with_backoff(
        session,
        requested_url,
        f"作品ページ取得 ID {work_id}",
        allow_not_found=True,
        allow_redirects=False,
    )
    if response is None:
        return None, requested_url, None

    if response.status_code in {301, 302, 303, 307, 308}:
        redirect_url = urljoin(requested_url, response.headers.get("Location", ""))
        response.close()

        redirect_match = WORK_PATH_PATTERN.search(urlsplit(redirect_url).path)
        if not redirect_match or int(redirect_match.group(1)) != work_id:
            return None, requested_url, redirect_url or None

        response = request_with_backoff(
            session,
            redirect_url,
            f"作品ページ取得 ID {work_id}",
            allow_not_found=True,
        )
        if response is None:
            return None, requested_url, redirect_url

    try:
        return decode_response_html(response), requested_url, response.url
    finally:
        response.close()


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
        "属性": "content",
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


def parse_pages(soup: BeautifulSoup):
    page_tag = soup.find(id="post-number")
    if not page_tag:
        return None

    text = page_tag.get_text(strip=True).replace("ページ", "")
    return int(text) if text.isdigit() else None


def is_not_found_page(soup: BeautifulSoup) -> bool:
    h1 = soup.find("h1")
    if not h1:
        return False
    return "ページが見つかりませんでした" in h1.get_text(strip=True)


def parse(html, work_id: int, requested_url: str, final_url: str | None):
    if html is None:
        return {
            "id": work_id,
            "url": requested_url,
            "final_url": final_url,
            "status": "not_found",
        }

    soup = BeautifulSoup(html, "html.parser")
    normalized_final_url = final_url.strip() if final_url else None

    if is_not_found_page(soup):
        return {
            "id": work_id,
            "url": requested_url,
            "final_url": normalized_final_url,
            "status": "not_found",
        }

    if not normalized_final_url:
        return {
            "id": work_id,
            "url": requested_url,
            "final_url": normalized_final_url,
            "status": "not_found",
        }

    final_path = urlsplit(normalized_final_url).path
    path_match = WORK_PATH_PATTERN.search(final_path)
    if not path_match or int(path_match.group(1)) != work_id:
        return {
            "id": work_id,
            "url": requested_url,
            "final_url": normalized_final_url,
            "status": "not_found",
        }

    h1 = soup.find("h1")
    tag_lists = extract_tag_lists(soup)

    return {
        "id": work_id,
        "title": h1.get_text(strip=True) if h1 else None,
        "date": extract_text_by_id(soup, "post-time"),
        "type": extract_text_by_id(soup, "post-category"),
        "pages": parse_pages(soup),
        "parody": tag_lists["parody"],
        "circle": tag_lists["circle"],
        "author": tag_lists["author"],
        "characters": tag_lists["characters"],
        "content": tag_lists["content"],
        "url": requested_url,
        "final_url": normalized_final_url,
        "status": "found",
    }


def print_result(data):
    print("============================================================")
    print(f"ID: {data.get('id')}")
    print(f"STATUS: {data.get('status')}")
    print()

    if data["status"] != "found":
        print('title: ""')
        print('date: ""')
        print('type: ""')
        print("pages: ")
        print()
        print('parody: ""')
        print('circle: ""')
        print('author: ""')
        print('characters: ""')
        print('content: ""')
        print(f'url: "{data.get("url", "")}"')
        print()
        print("Finish\n")
        return

    print(f'title: "{data.get("title", "")}"')
    print(f'date: "{data.get("date", "")}"')
    print(f'type: "{data.get("type", "")}"')
    print(f'pages: {data.get("pages")}')
    print()

    def print_list(label, values):
        if not values:
            print(f'{label}: ""')
        elif len(values) == 1:
            print(f'{label}: "{values[0]}"')
        else:
            print(f"{label}:")
            for item in values:
                print(f'    "{item}",')

    print_list("parody", data.get("parody"))
    print_list("circle", data.get("circle"))
    print_list("author", data.get("author"))
    print_list("characters", data.get("characters"))
    print_list("content", data.get("content"))

    print()
    print(f'url: "{data.get("url", "")}"')
    print(f'final_url: "{data.get("final_url", "")}"')
    print()
    print("Finish\n")


def looks_like_mojibake(text: str | None) -> bool:
    if not text:
        return False

    if any(marker in text for marker in MOJIBAKE_MARKERS):
        return True

    if SUSPICIOUS_CYRILLIC_PATTERN.search(text):
        return True

    return False


def record_needs_refresh(row) -> bool:
    status = (row["status"] or "").strip().lower()
    if not status:
        return True

    if status != "found":
        return False

    title = (row["title"] or "").strip()
    date_text = (row["date"] or "").strip()
    work_type = (row["type"] or "").strip()

    if not title or not date_text or not work_type:
        return True

    if looks_like_mojibake(title) or looks_like_mojibake(date_text) or looks_like_mojibake(work_type):
        return True

    if not DATE_TEXT_PATTERN.match(date_text):
        return True

    return False


def find_next_target_id(connection, start_id: int) -> int:
    next_id = int(start_id)
    rows = connection.execute(
        "SELECT id, title, date, type, status FROM works WHERE id >= ? ORDER BY id",
        (next_id,),
    )

    for row in rows:
        row_id = int(row["id"])
        if row_id != next_id:
            break
        if record_needs_refresh(row):
            break
        next_id += 1

    return next_id


def find_earliest_suspicious_id(connection, before_id: int) -> int | None:
    if before_id <= 0:
        return None

    rows = connection.execute(
        "SELECT id, title, date, type, status FROM works WHERE id < ? ORDER BY id",
        (int(before_id),),
    )

    for row in rows:
        if record_needs_refresh(row):
            return int(row["id"])

    return None


def main():
    connection = open_metadata_connection()
    session = create_session()
    current_id = load_next_id()
    suspicious_id = find_earliest_suspicious_id(connection, current_id)
    if suspicious_id is not None and suspicious_id < current_id:
        print(
            f"既存DBに要再取得データを検出したため、ID {suspicious_id} から補修再開します。"
        )
        current_id = suspicious_id
        save_next_id(current_id)

    print(f"開始ID: {current_id}")

    try:
        while True:
            next_target_id = find_next_target_id(connection, current_id)
            if next_target_id != current_id:
                print(
                    f"ID {current_id} から ID {next_target_id - 1} までは"
                    "正常データが既にあるためまとめてスキップ"
                )
                current_id = next_target_id
                save_next_id(current_id)

            html, requested_url, final_url = fetch_page(session, current_id)
            data = parse(html, current_id, requested_url, final_url)
            existing_row = connection.execute(
                "SELECT id, title, date, type, status FROM works WHERE id = ?",
                (current_id,),
            ).fetchone()
            if existing_row is not None and record_needs_refresh(existing_row):
                overwrite_work_metadata(connection, data)
            else:
                upsert_work(connection, data)
            print_result(data)

            current_id += 1
            save_next_id(current_id)
            time.sleep(REQUEST_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        save_next_id(current_id)
        print("\n中断しました。次回はこのIDから再開します。")

    finally:
        session.close()
        connection.close()


if __name__ == "__main__":
    main()
