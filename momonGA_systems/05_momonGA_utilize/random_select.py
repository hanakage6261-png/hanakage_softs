import importlib
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
for candidate_dir in (BASE_DIR, *BASE_DIR.parents):
    registry_dir = candidate_dir / "00_momonGA_master"
    registry_path = registry_dir / "momonGA_registry.py"
    if registry_path.exists():
        if str(registry_dir) not in sys.path:
            sys.path.insert(0, str(registry_dir))
        break
else:
    raise RuntimeError("00_momonGA_master/momonGA_registry.py が見つかりません。")

momonGA_registry = importlib.import_module("momonGA_registry")
load_module = momonGA_registry.load_module

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
