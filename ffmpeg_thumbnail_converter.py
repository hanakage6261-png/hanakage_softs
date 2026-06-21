import subprocess
import os
import shutil
from datetime import datetime

TRASH_DIR = "trash"


# -----------------------------
# パス正規化
# -----------------------------
def normalize_path(p):
    return os.path.abspath(p.strip().strip('"'))


# -----------------------------
# 安全な出力名生成
# -----------------------------
def make_safe_output_name(output_path):
    output_path = normalize_path(output_path)

    base, ext = os.path.splitext(output_path)

    if ext == "":
        ext = ".mp4"

    candidate = base + ext

    # 同名 or 既存ファイル対策
    if os.path.exists(candidate):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        candidate = f"{base}_{timestamp}{ext}"

    return candidate


# -----------------------------
# ffmpeg実行
# -----------------------------
def run_ffmpeg(video_path, image_path, output_path):
    cmd = [
        "ffmpeg",
        "-y",

        "-i", video_path,
        "-i", image_path,

        "-map", "0",
        "-map", "1",

        "-c:v", "copy",
        "-c:a", "copy",

        "-c:v:1", "mjpeg",
        "-disposition:v:1", "attached_pic",

        output_path
    ]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )

    if result.returncode != 0:
        print("=== ffmpeg error ===")
        print(result.stderr)
        return False

    return True


# -----------------------------
# 出力チェック
# -----------------------------
def is_valid_output(path):
    return os.path.exists(path) and os.path.getsize(path) > 0


# -----------------------------
# 安全退避
# -----------------------------
def move_to_trash(path):
    if not os.path.exists(path):
        return

    try:
        os.makedirs(TRASH_DIR, exist_ok=True)

        base = os.path.basename(path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        new_path = os.path.join(TRASH_DIR, f"{timestamp}_{base}")

        shutil.move(path, new_path)
        print(f"退避: {path} -> {new_path}")

    except Exception as e:
        print(f"退避失敗: {path} ({e})")


# -----------------------------
# メイン処理
# -----------------------------
def main():
    print("=== サムネ埋め込みツール（完全安定版）===")

    video = normalize_path(input("動画ファイルパス: "))
    image = normalize_path(input("サムネ画像パス: "))
    output_input = input("生成動画ファイルパス: ")

    output = make_safe_output_name(output_input)

    print(f"\n出力ファイル: {output}")
    print("処理開始...\n")

    success = run_ffmpeg(video, image, output)

    if success and is_valid_output(output):
        print("成功: 生成完了")

        move_to_trash(video)
        move_to_trash(image)

        print("元ファイルは trash に移動しました")

    else:
        print("失敗: ファイルは削除しません")


if __name__ == "__main__":
    main()