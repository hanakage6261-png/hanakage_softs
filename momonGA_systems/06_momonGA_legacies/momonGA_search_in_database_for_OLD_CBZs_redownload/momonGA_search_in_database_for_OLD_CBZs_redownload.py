import importlib
import sys
from datetime import datetime
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
    raise RuntimeError("00_momonGA_master/momonGA_registry.py was not found.")

momonGA_registry = importlib.import_module("momonGA_registry")
load_module = momonGA_registry.load_module

metadata_store = load_module("metadata_store")
get_joined_view_name = metadata_store.get_joined_view_name
open_metadata_connection = metadata_store.open_metadata_connection


OUTPUT_DIR = CURRENT_DIR / "output"
OUTPUT_FILE_PREFIX = "momonGA_old_cbz_redownload_urls"


def build_output_path() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return OUTPUT_DIR / f"{OUTPUT_FILE_PREFIX}_{timestamp}.txt"


def fetch_downloaded_work_urls(connection):
    view_name = get_joined_view_name()
    rows = connection.execute(
        f"""
        SELECT
            id,
            title,
            COALESCE(NULLIF(TRIM(final_url), ''), NULLIF(TRIM(url), '')) AS resolved_url
        FROM {view_name}
        WHERE downloaded = 1
          AND status = 'found'
          AND COALESCE(NULLIF(TRIM(final_url), ''), NULLIF(TRIM(url), '')) IS NOT NULL
        ORDER BY id
        """
    ).fetchall()
    return rows


def dedupe_urls(rows):
    unique_urls = []
    seen_urls = set()

    for row in rows:
        url = str(row["resolved_url"]).strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        unique_urls.append(url)

    return unique_urls


def write_url_file(output_path: Path, urls):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as file:
        for url in urls:
            file.write(f"{url}\n")


def main():
    connection = open_metadata_connection()
    try:
        rows = fetch_downloaded_work_urls(connection)
    finally:
        connection.close()

    urls = dedupe_urls(rows)
    output_path = build_output_path()
    write_url_file(output_path, urls)

    print(f"Downloaded works found: {len(rows)}")
    print(f"URLs written: {len(urls)}")
    print(f"Output file: {output_path}")


if __name__ == "__main__":
    main()
