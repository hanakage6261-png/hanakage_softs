from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MASTER_DIR = Path(__file__).resolve().parent
ROOT_DIR = MASTER_DIR.parent
DOCS_DIR = MASTER_DIR / "docs"

DIRECTORY_NAMES = {
    "downloader": "01_momonGA_downloader",
    "database": "02_momonGA_database",
    "metadata_searching": "03_momonGA_metadata_searching",
    "patch": "04_momonGA_patch",
    "utilize": "05_momonGA_utilize",
    "legacies": "06_momonGA_legacies",
}

DIRECTORIES = {
    key: ROOT_DIR / directory_name
    for key, directory_name in DIRECTORY_NAMES.items()
}

MODULE_PATHS = {
    "metadata_store": DIRECTORIES["database"] / "momonGA_metadata_store.py",
    "downloader_main": DIRECTORIES["downloader"] / "momonGA_downloader.py",
    "metadata_auto_searching": DIRECTORIES["metadata_searching"] / "site_metadata_searcher" / "momonGA_metadata_auto_searching.py",
    "file_status_checker": DIRECTORIES["metadata_searching"] / "file_status_checker" / "momonGA_file_status_checker.py",
    "metadata_manual_searching": DIRECTORIES["patch"] / "momonGA_metadata_manual_searching.py",
    "author_data_eliminater": DIRECTORIES["patch"] / "momonGA_authordata_eliminater.py",
    "metadata_researching_for_null_ids": DIRECTORIES["legacies"] / "momonGA_metadata_researching_for_null_IDs.py",
    "pdf_to_cbz_redownload_helper": DIRECTORIES["patch"] / "momonGA_pdf_to_cbz_redownload_helper.py",
    "metadata_mistake_repair": DIRECTORIES["legacies"] / "momonGA_basis" / "momonGA_searching_legacies" / "momonGA_researching_for_mistakes.py",
}

INTERNAL_MODULE_NAMES = {
    alias: f"_momonGA_{alias}"
    for alias in MODULE_PATHS
}


def get_directory(key: str) -> Path:
    return DIRECTORIES[key]


def get_master_dir() -> Path:
    return MASTER_DIR


def get_master_file(name: str) -> Path:
    return MASTER_DIR / name


def get_docs_dir() -> Path:
    return DOCS_DIR


def get_docs_file(name: str) -> Path:
    return DOCS_DIR / name


def get_module_path(alias: str) -> Path:
    return MODULE_PATHS[alias]


def load_module(alias: str):
    internal_name = INTERNAL_MODULE_NAMES[alias]
    cached_module = sys.modules.get(internal_name)
    if cached_module is not None:
        return cached_module

    module_path = get_module_path(alias)
    spec = importlib.util.spec_from_file_location(internal_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"モジュールを読み込めません: {alias} / {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[internal_name] = module
    spec.loader.exec_module(module)
    return module
