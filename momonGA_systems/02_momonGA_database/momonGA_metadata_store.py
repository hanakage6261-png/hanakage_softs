import importlib
import json
import os
import shutil
import sqlite3
import sys
import time
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
    raise RuntimeError("00_momonGA_master/momonGA_registry.py が見つかりません。")

momonGA_registry = importlib.import_module("momonGA_registry")
get_directory = momonGA_registry.get_directory


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
WORKS_TABLE = "works"
WORK_STATE_TABLE = "work_state"
WORKS_WITH_STATE_VIEW = "works_with_state"
WORKS_COLUMNS = (
    "id",
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
)
WORKS_DEFINITION = """
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
    status TEXT
)
"""
WORK_STATE_COLUMN_DEFINITIONS = {
    "id": "INTEGER PRIMARY KEY",
    "downloaded": "INTEGER NOT NULL DEFAULT 0",
    "download_count": "INTEGER NOT NULL DEFAULT 0",
    "file_present": "INTEGER NOT NULL DEFAULT 0",
    "current_file_name": "TEXT",
    "file_count": "INTEGER NOT NULL DEFAULT 0",
    "metadata_check_count": "INTEGER NOT NULL DEFAULT 0",
    "last_metadata_checked_at": "TEXT",
}


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
    _ensure_work_state_table(cursor)
    _ensure_works_table(cursor)
    _ensure_work_state_rows(cursor)
    _recreate_joined_view(cursor)
    connection.commit()


def _table_exists(cursor, table_name: str) -> bool:
    row = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _get_column_names(cursor, table_name: str):
    return [
        row["name"]
        for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
    ]


