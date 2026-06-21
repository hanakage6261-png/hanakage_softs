import json
import os
import shutil
import sqlite3
import time

from momonGA_registry import get_directory


PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEMS_ROOT_DIR = os.path.dirname(PACKAGE_DIR)
DB_FILE_NAME = "momonGA_metadata.db"
LEGACY_DB_FILE_NAME = "momon.db"
DB_PATH = os.path.join(PACKAGE_DIR, DB_FILE_NAME)
SEARCH_DIR = os.fspath(get_directory("metadata_searching"))
LEGACY_DB_PATHS = [
    os.path.join(PACKAGE_DIR, LEGACY_DB_FILE_NAME),
    os.path.join(SYSTEMS_ROOT_DIR, DB_FILE_NAME),
    os.path.join(SYSTEMS_ROOT_DIR, LEGACY_DB_FILE_NAME),
    os.path.join(SYSTEMS_ROOT_DIR, "momonGA_metadata.db"),
    os.path.join(SYSTEMS_ROOT_DIR, "momon.db"),
    os.path.join(SYSTEMS_ROOT_DIR, "momonGA_searching", LEGACY_DB_FILE_NAME),
    os.path.join(SEARCH_DIR, LEGACY_DB_FILE_NAME),
]
DB_BUSY_TIMEOUT_MS = 30000
DB_LOCK_RETRY_ATTEMPTS = 20
DB_LOCK_RETRY_SECONDS = 0.5


def ensure_database_file():
    if os.path.exists(DB_PATH):
        return DB_PATH

    for legacy_db_path in LEGACY_DB_PATHS:
        if not os.path.exists(legacy_db_path):
            continue

        try:
            shutil.copy2(legacy_db_path, DB_PATH)
            return DB_PATH
        except PermissionError:
            return legacy_db_path

    return DB_PATH


def get_database_path():
    return ensure_database_file()


def open_metadata_connection():
    database_path = get_database_path()

    connection = sqlite3.connect(database_path, timeout=DB_BUSY_TIMEOUT_MS / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute(f"PRAGMA busy_timeout = {DB_BUSY_TIMEOUT_MS}")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    initialize_schema(connection)
    return connection


def initialize_schema(connection):
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS works (
            id INTEGER PRIMARY KEY,
            title TEXT,
            date TEXT,
            type TEXT,
            pages INTEGER,
            parody TEXT,
            circle TEXT,
            author TEXT,
            characters TEXT,
            content TEXT,
            url TEXT,
            final_url TEXT,
            status TEXT,
            downloaded INTEGER NOT NULL DEFAULT 0
        )
        """
    )

    column_names = {
        row["name"]
        for row in cursor.execute("PRAGMA table_info(works)").fetchall()
    }
    if "downloaded" not in column_names:
        cursor.execute(
            "ALTER TABLE works ADD COLUMN downloaded INTEGER NOT NULL DEFAULT 0"
        )

    connection.commit()


def _clean_text(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _serialize_list(values):
    if values is None:
        return None
    return json.dumps(list(values), ensure_ascii=False)


def build_work_record(data, downloaded=False):
    return {
        "id": int(data["id"]),
        "title": _clean_text(data.get("title")),
        "date": _clean_text(data.get("date")),
        "type": _clean_text(data.get("type")),
        "pages": data.get("pages"),
        "parody": _serialize_list(data.get("parody")),
        "circle": _serialize_list(data.get("circle")),
        "author": _serialize_list(data.get("author")),
        "characters": _serialize_list(data.get("characters")),
        "content": _serialize_list(data.get("content")),
        "url": _clean_text(data.get("url")),
        "final_url": _clean_text(data.get("final_url")),
        "status": _clean_text(data.get("status")),
        "downloaded": 1 if downloaded else 0,
    }


def _execute_with_db_retry(connection, query: str, params):
    last_error = None

    for attempt in range(1, DB_LOCK_RETRY_ATTEMPTS + 1):
        cursor = connection.cursor()
        try:
            cursor.execute(query, params)
            connection.commit()
            return
        except sqlite3.OperationalError as exc:
            last_error = exc
            message = str(exc).lower()
            if "database is locked" not in message and "database table is locked" not in message:
                raise
            if attempt < DB_LOCK_RETRY_ATTEMPTS:
                time.sleep(DB_LOCK_RETRY_SECONDS)
                continue
            raise

    if last_error is not None:
        raise last_error


def upsert_work(connection, data, downloaded=False):
    record = build_work_record(data, downloaded=downloaded)
    _execute_with_db_retry(
        connection,
        """
        INSERT INTO works (
            id, title, date, type, pages,
            parody, circle, author, characters, content,
            url, final_url, status, downloaded
        ) VALUES (
            :id, :title, :date, :type, :pages,
            :parody, :circle, :author, :characters, :content,
            :url, :final_url, :status, :downloaded
        )
        ON CONFLICT(id) DO UPDATE SET
            title = COALESCE(excluded.title, works.title),
            date = COALESCE(excluded.date, works.date),
            type = COALESCE(excluded.type, works.type),
            pages = COALESCE(excluded.pages, works.pages),
            parody = COALESCE(excluded.parody, works.parody),
            circle = COALESCE(excluded.circle, works.circle),
            author = COALESCE(excluded.author, works.author),
            characters = COALESCE(excluded.characters, works.characters),
            content = COALESCE(excluded.content, works.content),
            url = COALESCE(excluded.url, works.url),
            final_url = COALESCE(excluded.final_url, works.final_url),
            status = CASE
                WHEN excluded.status = 'found' THEN 'found'
                WHEN works.status IS NULL THEN excluded.status
                ELSE works.status
            END,
            downloaded = CASE
                WHEN works.downloaded = 1 OR excluded.downloaded = 1 THEN 1
                ELSE 0
            END
        """
        ,
        record,
    )


def overwrite_work_metadata(connection, data):
    record = build_work_record(data, downloaded=False)
    _execute_with_db_retry(
        connection,
        """
        INSERT INTO works (
            id, title, date, type, pages,
            parody, circle, author, characters, content,
            url, final_url, status, downloaded
        ) VALUES (
            :id, :title, :date, :type, :pages,
            :parody, :circle, :author, :characters, :content,
            :url, :final_url, :status, 0
        )
        ON CONFLICT(id) DO UPDATE SET
            title = excluded.title,
            date = excluded.date,
            type = excluded.type,
            pages = excluded.pages,
            parody = excluded.parody,
            circle = excluded.circle,
            author = excluded.author,
            characters = excluded.characters,
            content = excluded.content,
            url = excluded.url,
            final_url = excluded.final_url,
            status = excluded.status,
            downloaded = works.downloaded
        """,
        record,
    )


def work_record_exists(connection, work_id: int) -> bool:
    row = connection.execute(
        "SELECT 1 FROM works WHERE id = ? LIMIT 1",
        (int(work_id),),
    ).fetchone()
    return row is not None


def mark_downloaded(connection, work_id: int):
    _execute_with_db_retry(
        connection,
        """
        INSERT INTO works (id, downloaded)
        VALUES (?, 1)
        ON CONFLICT(id) DO UPDATE SET downloaded = 1
        """,
        (int(work_id),),
    )
