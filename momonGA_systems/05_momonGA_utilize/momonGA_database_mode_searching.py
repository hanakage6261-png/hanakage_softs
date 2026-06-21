import collections
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
open_metadata_connection = metadata_store.open_metadata_connection


FIELDS = {
    "1": "author",
    "2": "circle",
    "3": "parody",
    "4": "characters",
    "5": "content",
    "6": "type",
    "7": "date",
}
LIST_FIELDS = {"author", "circle", "parody", "characters", "content"}


def iter_values(raw_value, is_list_field: bool):
    if not raw_value:
        return []
    if not is_list_field:
        return [str(raw_value).strip()]
    try:
        data = json.loads(raw_value)
    except json.JSONDecodeError:
        return [str(raw_value).strip()]
    if not isinstance(data, list):
        return [str(data).strip()]
    return [str(value).strip() for value in data if str(value).strip()]


def main():
    print("集計するフィールドを選んでください。")
    for key, field in FIELDS.items():
        print(f"[{key}] {field}")

    choice = input("番号: ").strip()
    field = FIELDS.get(choice)
    if not field:
        print("無効な番号です。")
        return

    raw_limit = input("表示件数(空Enterで30): ").strip()
    limit = int(raw_limit) if raw_limit.isdigit() and int(raw_limit) > 0 else 30

    connection = open_metadata_connection()
    counter = collections.Counter()

    try:
        rows = connection.execute(
            f"SELECT {field} FROM works WHERE status = 'found'"
        ).fetchall()
        for row in rows:
            for value in iter_values(row[field], field in LIST_FIELDS):
                counter[value] += 1

    finally:
        connection.close()

    print(f"\n{field} ranking")
    for index, (value, count) in enumerate(counter.most_common(limit), 1):
        print(f"{index:>3}. {count:>6}  {value}")


if __name__ == "__main__":
    main()
