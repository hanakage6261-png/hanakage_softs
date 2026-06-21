import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus


CURRENT_DIR = Path(__file__).resolve().parent
for candidate_dir in (CURRENT_DIR, *CURRENT_DIR.parents):
    registry_dir = candidate_dir / "00_momonGA_master"
    registry_path = registry_dir / "momonGA_registry.py"
    if registry_path.exists():
        if str(registry_dir) not in sys.path:
            sys.path.insert(0, str(registry_dir))
        break
else:
    raise RuntimeError("00_momonGA_master/momonGA_registry.py が見つかりません。")

from momonGA_registry import load_module

downloader_module = load_module("downloader_main")
create_session = downloader_module.create_session
dedupe_urls = downloader_module.dedupe_urls
extract_work_urls_from_soup = downloader_module.extract_work_urls_from_soup
fetch_work_summary = downloader_module.fetch_work_summary
iter_collection_pages = downloader_module.iter_collection_pages
normalize_url = downloader_module.normalize_url


PDF_NAME_PATTERN = re.compile(r"^\[(?P<author>.+?)\]\s*(?P<title>.+?)\.pdf$", re.IGNORECASE)
DEFAULT_PDF_DIR = Path.home() / "Downloads" / "momonGA_PDFs"
OUTPUT_FILE = CURRENT_DIR / "momonGA_pdf_to_cbz_redownload_candidates.json"


def parse_pdf_name(path: Path):
    match = PDF_NAME_PATTERN.match(path.name)
    if not match:
        return None
    return match.group("author").strip(), match.group("title").strip()


def normalize_match_text(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def is_unknown_author(author: str) -> bool:
    normalized = normalize_match_text(author).strip("[]")
    return normalized in {"", "unknownauthor", "unknown_author", "unknownauthor."}


def titles_related(candidate: str, title: str) -> bool:
    normalized_candidate = normalize_match_text(candidate)
    normalized_title = normalize_match_text(title)
    if not normalized_candidate or not normalized_title:
        return False
    return (
        normalized_candidate == normalized_title
        or normalized_title in normalized_candidate
        or normalized_candidate in normalized_title
    )


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


def authors_from_work(work) -> list[str]:
    if getattr(work, "authors", None):
        return [str(value).strip() for value in work.authors if str(value).strip()]
    if getattr(work, "author", None):
        return [str(work.author).strip()]
    return []


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    for index in range(1, 10000):
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"重複回避先が見つかりません: {path}")


def retire_pdf(path: Path, delete_pdfs: bool):
    if not path.exists():
        print(f"PDFが見つかりません: {path.name}")
        return

    if delete_pdfs:
        path.unlink()
        return

    processed_dir = path.parent / "processed"
    processed_dir.mkdir(exist_ok=True)
    shutil.move(str(path), str(unique_destination(processed_dir / path.name)))


def build_search_url(keyword: str) -> str:
    return normalize_url(f"https://momon-ga.com/?s={quote_plus(keyword)}")


def collect_search_work_urls(session, keyword: str):
    search_url = build_search_url(keyword)
    work_urls = []

    try:
        for page_number, (page_url, soup) in enumerate(
            iter_collection_pages(session, search_url),
            1,
        ):
            page_urls = extract_work_urls_from_soup(soup, page_url)
            print(f"検索 '{keyword}' ページ {page_number}: {len(page_urls)} 件")
            work_urls.extend(page_urls)
    except Exception as exc:
        print(f"検索URL展開に失敗しました: {keyword} / {exc}")
        return []

    return dedupe_urls(work_urls)


def fetch_search_candidates(session, keyword: str):
    candidates = []
    for work_url in collect_search_work_urls(session, keyword):
        try:
            candidates.append(fetch_work_summary(session, work_url))
        except Exception as exc:
            print(f"候補取得失敗: {work_url} / {exc}")
    return candidates


def dedupe_works_by_id(works):
    deduped = {}
    for work in works:
        deduped[int(work.work_id)] = work
    return list(deduped.values())


def find_candidates_for_pdf(session, author: str, title: str):
    author_usable = not is_unknown_author(author)
    title_candidates = fetch_search_candidates(session, title)
    title_matches = [
        work for work in title_candidates if titles_related(work.title, title)
    ]

    if title_matches:
        candidates = title_matches
    elif author_usable:
        combined_keyword = f"{author} {title}".strip()
        combined_candidates = fetch_search_candidates(session, combined_keyword)
        combined_matches = [
            work for work in combined_candidates if titles_related(work.title, title)
        ]
        candidates = combined_matches or combined_candidates or title_candidates
    else:
        candidates = title_candidates

    candidate_records = []
    for work in dedupe_works_by_id(candidates):
        work_authors = authors_from_work(work)
        candidate_records.append(
            {
                "id": int(work.work_id),
                "url": work.final_url or work.source_url,
                "title": work.title,
                "authors": work_authors,
                "author_match": (
                    any(author_matches(candidate, author) for candidate in work_authors)
                    if author_usable
                    else None
                ),
            }
        )

    candidate_records.sort(key=lambda item: item["id"])
    return {
        "author_usable": author_usable,
        "search_title": title,
        "candidates": candidate_records,
    }


def write_output(pdf_dir: Path, results):
    all_candidate_urls = dedupe_urls(
        [
            candidate["url"]
            for result in results
            for candidate in result["candidates"]
            if candidate.get("url")
        ]
    )
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "pdf_directory": str(pdf_dir),
        "result_count": len(results),
        "all_candidate_urls": all_candidate_urls,
        "results": results,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    return payload


def collect_pdf_candidates(pdf_dir: Path, delete_pdfs: bool):
    pdf_paths = sorted(pdf_dir.glob("*.pdf"))
    if not pdf_paths:
        print(f"PDFが見つかりません: {pdf_dir}")
        return []

    session = create_session()
    results = []
    processed_count = 0

    try:
        for pdf_path in pdf_paths:
            parsed = parse_pdf_name(pdf_path)
            if parsed is None:
                print(f"ファイル名形式が想定外なのでスキップします: {pdf_path.name}")
                continue

            author, title = parsed
            print("=" * 60)
            print(f"PDF: {pdf_path.name}")
            print(f"author: {author}")
            print(f"title: {title}")

            candidate_result = find_candidates_for_pdf(session, author, title)
            result_entry = {
                "pdf_file": pdf_path.name,
                "author": author,
                "title": title,
                "author_usable": candidate_result["author_usable"],
                "search_title": candidate_result["search_title"],
                "candidates": candidate_result["candidates"],
            }
            results.append(result_entry)

            print(f"候補URL数: {len(result_entry['candidates'])}")
            for candidate in result_entry["candidates"]:
                print(
                    f"- mo{candidate['id']} | {candidate['title']} | "
                    f"author_match={candidate['author_match']} | {candidate['url']}"
                )

            if result_entry["candidates"]:
                retire_pdf(pdf_path, delete_pdfs)
                processed_count += 1

    finally:
        session.close()

    print(f"\n候補を書き出したPDF数: {processed_count}")
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Old PDF files to CBZ redownload helper."
    )
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
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir).expanduser()
    results = collect_pdf_candidates(pdf_dir, args.delete_pdfs)
    payload = write_output(pdf_dir, results)
    print(f"保存先: {OUTPUT_FILE}")
    print(f"総候補URL数: {len(payload['all_candidate_urls'])}")


if __name__ == "__main__":
    main()
