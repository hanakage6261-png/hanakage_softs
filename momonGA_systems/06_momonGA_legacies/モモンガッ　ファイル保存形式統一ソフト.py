import os
import shutil

DOWNLOAD_ROOT = "/sdcard/Download"

def main():
    for author in os.listdir(DOWNLOAD_ROOT):
        author_dir = os.path.join(DOWNLOAD_ROOT, author)

        if not os.path.isdir(author_dir):
            continue

        for filename in os.listdir(author_dir):
            if not filename.lower().endswith(".pdf"):
                continue

            src = os.path.join(author_dir, filename)
            new_name = f"[{author}] {filename}"
            dst = os.path.join(DOWNLOAD_ROOT, new_name)

            if os.path.exists(dst):
                print("重複のためスキップ:", new_name)
                continue

            shutil.move(src, dst)
            print("移動:", new_name)

        if not os.listdir(author_dir):
            os.rmdir(author_dir)
            print("フォルダ削除:", author)

    print("整理完了")

if __name__ == "__main__":
    main()