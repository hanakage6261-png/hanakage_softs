import json
import os
import sqlite3
import sys


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from momonGA_registry import load_module

metadata_store = load_module("metadata_store")
get_database_path = metadata_store.get_database_path


FIELDS = (
    "title",
    "date",
    "type",
    "pages",
    "parody",
    "circle",
    "author",
    "characters",
    "content",
    "url",
    "final_url",
    "status",
    "downloaded",
)
LIST_FIELDS = {"parody", "circle", "author", "characters", "content"}


def list_length(value):
    if not value:
        return 0
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return 1
    if isinstance(data, list):
        return len([item for item in data if str(item).strip()])
    return 1


def main():
    connection = sqlite3.connect(get_database_path())
    connection.row_factory = sqlite3.Row

    try:
        total = connection.execute("SELECT COUNT(*) FROM works").fetchone()[0]
        found = connection.execute(
            "SELECT COUNT(*) FROM works WHERE status = 'found'"
        ).fetchone()[0]
        print(f"total rows: {total}")
        print(f"found rows: {found}")
        print("")

        for field in FIELDS:
            non_empty = connection.execute(
                f"SELECT COUNT(*) FROM works WHERE {field} IS NOT NULL AND {field} != ''"
            ).fetchone()[0]
            distinct = connection.execute(
                f"SELECT COUNT(DISTINCT {field}) FROM works WHERE {field} IS NOT NULL AND {field} != ''"
            ).fetchone()[0]

            if field in LIST_FIELDS:
                item_count = 0
                for row in connection.execute(f"SELECT {field} FROM works"):
                    item_count += list_length(row[field])
                print(
                    f"{field:>10}: non_empty={non_empty:>6} distinct_raw={distinct:>6} list_items={item_count:>7}"
                )
            else:
                print(f"{field:>10}: non_empty={non_empty:>6} distinct={distinct:>6}")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
