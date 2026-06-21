import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from momonGA_registry import load_module

metadata_store = load_module("metadata_store")
open_metadata_connection = metadata_store.open_metadata_connection


def main():
    connection = open_metadata_connection()

    try:
        row = connection.execute(
            """
            SELECT *
            FROM works
            WHERE status = 'found'
            ORDER BY RANDOM()
            LIMIT 1
            """
        ).fetchone()
        print(tuple(row) if row is not None else None)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
