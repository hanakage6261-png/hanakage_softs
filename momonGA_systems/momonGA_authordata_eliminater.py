import re
from pathlib import Path


RENAME_DIR = Path.home() / "Downloads" / "momonGA_rename"
AUTHOR_PREFIX_PATTERN = re.compile(
    r"^(?P<id_prefix>\[mo\d+\]\s*)?\[[^\]]*\]\s*(?P<title>.+)$",
    re.IGNORECASE,
)


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(1, 10000):
        candidate = path.with_name(f"{path.stem} ({index}){path.suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"重複しないファイル名を作成できませんでした: {path.name}")


def remove_author_from_name(path: Path):
    match = AUTHOR_PREFIX_PATTERN.match(path.name)
    if not match:
        return None

    id_prefix = match.group("id_prefix") or ""
    title = match.group("title").strip()
    new_name = f"{id_prefix}[] {title}"

    if new_name == path.name:
        return path

    destination = unique_path(path.with_name(new_name))
    path.rename(destination)
    return destination


def main():
    RENAME_DIR.mkdir(parents=True, exist_ok=True)

    print("作者名除去対象のCBZファイルを次のフォルダへ入れてください。")
    print(RENAME_DIR)
    input("準備ができたらEnterを押してください。")

    cbz_files = sorted(RENAME_DIR.glob("*.cbz"))
    if not cbz_files:
        print("CBZファイルが見つかりませんでした。")
        return

    renamed = 0
    skipped = 0

    for cbz_path in cbz_files:
        destination = remove_author_from_name(cbz_path)
        if destination is None:
            print(f"対象形式ではないためスキップ: {cbz_path.name}")
            skipped += 1
            continue

        if destination == cbz_path:
            print(f"作者名は既に空欄です: {cbz_path.name}")
            skipped += 1
            continue

        print(f"変更: {cbz_path.name} -> {destination.name}")
        renamed += 1

    print(f"\n変更件数: {renamed}")
    print(f"スキップ件数: {skipped}")


if __name__ == "__main__":
    main()
