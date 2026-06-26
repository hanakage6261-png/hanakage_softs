from __future__ import annotations

import hashlib
import io
import re
from datetime import date
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup
from PIL import Image

from momonGA_modules.momonGA_downloader_modules_network.momonGA_downloader_network import (
    decode_response_html,
    download_binary,
    fetch_soup,
    request_with_backoff,
)
from momonGA_modules.momonGA_downloader_modules_shared.momonGA_downloader_shared import (
    DATE_PATTERN,
    IMG_URL_TEMPLATE,
    MAX_COLLECTION_PAGES,
    WORK_PATH_PATTERN,
    WorkSummary,
    ensure_trailing_slash,
    get_work_id,
    normalize_url,
)


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


def resolve_collection_targets(session, collection_url: str, record_work=None):
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
        if record_work is not None:
            record_work(work)
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


def resolve_download_targets(session, input_url: str, record_work=None):
    normalized_url = normalize_url(input_url)
    from momonGA_modules.momonGA_downloader_modules_shared.momonGA_downloader_shared import get_url_kind

    url_kind = get_url_kind(normalized_url)

    if url_kind == "work":
        work = fetch_work_summary(session, normalized_url)
        if record_work is not None:
            record_work(work)
        return [work]

    return resolve_collection_targets(session, normalized_url, record_work=record_work)
