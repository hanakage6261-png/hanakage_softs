from __future__ import annotations

import time

import requests
from bs4 import BeautifulSoup

from momonGA_modules.momonGA_downloader_modules_shared.momonGA_downloader_shared import (
    HEADERS,
    INITIAL_BACKOFF_SECONDS,
    MAX_BACKOFF_SECONDS,
    RETRYABLE_STATUS_CODES,
    TIMEOUT,
)


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
