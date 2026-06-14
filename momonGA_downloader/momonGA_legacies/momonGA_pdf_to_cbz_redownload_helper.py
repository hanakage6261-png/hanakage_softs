import argparse
import io
import json
import os
import re
import shutil
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote_plus

# Force UTF-8 encoding for stdout/stderr on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from momonGA_metadata_store import get_database_path, open_metadata_connection
from momonGA_downloader.momonGA_downloader import (
    create_session,
    dedupe_urls,
    process_input_queue,
    resolve_download_targets,
    save_resume_state,
    select_save_location,
)


PDF_NAME_PATTERN = re.compile(r"^\[(?P<author>.+?)\]\s*(?P<title>.+?)\.pdf$", re.IGNORECASE)
DEFAULT_PDF_DIR = Path.home() / "Downloads" / "momonGA_PDFs"
URL_LIST_FILE = CURRENT_DIR / "recovered_pdf_work_urls.txt"


def parse_pdf_name(path: Path):
    match = PDF_NAME_PATTERN.match(path.name)
    if not match:
        return None
    return match.group("author").strip(), match.group("title").strip()


def decode_json_list(value):
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return [str(value)]
    if isinstance(data, list):
        return [str(item) for item in data]
    return [str(data)]


def normalize_match_text(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def row_has_author(row, author: str) -> bool:
    normalized_author = normalize_match_text(author)
    for item in decode_json_list(row["author"]):
        normalized_item = normalize_match_text(item)
        if not normalized_item:
            continue
        if normalized_item == normalized_author:
            return True
        if normalized_author in normalized_item or normalized_item in normalized_author:
            return True
    return False


def row_url(row):
    return row["final_url"] or row["url"]


def find_urls_from_database(author: str, title: str):
    connection = sqlite3.connect(get_database_path())
    connection.row_factory = sqlite3.Row
    try:
        exact_rows = connection.execute(
            """
            SELECT title, author, url, final_url
            FROM works
            WHERE status = 'found'
              AND title = ?
              AND author LIKE ?
            ORDER BY id
            """,
            (title, f"%{author}%"),
        ).fetchall()
        exact_urls = [row_url(row) for row in exact_rows if row_has_author(row, author) and row_url(row)]
        if exact_urls:
            return exact_urls

        author_rows = connection.execute(
            """
            SELECT title, author, url, final_url
            FROM works
            WHERE status = 'found'
              AND author LIKE ?
            ORDER BY id
            """,
            (f"%{author}%",),
        ).fetchall()
        return [row_url(row) for row in author_rows if row_has_author(row, author) and row_url(row)]
    finally:
        connection.close()


def resolve_search_works(session, metadata_connection, keyword: str):
    search_url = f"https://momon-ga.com/?s={quote_plus(keyword)}"
    try:
        return resolve_download_targets(session, metadata_connection, search_url)
    except RuntimeError as exc:
        print(f"検索結果から作品URLを取得できませんでした: {keyword} / {exc}")
        return []


def author_matches(candidate: str, author: str) -> bool:
    normalized_candidate = normalize_match_text(candidate)
    normalized_author = normalize_match_text(author)
    if not normalized_candidate or not normalized_author:
        return False
    return (
        normalized_candidate == normalized_author
        or normalized_candidate in normalized_author
        or normalized_author in normalized_candidate
    )


def find_urls_from_site(session, metadata_connection, author: str, title: str):
    works = resolve_search_works(session, metadata_connection, author)
    matched_urls = []
    for work in works:
        work_authors = work.authors or ([work.author] if work.author else [])
        if any(author_matches(candidate, author) for candidate in work_authors):
            matched_urls.append(work.source_url)

    if matched_urls:
        return matched_urls

    title_works = resolve_search_works(session, metadata_connection, title)
    if title_works:
        return [work.source_url for work in title_works]

    return [work.source_url for work in works]


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    for index in range(1, 10000):
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"退避先ファイル名を作れませんでした: {path}")


