import json
import os
import sqlite3
import sys


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from momonGA_metadata_store import get_database_path


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
    return connection.execute(
        f"""
        SELECT id, title, date, type, pages, author, circle, status, downloaded, final_url
        FROM works
        WHERE {where_clause}
        ORDER BY id
        LIMIT ?
        """,
        params,
    ).fetchall()


def main():
    connection = sqlite3.connect(get_database_path())
    connection.row_factory = sqlite3.Row

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
            print(f"status/downloaded: {row['status']} / {row['downloaded']}")
            print(f"url: {row['final_url']}")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
