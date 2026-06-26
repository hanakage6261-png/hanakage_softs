import csv
import importlib
import json
import os
import sys
import time
from pathlib import Path


CURRENT_DIR = Path(__file__).resolve().parent
for candidate_dir in (CURRENT_DIR, *CURRENT_DIR.parents):
    registry_dir = candidate_dir / "00_momonGA_master"
    registry_path = registry_dir / "momonGA_registry.py"
    if registry_path.exists():
        if str(registry_dir) not in sys.path:
            sys.path.insert(0, str(registry_dir))
        break
else:
    raise RuntimeError("00_momonGA_master/momonGA_registry.py was not found.")

momonGA_registry = importlib.import_module("momonGA_registry")
load_module = momonGA_registry.load_module

url_rules = load_module("url_rules")
filter_supported_urls = url_rules.filter_supported_urls
normalize_url = url_rules.normalize_url

downloader_module = load_module("downloader_main")
RESUME_TEMP_SUFFIX = downloader_module.RESUME_TEMP_SUFFIX
RESUME_SAVE_RETRY_ATTEMPTS = downloader_module.RESUME_SAVE_RETRY_ATTEMPTS
RESUME_SAVE_RETRY_SECONDS = downloader_module.RESUME_SAVE_RETRY_SECONDS
dedupe_urls = downloader_module.dedupe_urls
get_resume_file_path = downloader_module.get_resume_file_path


ENCODINGS = ("utf-8-sig", "utf-8", "cp932")


def resolve_input_path(raw_path: str) -> Path:
    cleaned = raw_path.strip().strip('"').strip("'")
    if not cleaned:
        raise ValueError("ファイルパスが入力されていません。")

    path = Path(cleaned).expanduser()
    if not path.is_absolute():
        raise ValueError("絶対パスで入力してください。")
    if not path.exists():
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")
    if not path.is_file():
        raise ValueError(f"ファイルではありません: {path}")
    return path


def read_text_lines(path: Path):
    last_error = None
    for encoding in ENCODINGS:
        try:
            with open(path, "r", encoding=encoding, newline="") as file:
                return file.read().splitlines()
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

    if last_error is not None:
        raise last_error
    return []


def read_txt_urls(path: Path):
    urls = []
    for line in read_text_lines(path):
        cleaned = line.strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        urls.append(cleaned)
    return urls


def read_csv_urls(path: Path):
    rows = list(csv.reader(read_text_lines(path)))
    if not rows:
        return []

    header = [cell.strip().lower() for cell in rows[0]]
    use_header = "url" in header
    column_index = header.index("url") if use_header else 0
    target_rows = rows[1:] if use_header else rows

    urls = []
    for row in target_rows:
        if column_index >= len(row):
            continue
        cleaned = row[column_index].strip()
        if not cleaned or cleaned.startswith("#"):
            continue
        urls.append(cleaned)
    return urls


def load_url_list(raw_path: str):
    path = resolve_input_path(raw_path)
    suffix = path.suffix.lower()

    if suffix == ".txt":
        urls = read_txt_urls(path)
    elif suffix == ".csv":
        urls = read_csv_urls(path)
    else:
        raise ValueError("対応している拡張子は .txt と .csv のみです。")

    normalized_urls = [normalize_url(url) for url in urls]
    deduped_urls = dedupe_urls(normalized_urls)
    return path, filter_supported_urls(deduped_urls, f"入力ファイル {path.name}")


def load_resume_state():
    resume_file_path = get_resume_file_path()
    temp_resume_file_path = f"{resume_file_path}{RESUME_TEMP_SUFFIX}"

    candidate_paths = []
    if os.path.exists(resume_file_path):
        candidate_paths.append(resume_file_path)
    if os.path.exists(temp_resume_file_path):
        candidate_paths.append(temp_resume_file_path)

    if not candidate_paths:
        return {"current_url": None, "pending_urls": []}

    candidate_paths.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    for candidate_path in candidate_paths:
        try:
            with open(candidate_path, "r", encoding="utf-8") as file:
                state = json.load(file)
            current_url = normalize_url(state.get("current_url")) if state.get("current_url") else None
            pending_urls = dedupe_urls(state.get("pending_urls", []))
            return {
                "current_url": current_url,
                "pending_urls": pending_urls,
            }
        except Exception:
            continue

    return {"current_url": None, "pending_urls": []}


def save_resume_state(current_url, pending_urls):
    resume_file_path = get_resume_file_path()
    temp_path = f"{resume_file_path}{RESUME_TEMP_SUFFIX}"

    state = {
        "current_url": normalize_url(current_url) if current_url else None,
        "pending_urls": dedupe_urls(pending_urls),
    }

    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(state, file, ensure_ascii=False, indent=2)

    last_error = None
    for attempt in range(1, RESUME_SAVE_RETRY_ATTEMPTS + 1):
        try:
            os.replace(temp_path, resume_file_path)
            return
        except PermissionError as exc:
            last_error = exc
            if attempt < RESUME_SAVE_RETRY_ATTEMPTS:
                time.sleep(RESUME_SAVE_RETRY_SECONDS)
                continue
        except OSError as exc:
            last_error = exc
            break

    raise RuntimeError(f"再開キューファイルの更新に失敗しました: {last_error}")


def merge_urls_into_resume(new_urls):
    state = load_resume_state()
    current_url = state["current_url"]
    existing_pending_urls = state["pending_urls"]

    merged_pending_urls = dedupe_urls(list(new_urls) + existing_pending_urls)
    if current_url:
        merged_pending_urls = [
            url for url in merged_pending_urls
            if url != current_url
        ]

    save_resume_state(current_url, merged_pending_urls)
    return current_url, existing_pending_urls, merged_pending_urls


def prompt_input_path():
    print("読み込む txt または csv ファイルの絶対パスを入力してください。")
    print("txt は 1 行 1 URL、csv は url 列または 1 列目を読み込みます。")
    return input("ファイルパス: ").strip()


def main():
    raw_path = prompt_input_path()
    if not raw_path:
        print("入力を中止しました。")
        return

    input_path, new_urls = load_url_list(raw_path)
    if not new_urls:
        print(f"有効なURLが見つかりませんでした: {input_path}")
        return

    current_url, existing_pending_urls, merged_pending_urls = merge_urls_into_resume(new_urls)

    print(f"入力ファイル: {input_path}")
    print(f"新規に読み込んだURL数: {len(new_urls)}")
    print(f"既存の pending_urls 数: {len(existing_pending_urls)}")
    print(f"統合後の pending_urls 数: {len(merged_pending_urls)}")
    if current_url:
        print(f"current_url は維持しました: {current_url}")
    else:
        print("current_url は未設定です。")
    print(f"更新先: {get_resume_file_path()}")


if __name__ == "__main__":
    main()
