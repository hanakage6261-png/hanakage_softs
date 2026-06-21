from __future__ import annotations

import importlib.util
from pathlib import Path


MASTER_REGISTRY_PATH = (
    Path(__file__).resolve().parent
    / "00_momonGA_master"
    / "momonGA_registry.py"
)

if not MASTER_REGISTRY_PATH.exists():
    raise RuntimeError(
        f"00_momonGA_master 内の momonGA_registry.py が見つかりません: {MASTER_REGISTRY_PATH}"
    )

spec = importlib.util.spec_from_file_location(
    "_momonGA_master_registry",
    MASTER_REGISTRY_PATH,
)
if spec is None or spec.loader is None:
    raise ImportError(f"レジストリを読み込めません: {MASTER_REGISTRY_PATH}")

module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

ROOT_DIR = module.ROOT_DIR
MASTER_DIR = module.MASTER_DIR
DIRECTORY_NAMES = module.DIRECTORY_NAMES
DIRECTORIES = module.DIRECTORIES
MODULE_PATHS = module.MODULE_PATHS
INTERNAL_MODULE_NAMES = module.INTERNAL_MODULE_NAMES
get_directory = module.get_directory
get_master_dir = module.get_master_dir
get_master_file = module.get_master_file
get_module_path = module.get_module_path
load_module = module.load_module