def retire_pdf(path: Path, delete_pdfs: bool):
    if not path.exists():
        print(f"ファイルが見つかりません（既に移動済みか削除済み）: {path.name}")
        return

    if delete_pdfs:
        path.unlink()
        return

    processed_dir = path.parent / "processed"
    processed_dir.mkdir(exist_ok=True)
    try:
        shutil.move(str(path), str(unique_destination(processed_dir / path.name)))
    except (FileNotFoundError, OSError) as e:
        print(f"ファイル移動に失敗しました: {path.name} - {e}")


def collect_pdf_urls(pdf_dir: Path, delete_pdfs: bool):
    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_paths:
        print(f"PDFが見つかりません: {pdf_dir}")
        return []

    session = create_session()
    metadata_connection = open_metadata_connection()
    collected_urls = []
    processed_count = 0

    try:
        for pdf_path in pdf_paths:
            parsed = parse_pdf_name(pdf_path)
            if parsed is None:
                print(f"ファイル名形式が違うためスキップ: {pdf_path.name}")
                continue

            author, title = parsed
            print("=" * 60)
            print(f"PDF: {pdf_path.name}")
            print(f"author: {author}")
            print(f"title: {title}")

            urls = find_urls_from_database(author, title)
            if urls:
                print(f"DBから {len(urls)} 件の作品URLを取得しました。")
            else:
                print("DBに作者情報がないため、サイト検索から作品URLを取得します。")
                urls = find_urls_from_site(session, metadata_connection, author, title)
                print(f"サイト検索から {len(urls)} 件の作品URLを取得しました。")

            if not urls:
                print("作品URLを取得できなかったため、このPDFは残します。")
                continue

            # Write URLs to file immediately
            for url in urls:
                with open(URL_LIST_FILE, 'a', encoding='utf-8') as f:
                    f.write(url + "\n")
                collected_urls.append(url)

            retire_pdf(pdf_path, delete_pdfs)
            processed_count += 1

    finally:
        session.close()
        metadata_connection.close()

    print(f"\n処理済みPDF: {processed_count}")
    print(f"取得URL数: {len(collected_urls)}")
    print(f"URLリスト: {URL_LIST_FILE}")
    return collected_urls


def enqueue_urls(urls):
    if not urls:
        return
    save_resume_state(urls[0], urls[1:])
    print("momonGA_downloader の再開キューへURLを登録しました。")


def maybe_run_downloader(urls):
    if not urls:
        return

    answer = input("このまま再ダウンロードを開始しますか？ [y/N]: ").strip().lower()
    if answer not in {"y", "yes"}:
        print("次回 momonGA_downloader.py を起動すると、登録済みURLから再開できます。")
        return

    save_root = select_save_location()
    os.makedirs(save_root, exist_ok=True)
    session = create_session()
    metadata_connection = open_metadata_connection()
    try:
        process_input_queue(session, save_root, metadata_connection, urls)
    finally:
        session.close()
        metadata_connection.close()


def main():
    parser = argparse.ArgumentParser(description="Old PDF files to CBZ redownload helper.")
    parser.add_argument(
        "--pdf-dir",
        default=str(DEFAULT_PDF_DIR),
        help="PDF files directory. Default: ~/Downloads/momonGA_PDFs",
    )
    parser.add_argument(
        "--delete-pdfs",
        action="store_true",
        help="Delete processed PDFs instead of moving them to processed/.",
    )
    parser.add_argument(
        "--enqueue-only",
        action="store_true",
        help="Only enqueue URL list for momonGA_downloader. Do not ask to run downloads now.",
    )
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir).expanduser()
    urls = collect_pdf_urls(pdf_dir, args.delete_pdfs)
    enqueue_urls(urls)
    if not args.enqueue_only:
        maybe_run_downloader(urls)


if __name__ == "__main__":
    main()
