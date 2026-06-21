import json
import os
import sys


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from momonGA_registry import load_module

metadata_store = load_module("metadata_store")
get_joined_view_name = metadata_store.get_joined_view_name
open_metadata_connection = metadata_store.open_metadata_connection


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
    "download_count",
    "file_present",
    "current_file_name",
    "file_count",
    "metadata_check_count",
    "last_metadata_checked_at",
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
    connection = open_metadata_connection()
    view_name = get_joined_view_name()

    try:
        total = connection.execute(f"SELECT COUNT(*) FROM {view_name}").fetchone()[0]
        found = connection.execute(
            f"SELECT COUNT(*) FROM {view_name} WHERE status = 'found'"
        ).fetchone()[0]
        print(f"total rows: {total}")
        print(f"found rows: {found}")
        print("")

        for field in FIELDS:
            non_empty = connection.execute(
                f"SELECT COUNT(*) FROM {view_name} WHERE {field} IS NOT NULL AND {field} != ''"
            ).fetchone()[0]
            distinct = connection.execute(
                f"SELECT COUNT(DISTINCT {field}) FROM {view_name} WHERE {field} IS NOT NULL AND {field} != ''"
            ).fetchone()[0]

            if field in LIST_FIELDS:
                item_count = 0
                for row in connection.execute(f"SELECT {field} FROM {view_name}"):
                    item_count += list_length(row[field])
                print(
                    f"{field:>24}: non_empty={non_empty:>6} distinct_raw={distinct:>6} list_items={item_count:>7}"
                )
            else:
                print(f"{field:>24}: non_empty={non_empty:>6} distinct={distinct:>6}")

    finally:
        connection.close()


if __name__ == "__main__":
    main()