def _ensure_work_state_table(cursor):
    cursor.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {WORK_STATE_TABLE} (
            id INTEGER PRIMARY KEY,
            downloaded INTEGER NOT NULL DEFAULT 0,
            download_count INTEGER NOT NULL DEFAULT 0,
            file_present INTEGER NOT NULL DEFAULT 0,
            current_file_name TEXT,
            file_count INTEGER NOT NULL DEFAULT 0,
            metadata_check_count INTEGER NOT NULL DEFAULT 0,
            last_metadata_checked_at TEXT
        )
        """
    )

    existing_columns = set(_get_column_names(cursor, WORK_STATE_TABLE))
    for column_name, definition in WORK_STATE_COLUMN_DEFINITIONS.items():
        if column_name in existing_columns:
            continue
        cursor.execute(
            f"ALTER TABLE {WORK_STATE_TABLE} ADD COLUMN {column_name} {definition}"
        )


def _ensure_works_table(cursor):
    if not _table_exists(cursor, WORKS_TABLE):
        cursor.execute(WORKS_DEFINITION)
        return

    existing_columns = _get_column_names(cursor, WORKS_TABLE)
    if tuple(existing_columns) == WORKS_COLUMNS:
        return

    _migrate_works_table(cursor, existing_columns)


def _migrate_works_table(cursor, existing_columns):
    if "downloaded" in existing_columns:
        cursor.execute(
            f"""
            INSERT INTO {WORK_STATE_TABLE} (id, downloaded, download_count)
            SELECT
                id,
                CASE WHEN COALESCE(downloaded, 0) != 0 THEN 1 ELSE 0 END,
                CASE WHEN COALESCE(downloaded, 0) != 0 THEN 1 ELSE 0 END
            FROM {WORKS_TABLE}
            WHERE id IS NOT NULL
            ON CONFLICT(id) DO UPDATE SET
                downloaded = CASE
                    WHEN {WORK_STATE_TABLE}.downloaded = 1 OR excluded.downloaded = 1 THEN 1
                    ELSE 0
                END,
                download_count = CASE
                    WHEN {WORK_STATE_TABLE}.download_count > excluded.download_count
                        THEN {WORK_STATE_TABLE}.download_count
                    ELSE excluded.download_count
                END
            """
        )

    cursor.execute(f"DROP VIEW IF EXISTS {WORKS_WITH_STATE_VIEW}")
    cursor.execute("DROP TABLE IF EXISTS works_schema_migration")
    cursor.execute(f"ALTER TABLE {WORKS_TABLE} RENAME TO works_schema_migration")
    cursor.execute(WORKS_DEFINITION)

    shared_columns = [
        column_name
        for column_name in WORKS_COLUMNS
        if column_name in existing_columns
    ]
    if shared_columns:
        columns_clause = ", ".join(shared_columns)
        cursor.execute(
            f"""
            INSERT INTO {WORKS_TABLE} ({columns_clause})
            SELECT {columns_clause}
            FROM works_schema_migration
            """
        )

    cursor.execute("DROP TABLE works_schema_migration")


def _ensure_work_state_rows(cursor):
    cursor.execute(
        f"""
        INSERT INTO {WORK_STATE_TABLE} (id)
        SELECT id
        FROM {WORKS_TABLE}
        WHERE id IS NOT NULL
        ON CONFLICT(id) DO NOTHING
        """
    )


def _recreate_joined_view(cursor):
    cursor.execute(f"DROP VIEW IF EXISTS {WORKS_WITH_STATE_VIEW}")
    cursor.execute(
        f"""
        CREATE VIEW {WORKS_WITH_STATE_VIEW} AS
        SELECT
            works.id,
            works.title,
            works.date,
            works.type,
            works.pages,
            works.parody,
            works.circle,
            works.author,
            works.characters,
            works.content,
            works.url,
            works.final_url,
            works.status,
            COALESCE(work_state.downloaded, 0) AS downloaded,
            COALESCE(work_state.download_count, 0) AS download_count,
            COALESCE(work_state.file_present, 0) AS file_present,
            work_state.current_file_name AS current_file_name,
            COALESCE(work_state.file_count, 0) AS file_count,
            COALESCE(work_state.metadata_check_count, 0) AS metadata_check_count,
            work_state.last_metadata_checked_at AS last_metadata_checked_at
        FROM {WORKS_TABLE} AS works
        LEFT JOIN {WORK_STATE_TABLE} AS work_state
            ON work_state.id = works.id
        """
    )


def _clean_text(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _clean_int(value):
    if value is None or value == "":
        return None
    return int(value)


def _serialize_list(values):
    if values is None:
        return None
    return json.dumps(list(values), ensure_ascii=False)


def build_work_record(data):
    return {
        "id": int(data["id"]),
        "title": _clean_text(data.get("title")),
        "date": _clean_text(data.get("date")),
        "type": _clean_text(data.get("type")),
        "pages": _clean_int(data.get("pages")),
        "parody": _serialize_list(data.get("parody")),
        "circle": _serialize_list(data.get("circle")),
        "author": _serialize_list(data.get("author")),
        "characters": _serialize_list(data.get("characters")),
        "content": _serialize_list(data.get("content")),
        "url": _clean_text(data.get("url")),
        "final_url": _clean_text(data.get("final_url")),
        "status": _clean_text(data.get("status")),
    }


def _execute_with_db_retry(connection, query: str, params=()):
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
            if (
                "database is locked" not in message
                and "database table is locked" not in message
            ):
                raise
            if attempt < DB_LOCK_RETRY_ATTEMPTS:
                time.sleep(DB_LOCK_RETRY_SECONDS)
                continue
            raise

    if last_error is not None:
        raise last_error


def _ensure_work_state_record(connection, work_id: int):
    _execute_with_db_retry(
        connection,
        f"INSERT OR IGNORE INTO {WORK_STATE_TABLE} (id) VALUES (?)",
        (int(work_id),),
    )


def get_joined_view_name():
    return WORKS_WITH_STATE_VIEW


def upsert_work(connection, data):
    record = build_work_record(data)
    _execute_with_db_retry(
        connection,
        f"""
        INSERT INTO {WORKS_TABLE} (
            id, title, date, type, pages,
            parody, circle, author, characters, content,
            url, final_url, status
        ) VALUES (
            :id, :title, :date, :type, :pages,
            :parody, :circle, :author, :characters, :content,
            :url, :final_url, :status
        )
        ON CONFLICT(id) DO UPDATE SET
            title = COALESCE(excluded.title, {WORKS_TABLE}.title),
            date = COALESCE(excluded.date, {WORKS_TABLE}.date),
            type = COALESCE(excluded.type, {WORKS_TABLE}.type),
            pages = COALESCE(excluded.pages, {WORKS_TABLE}.pages),
            parody = COALESCE(excluded.parody, {WORKS_TABLE}.parody),
            circle = COALESCE(excluded.circle, {WORKS_TABLE}.circle),
            author = COALESCE(excluded.author, {WORKS_TABLE}.author),
            characters = COALESCE(excluded.characters, {WORKS_TABLE}.characters),
            content = COALESCE(excluded.content, {WORKS_TABLE}.content),
            url = COALESCE(excluded.url, {WORKS_TABLE}.url),
            final_url = COALESCE(excluded.final_url, {WORKS_TABLE}.final_url),
            status = CASE
                WHEN excluded.status = 'found' THEN 'found'
                WHEN {WORKS_TABLE}.status IS NULL THEN excluded.status
                ELSE {WORKS_TABLE}.status
            END
        """,
        record,
    )
    _ensure_work_state_record(connection, record["id"])


def overwrite_work_metadata(connection, data):
    record = build_work_record(data)
    _execute_with_db_retry(
        connection,
        f"""
        INSERT INTO {WORKS_TABLE} (
            id, title, date, type, pages,
            parody, circle, author, characters, content,
            url, final_url, status
        ) VALUES (
            :id, :title, :date, :type, :pages,
            :parody, :circle, :author, :characters, :content,
            :url, :final_url, :status
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
            status = excluded.status
        """,
        record,
    )
    _ensure_work_state_record(connection, record["id"])


def work_record_exists(connection, work_id: int) -> bool:
    row = connection.execute(
        f"SELECT 1 FROM {WORKS_TABLE} WHERE id = ? LIMIT 1",
        (int(work_id),),
    ).fetchone()
    return row is not None


def record_download_event(connection, work_id: int):
    _execute_with_db_retry(
        connection,
        f"""
        INSERT INTO {WORK_STATE_TABLE} (id, downloaded, download_count)
        VALUES (?, 1, 1)
        ON CONFLICT(id) DO UPDATE SET
            downloaded = 1,
            download_count = {WORK_STATE_TABLE}.download_count + 1
        """,
        (int(work_id),),
    )


def mark_downloaded(connection, work_id: int):
    record_download_event(connection, work_id)


def record_metadata_check(connection, work_id: int, checked_at: str | None = None):
    timestamp = checked_at or datetime.now().isoformat(timespec="seconds")
    _execute_with_db_retry(
        connection,
        f"""
        INSERT INTO {WORK_STATE_TABLE} (
            id,
            metadata_check_count,
            last_metadata_checked_at
        )
        VALUES (?, 1, ?)
        ON CONFLICT(id) DO UPDATE SET
            metadata_check_count = {WORK_STATE_TABLE}.metadata_check_count + 1,
            last_metadata_checked_at = excluded.last_metadata_checked_at
        """,
        (int(work_id), timestamp),
    )


def fetch_downloaded_ids(connection, work_ids):
    normalized_ids = [int(work_id) for work_id in work_ids]
    if not normalized_ids:
        return set()

    placeholders = ",".join("?" for _ in normalized_ids)
    rows = connection.execute(
        f"""
        SELECT id
        FROM {WORK_STATE_TABLE}
        WHERE downloaded = 1
          AND id IN ({placeholders})
        """,
        normalized_ids,
    ).fetchall()
    return {int(row["id"]) for row in rows}


def reset_all_file_statuses(connection):
    _execute_with_db_retry(
        connection,
        f"""
        UPDATE {WORK_STATE_TABLE}
        SET
            file_present = 0,
            current_file_name = NULL,
            file_count = 0
        """
    )


def update_file_status(
    connection,
    work_id: int,
    file_present: bool,
    current_file_name: str | None,
    file_count: int,
):
    _execute_with_db_retry(
        connection,
        f"""
        INSERT INTO {WORK_STATE_TABLE} (
            id,
            file_present,
            current_file_name,
            file_count
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            file_present = excluded.file_present,
            current_file_name = excluded.current_file_name,
            file_count = excluded.file_count
        """,
        (
            int(work_id),
            1 if file_present else 0,
            _clean_text(current_file_name),
            int(file_count),
        ),
    )
