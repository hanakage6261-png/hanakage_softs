import collections
import os
import re
import sqlite3
import sys


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from momonGA_registry import load_module

metadata_store = load_module("metadata_store")
get_database_path = metadata_store.get_database_path


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
    connection = sqlite3.connect(get_database_path())
    connection.row_factory = sqlite3.Row
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
