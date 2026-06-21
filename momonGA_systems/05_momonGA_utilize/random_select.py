import os
import sqlite3
import sys


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
GRANDPARENT_DIR = os.path.dirname(PARENT_DIR)
for candidate_dir in (PARENT_DIR, GRANDPARENT_DIR):
    if candidate_dir not in sys.path:
        sys.path.insert(0, candidate_dir)

from momonGA_registry import load_module

metadata_store = load_module("metadata_store")
get_database_path = metadata_store.get_database_path


DB_PATH = get_database_path()

connection = sqlite3.connect(DB_PATH)
cursor = connection.cursor()

cursor.execute(
    """
    SELECT *
    FROM works
    WHERE status = 'found'
    ORDER BY RANDOM()
    LIMIT 1
    """
)

row = cursor.fetchone()
print(row)

connection.close()
