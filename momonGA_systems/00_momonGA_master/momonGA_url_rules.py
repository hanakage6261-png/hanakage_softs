from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit, urlunsplit


ALLOWED_SITE_HOST = "momon-ga.com"
ROOT_COLLECTION_SEGMENTS = {
    "fanzine",
    "magazine",
    "trend",
    "popularity",
    "comments",
    "rated",
    "mylist",
    "history",
}
METADATA_COLLECTION_SEGMENTS = {
    "parody",
    "group",
    "cartoonist",
    "character",
    "tag",
}
WORK_PATH_PATTERN = re.compile(r"^/(?:magazine|fanzine)/mo(\d+)/?$", re.IGNORECASE)
WORK_ID_PATTERN = re.compile(r"mo(\d+)", re.IGNORECASE)


def normalize_url(url: str) -> str:
    normalized = url.strip()
    if not normalized:
        return ""

    if "://" not in normalized:
        normalized = f"https://{normalized.lstrip('/')}"

    parts = urlsplit(normalized)
    if not parts.netloc:
        parts = urlsplit(f"https://{normalized}")

    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/" and not path.endswith("/"):
        path += "/"

    return urlunsplit((
        "https",
        parts.netloc.lower(),
        path,
        parts.query,
        "",
    ))


def get_work_id(url: str) -> str:
    match = WORK_ID_PATTERN.search(url)
    if not match:
        raise RuntimeError("入力されたURLは適切なURLではありません。作品、作者またはサークルのURLを入力してください。")
    return match.group(1)


def contains_embedded_url(path: str) -> bool:
    lowered = path.lower()
    return "http://" in lowered or "https://" in lowered


def is_root_collection_path(path: str) -> bool:
    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return False

    root = segments[0].lower()
    if root not in ROOT_COLLECTION_SEGMENTS:
        return False

    if len(segments) == 1:
        return True

    return (
        len(segments) == 3
        and segments[1].lower() == "page"
        and segments[2].isdigit()
    )


def is_metadata_collection_path(path: str) -> bool:
    segments = [segment for segment in path.split("/") if segment]
    if len(segments) < 2:
        return False

    root = segments[0].lower()
    if root not in METADATA_COLLECTION_SEGMENTS:
        return False

    if len(segments) == 2:
        return True

    return (
        len(segments) == 4
        and segments[2].lower() == "page"
        and segments[3].isdigit()
    )


def is_collection_path(path: str) -> bool:
    if contains_embedded_url(path):
        return False
    return is_root_collection_path(path) or is_metadata_collection_path(path)


def is_search_result_url(url: str) -> bool:
    parts = urlsplit(normalize_url(url))
    path = parts.path or "/"
    query = parse_qs(parts.query)
    search_terms = query.get("s", [])
    return path == "/" and any(term.strip() for term in search_terms)


def get_url_kind(url: str) -> str:
    normalized_url = normalize_url(url)
    parts = urlsplit(normalized_url)
    path = parts.path

    if parts.netloc.lower() != ALLOWED_SITE_HOST:
        raise RuntimeError("momon-ga.com のURLのみ入力できます。")

    if contains_embedded_url(path):
        raise RuntimeError("URLの途中に別のURLが連結されています。1行に1URLだけ入力してください。")

    if WORK_PATH_PATTERN.search(path):
        return "work"
    if is_collection_path(path) or is_search_result_url(normalized_url):
        return "collection"

    raise RuntimeError("作品のURL、作者URLまたは、サークルURLを入力して下さい。")


def filter_supported_urls(urls, source_label: str):
    supported_urls = []

    for url in urls:
        try:
            normalized_url = normalize_url(url)
            get_url_kind(normalized_url)
        except RuntimeError:
            print(f"警告: {source_label} に未対応URLが含まれていたため無視します: {url}")
            continue

        supported_urls.append(normalized_url)

    return supported_urls
