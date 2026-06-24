from __future__ import annotations

import ctypes
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


WORK_ROOT_NAME = "ffmpeg_converter"
FINAL_DIR_NAME = "final_movie"
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


class ConversionError(Exception):
    pass


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("wFunc", ctypes.c_uint),
        ("pFrom", ctypes.c_wchar_p),
        ("pTo", ctypes.c_wchar_p),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", ctypes.c_bool),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", ctypes.c_wchar_p),
    ]


FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


def strip_quotes(text: str) -> str:
    return text.strip().strip('"').strip("'")


def bundle_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resolve_ffmpeg_path() -> Path:
    candidates = [
        bundle_dir() / "ffmpeg.exe",
        app_dir() / "ffmpeg.exe",
    ]

    which_result = shutil.which("ffmpeg")
    if which_result:
        candidates.append(Path(which_result))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        "ffmpeg.exe が見つかりません。プログラムと同じ場所に配置するか、"
        "exe 化時に同梱してください。"
    )


def get_downloads_dir() -> Path:
    override = strip_quotes(os.environ.get("FFMPEG_THUMBNAIL_DOWNLOADS_DIR", ""))
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / "Downloads").resolve()


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def prompt_existing_file(label: str) -> Path:
    while True:
        raw_value = input(f"{label} の絶対パス: ")
        cleaned = strip_quotes(raw_value)

        if not cleaned:
            print("入力が空です。絶対パスを入力してください。")
            continue

        candidate = Path(cleaned).expanduser()
        if not candidate.is_absolute():
            print("絶対パスで入力してください。")
            continue

        if not candidate.exists():
            print("そのパスのファイルは存在しません。")
            continue

        if not candidate.is_file():
            print("ファイルを指定してください。")
            continue

        return candidate.resolve()


def sanitize_output_name(name: str, default_stem: str) -> str:
    cleaned = strip_quotes(name)
    if not cleaned:
        cleaned = default_stem

    filename_only = Path(cleaned).name
    stem = Path(filename_only).stem or default_stem
    suffix = Path(filename_only).suffix or ".mp4"

    safe_stem = INVALID_FILENAME_CHARS.sub("_", stem).strip(" .")
    if not safe_stem:
        safe_stem = default_stem

    safe_suffix = INVALID_FILENAME_CHARS.sub("", suffix) or ".mp4"
    if not safe_suffix.startswith("."):
        safe_suffix = f".{safe_suffix}"

    return f"{safe_stem}{safe_suffix}"


def make_unique_path(directory: Path, filename: str) -> Path:
    directory = ensure_directory(directory)
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 2

    while True:
        numbered = directory / f"{stem}_{counter}{suffix}"
        if not numbered.exists():
            return numbered
        counter += 1


def move_to_directory(source: Path, target_dir: Path) -> Path:
    ensure_directory(target_dir)
    destination = make_unique_path(target_dir, source.name)
    shutil.move(str(source), str(destination))
    return destination


def move_inputs_to_work_dir(video_src: Path, image_src: Path, work_dir: Path) -> tuple[Path, Path]:
    moved_video: Path | None = None
    moved_image: Path | None = None

    try:
        moved_video = move_to_directory(video_src, work_dir)
        moved_image = move_to_directory(image_src, work_dir)
        return moved_video, moved_image
    except Exception as exc:
        if moved_video and moved_video.exists():
            fallback_video = video_src.parent / moved_video.name
            if not fallback_video.exists():
                shutil.move(str(moved_video), str(fallback_video))
        if moved_image and moved_image.exists():
            fallback_image = image_src.parent / moved_image.name
            if not fallback_image.exists():
                shutil.move(str(moved_image), str(fallback_image))
        raise ConversionError(f"作業フォルダへの移動に失敗しました: {exc}") from exc


def build_ffmpeg_command(ffmpeg_path: Path, video_path: Path, image_path: Path, output_path: Path) -> list[str]:
    return [
        str(ffmpeg_path),
        "-hide_banner",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(image_path),
        "-map",
        "0",
        "-map",
        "1",
        "-c",
        "copy",
        "-c:v:1",
        "mjpeg",
        "-disposition:v:1",
        "attached_pic",
        str(output_path),
    ]


def run_ffmpeg(ffmpeg_path: Path, video_path: Path, image_path: Path, output_path: Path) -> None:
    temp_output = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
    if temp_output.exists():
        temp_output.unlink()

    command = build_ffmpeg_command(ffmpeg_path, video_path, image_path, temp_output)
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        temp_output.unlink(missing_ok=True)
        details = result.stderr.strip() or result.stdout.strip() or "詳細不明"
        raise ConversionError(f"ffmpeg の実行に失敗しました。\n{details}")

    if not temp_output.exists() or temp_output.stat().st_size == 0:
        temp_output.unlink(missing_ok=True)
        raise ConversionError("ffmpeg は終了しましたが、出力ファイルが正しく作成されませんでした。")

    if output_path.exists():
        output_path.unlink()

    shutil.move(str(temp_output), str(output_path))


def send_to_recycle_bin(path: Path) -> bool:
    if os.name != "nt":
        return False

    if not path.exists():
        return True

    operation = SHFILEOPSTRUCTW()
    operation.wFunc = FO_DELETE
    operation.pFrom = str(path) + "\0\0"
    operation.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI

    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    return result == 0 and not operation.fAnyOperationsAborted


def print_summary(work_dir: Path, final_output: Path) -> None:
    print("\n処理が完了しました。")
    print(f"作業フォルダ: {work_dir}")
    print(f"完成ファイル: {final_output}")


def main() -> int:
    print("=== mp4 サムネイル埋め込みツール ===")

    try:
        ffmpeg_path = resolve_ffmpeg_path()
    except FileNotFoundError as exc:
        print(exc)
        return 1

    downloads_dir = get_downloads_dir()
    work_dir = ensure_directory(downloads_dir / WORK_ROOT_NAME)
    final_dir = ensure_directory(work_dir / FINAL_DIR_NAME)

    print(f"ffmpeg: {ffmpeg_path}")
    print(f"作業フォルダ: {work_dir}")

    video_source = prompt_existing_file("動画ファイル")
    image_source = prompt_existing_file("画像ファイル")

    if video_source == image_source:
        print("動画ファイルと画像ファイルに同じパスは指定できません。")
        return 1

    try:
        working_video, working_image = move_inputs_to_work_dir(video_source, image_source, work_dir)
    except ConversionError as exc:
        print(exc)
        return 1

    default_name = working_video.stem
    requested_name = input("完成後の動画ファイル名: ")
    output_name = sanitize_output_name(requested_name, default_name)
    final_output = make_unique_path(final_dir, output_name)

    print(f"\n出力予定ファイル: {final_output}")
    print("ffmpeg でサムネイルを埋め込みます...\n")

    try:
        run_ffmpeg(ffmpeg_path, working_video, working_image, final_output)
    except ConversionError as exc:
        print(exc)
        print("元ファイルは作業フォルダに残しています。")
        return 1

    recycle_video = send_to_recycle_bin(working_video)
    recycle_image = send_to_recycle_bin(working_image)

    print_summary(work_dir, final_output)

    if recycle_video and recycle_image:
        print("元の動画ファイルと画像ファイルはごみ箱に移動しました。")
    else:
        print("元ファイルのごみ箱移動に失敗したため、作業フォルダを確認してください。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
