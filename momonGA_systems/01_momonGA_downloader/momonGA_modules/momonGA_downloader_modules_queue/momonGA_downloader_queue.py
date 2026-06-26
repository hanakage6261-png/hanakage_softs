from __future__ import annotations

import json
import os
import re
import time

from momonGA_modules.momonGA_downloader_modules_shared.momonGA_downloader_shared import (
    RESUME_SAVE_RETRY_ATTEMPTS,
    RESUME_SAVE_RETRY_SECONDS,
    RESUME_TEMP_SUFFIX,
    WorkSummary,
    ensure_resume_directory_exists,
    filter_supported_urls,
    get_legacy_resume_file_path,
    get_resume_file_path,
    get_url_kind,
    normalize_url,
)


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


def prompt_exclude_downloaded_works(downloaded_ids, works):
    if not works:
        return works

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


def _build_resume_candidate_paths():
    primary_resume = get_resume_file_path()
    primary_temp = f"{primary_resume}{RESUME_TEMP_SUFFIX}"

    candidate_paths = []
    for path in (primary_resume, primary_temp):
        if path not in candidate_paths:
            candidate_paths.append(path)

    if os.path.exists(primary_resume) or os.path.exists(primary_temp):
        return candidate_paths

    legacy_resume = get_legacy_resume_file_path()
    legacy_temp = f"{legacy_resume}{RESUME_TEMP_SUFFIX}"
    for path in (legacy_resume, legacy_temp):
        if path not in candidate_paths:
            candidate_paths.append(path)
    return candidate_paths


def _load_resume_state_from_path(path: str, source_label: str):
    try:
        with open(path, "r", encoding="utf-8") as file:
            raw_state = json.load(file)
    except Exception:
        return None

    current_url = raw_state.get("current_url")
    if current_url:
        current_url = normalize_url(current_url)
        try:
            get_url_kind(current_url)
        except RuntimeError:
            print(f"警告: {source_label} の current_url が不正だったため無視します: {current_url}")
            current_url = None

    pending_urls = filter_supported_urls(
        dedupe_urls(raw_state.get("pending_urls", [])),
        source_label,
    )
    if current_url:
        pending_urls = [url for url in pending_urls if url != current_url]

    return {
        "current_url": current_url,
        "pending_urls": pending_urls,
    }


def _save_resume_state_to_path(resume_file_path: str, state: dict):
    ensure_resume_directory_exists()
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


def migrate_legacy_resume_file_if_needed():
    primary_resume = get_resume_file_path()
    primary_temp = f"{primary_resume}{RESUME_TEMP_SUFFIX}"
    if os.path.exists(primary_resume) or os.path.exists(primary_temp):
        return

    legacy_resume = get_legacy_resume_file_path()
    legacy_temp = f"{legacy_resume}{RESUME_TEMP_SUFFIX}"

    for candidate_path, label in (
        (legacy_resume, "旧再開キュー"),
        (legacy_temp, "旧一時再開キュー"),
    ):
        if not os.path.exists(candidate_path):
            continue

        state = _load_resume_state_from_path(candidate_path, label)
        if state is None:
            continue

        if _save_resume_state_to_path(primary_resume, state):
            for obsolete_path in (legacy_resume, legacy_temp):
                if not os.path.exists(obsolete_path):
                    continue
                try:
                    os.remove(obsolete_path)
                except OSError:
                    pass
            print("旧来の root 直下の再開キューを modules 配下へ移行しました。")
            print(f"移行元: {candidate_path}")
            print(f"移行先: {primary_resume}")
        return


def load_resume_queue():
    migrate_legacy_resume_file_if_needed()

    candidate_paths = [
        path for path in _build_resume_candidate_paths()
        if os.path.exists(path)
    ]

    if not candidate_paths:
        return []

    candidate_paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    for candidate_path in candidate_paths:
        state = _load_resume_state_from_path(candidate_path, "再開キュー")
        if state is None:
            continue
        if candidate_path.endswith(RESUME_TEMP_SUFFIX):
            print("前回の一時再開ファイルを復元に使用します。")
        break
    else:
        state = None

    if state is None:
        print("再開情報の読み込みに失敗したため、再開キューは無視します。")
        return []

    restored_urls = []
    current_url = state["current_url"]
    pending_urls = state["pending_urls"]

    if current_url:
        restored_urls.append(current_url)
    restored_urls.extend(pending_urls)
    restored_urls = dedupe_urls(restored_urls)

    if restored_urls:
        print(f"前回未完了のURLを {len(restored_urls)} 件復元しました。")

    return restored_urls


def save_resume_state(current_url, pending_urls):
    resume_file_path = get_resume_file_path()
    state = {
        "current_url": normalize_url(current_url) if current_url else None,
        "pending_urls": dedupe_urls(pending_urls),
    }
    return _save_resume_state_to_path(resume_file_path, state)


def clear_resume_state():
    for path in (
        get_resume_file_path(),
        f"{get_resume_file_path()}{RESUME_TEMP_SUFFIX}",
        get_legacy_resume_file_path(),
        f"{get_legacy_resume_file_path()}{RESUME_TEMP_SUFFIX}",
    ):
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
