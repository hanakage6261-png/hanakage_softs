import json
import os
import sys
from pathlib import Path


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
for candidate_dir in (Path(BASE_DIR), *Path(BASE_DIR).parents):
    registry_dir = candidate_dir / "00_momonGA_master"
    registry_path = registry_dir / "momonGA_registry.py"
    if registry_path.exists():
        if str(registry_dir) not in sys.path:
            sys.path.insert(0, str(registry_dir))
        break
else:
    raise RuntimeError("00_momonGA_master/momonGA_registry.py が見つかりません。")

from momonGA_registry import load_module

metadata_store = load_module("metadata_store")
get_joined_view_name = metadata_store.get_joined_view_name
open_metadata_connection = metadata_store.open_metadata_connection


SEARCH_COLUMNS = (
    "title",
    "date",
    "type",
    "parody",
    "circle",
    "author",
    "characters",
    "content",
    "url",
    "final_url",
    "current_file_name",
)


def decode_json_list(value):
    if not value:
        return []
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return [value]
    return data if isinstance(data, list) else [str(data)]


def format_list(value):
    return ", ".join(decode_json_list(value))


def search(connection, keyword: str, limit: int):
    where_clause = " OR ".join(f"{column} LIKE ?" for column in SEARCH_COLUMNS)
    params = [f"%{keyword}%"] * len(SEARCH_COLUMNS)
    params.append(limit)
    view_name = get_joined_view_name()
    return connection.execute(
        f"""
        SELECT
            id,
            title,
            date,
            type,
            pages,
            author,
            circle,
            status,
            downloaded,
            download_count,
            file_present,
            current_file_name,
            file_count,
            metadata_check_count,
            last_metadata_checked_at,
            final_url
        FROM {view_name}
        WHERE {where_clause}
        ORDER BY id
        LIMIT ?
        """,
        params,
    ).fetchall()


def main():
    connection = open_metadata_connection()

    try:
        keyword = input("検索語: ").strip()
        if not keyword:
            print("検索語が空です。")
            return

        raw_limit = input("最大表示件数(空Enterで50): ").strip()
        limit = int(raw_limit) if raw_limit.isdigit() and int(raw_limit) > 0 else 50
        rows = search(connection, keyword, limit)

        print(f"\n{len(rows)} 件表示します。")
        for row in rows:
            print("=" * 60)
            print(f"ID: {row['id']}")
            print(f"title: {row['title']}")
            print(f"date/type/pages: {row['date']} / {row['type']} / {row['pages']}")
            print(f"author: {format_list(row['author'])}")
            print(f"circle: {format_list(row['circle'])}")
            print(
                "status/downloaded/file_present: "
                f"{row['status']} / {row['downloaded']} / {row['file_present']}"
            )
            print(
                "download_count/file_count/check_count: "
                f"{row['download_count']} / {row['file_count']} / {row['metadata_check_count']}"
            )
            print(f"current_file_name: {row['current_file_name']}")
            print(f"last_metadata_checked_at: {row['last_metadata_checked_at']}")
            print(f"url: {row['final_url']}")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
