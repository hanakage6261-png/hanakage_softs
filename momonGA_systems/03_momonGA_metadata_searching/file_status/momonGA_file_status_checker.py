import importlib
import json
import os
import re
import sys
from collections import defaultdict
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
    raise RuntimeError("00_momonGA_master/momonGA_registry.py が見つかりません。")

momonGA_registry = importlib.import_module("momonGA_registry")
get_directory = momonGA_registry.get_directory
load_module = momonGA_registry.load_module

metadata_store = load_module("metadata_store")
open_metadata_connection = metadata_store.open_metadata_connection
reset_all_file_statuses = metadata_store.reset_all_file_statuses
update_file_status = metadata_store.update_file_status


CONFIG_PATH = get_directory("metadata_searching") / "momonGA_file_status_checker_paths.json"
CBZ_SUFFIX = ".cbz"
WORK_ID_PATTERN = re.compile(r"(?P<id>\d+)(?: \(\d+\))?$")


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"設定ファイルがありません: {CONFIG_PATH}")

    with open(CONFIG_PATH, "r", encoding="utf-8") as file:
        config = json.load(file)

    search_roots = [
        Path(str(raw_path)).expanduser()
        for raw_path in config.get("search_roots", [])
        if str(raw_path).strip()
    ]
    require_all_roots = bool(config.get("require_all_roots", True))
    return search_roots, require_all_roots


def validate_roots(search_roots, require_all_roots: bool):
    if not search_roots:
        raise RuntimeError(
            f"検索対象パスが未設定です。{CONFIG_PATH} の search_roots を設定してください。"
        )

    existing_roots = [path for path in search_roots if path.exists()]
    missing_roots = [path for path in search_roots if not path.exists()]

    if missing_roots:
        print("見つからない検索対象パス:")
        for path in missing_roots:
            print(f"- {path}")

    if require_all_roots and missing_roots:
        raise RuntimeError(
            "require_all_roots=true のため、未接続または未存在のパスがある状態では更新しません。"
        )

    if not existing_roots:
        raise RuntimeError("利用可能な検索対象パスがありません。")

    return existing_roots


def extract_work_id(path: Path):
    if path.suffix.lower() != CBZ_SUFFIX:
        return None
    match = WORK_ID_PATTERN.search(path.stem)
    if not match:
        return None
    return int(match.group("id"))


def scan_cbz_files(search_roots):
    indexed_files = defaultdict(list)
    ignored_files = []

    for root in search_roots:
        print(f"走査中: {root}")
        for cbz_path in root.rglob(f"*{CBZ_SUFFIX}"):
            work_id = extract_work_id(cbz_path)
            if work_id is None:
                ignored_files.append(cbz_path)
                continue
            indexed_files[work_id].append(cbz_path)

    return indexed_files, ignored_files


def choose_primary_file(paths):
    return max(paths, key=lambda path: path.stat().st_mtime)


def update_database(indexed_files):
    connection = open_metadata_connection()

    try:
        reset_all_file_statuses(connection)
        for work_id, paths in sorted(indexed_files.items()):
            primary_path = choose_primary_file(paths)
            update_file_status(
                connection,
                work_id,
                True,
                primary_path.name,
                len(paths),
            )
    finally:
        connection.close()


def main():
    search_roots, require_all_roots = load_config()
    existing_roots = validate_roots(search_roots, require_all_roots)
    indexed_files, ignored_files = scan_cbz_files(existing_roots)
    update_database(indexed_files)

    duplicate_ids = {
        work_id: paths
        for work_id, paths in indexed_files.items()
        if len(paths) > 1
    }

    print("")
    print(f"対象ルート数: {len(existing_roots)}")
    print(f"CBZを検出したID数: {len(indexed_files)}")
    print(f"ID付きCBZ総数: {sum(len(paths) for paths in indexed_files.values())}")
    print(f"重複ID数: {len(duplicate_ids)}")
    print(f"IDを読めず除外したCBZ数: {len(ignored_files)}")

    if duplicate_ids:
        print("\n重複ID一覧:")
        for work_id, paths in sorted(duplicate_ids.items()):
            names = ", ".join(path.name for path in sorted(paths))
            print(f"- {work_id}: {names}")

    if ignored_files:
        print("\nIDを読めなかったCBZ:")
        for path in ignored_files[:20]:
            print(f"- {path}")
        if len(ignored_files) > 20:
            print(f"... and {len(ignored_files) - 20} more")


if __name__ == "__main__":
    main()
