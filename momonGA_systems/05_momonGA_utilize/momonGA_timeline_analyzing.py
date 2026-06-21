import collections
import os
import re
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


DATE_PATTERN = re.compile(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})")


def parse_year_month(date_text):
    if not date_text:
        return None
    match = DATE_PATTERN.search(date_text)
    if not match:
        return None
    year, month, _day = match.groups()
    return f"{int(year):04d}-{int(month):02d}"


def main():
    connection = open_metadata_connection()
    counter = collections.Counter()
    unknown = 0

    try:
        rows = connection.execute(
            "SELECT date FROM works WHERE status = 'found'"
        ).fetchall()
        for row in rows:
            year_month = parse_year_month(row["date"])
            if year_month:
                counter[year_month] += 1
            else:
                unknown += 1

    finally:
        connection.close()

    print("month | works")
    for year_month in sorted(counter):
        print(f"{year_month} | {counter[year_month]}")
    print(f"unknown | {unknown}")


if __name__ == "__main__":
    main()
