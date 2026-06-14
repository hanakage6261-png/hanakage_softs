# Pornhub Downloader

This small CLI wraps `yt-dlp` so you can paste a video URL, inspect available streams, choose one, and download a single MP4 file.

Use it only for videos that you own or have permission to download, and make sure your use follows the site's rules.

## Setup

```powershell
python -m pip install -r requirements.txt
```

If you prefer a simple launcher, you can double-click `download_my_video.bat` and follow the prompts.

## Basic usage

Download one URL:

```powershell
python pornhub_downloader.py "https://www.pornhub.com/view_video.php?viewkey=XXXX"
```

By default it tries to:

- prefer MP4-compatible H.264 video and AAC audio, then choose the best quality within those candidates when available
- merge/remux the result into one `mp4` file
- name the file from the video title
- download the site thumbnail and embed it into the video file
- if two videos would end up with the same title-based filename, automatically add the video ID only for that collision case
- save downloaded media under `Downloads\pornhub` by default, not inside the program folder

Download only when the uploader metadata matches your account name:

```powershell
python pornhub_downloader.py "https://www.pornhub.com/view_video.php?viewkey=XXXX" --expected-owner "YourChannelName"
```

Read multiple URLs from a text file:

```powershell
python pornhub_downloader.py --url-file urls.txt --expected-owner "YourChannelName"
```

Example `urls.txt`:

```text
# one URL per line
https://www.pornhub.com/view_video.php?viewkey=AAAA
https://www.pornhub.com/view_video.php?viewkey=BBBB
```

List streams and exit:

```powershell
python pornhub_downloader.py "https://www.pornhub.com/view_video.php?viewkey=XXXX" --list-formats
```

Download a specific stream by `format_id`:

```powershell
python pornhub_downloader.py "https://www.pornhub.com/view_video.php?viewkey=XXXX" --format-id hls-2126
```

## Logged-in downloads

If some of your videos require a logged-in session, you can reuse browser cookies:

```powershell
python pornhub_downloader.py --url-file urls.txt --cookies-from-browser chrome --expected-owner "YourChannelName"
```

On Windows, cookie loading can fail if Chrome or Edge is still open. Close the browser and retry, or use `cookies.txt`.

You can also target a specific browser profile:

```powershell
python pornhub_downloader.py --url-file urls.txt --cookies-from-browser "edge:Default" --expected-owner "YourChannelName"
```

If you already exported cookies into Netscape format, use:

```powershell
python pornhub_downloader.py --url-file urls.txt --cookies cookies.txt --expected-owner "YourChannelName"
```

## Safe test mode

Check that URLs resolve and that the owner filter matches before downloading:

```powershell
python pornhub_downloader.py --url-file urls.txt --cookies-from-browser chrome --expected-owner "YourChannelName" --dry-run
```

## Notes

- Downloaded files are saved into `C:\Users\<you>\Downloads\pornhub` by default.
- Already-downloaded URLs are tracked in `.download-archive.txt` inside the output folder.
- The default format selector prefers MP4/H.264/AAC-friendly outputs first.
- The final container is `mp4`, which is a good fit for Windows 11 playback and file compatibility.
- HLS videos are downloaded from their `m3u8` playlist with yt-dlp's native HLS downloader, then finalized as one MP4 file.
- Fragment retries are higher than the defaults, and unavailable fragments are treated as errors instead of being skipped silently.
- If a download stops midway, running the same command again will try to resume it.
- If you want to keep the thumbnail image as a separate file after it is embedded, add:

```powershell
python pornhub_downloader.py "https://www.pornhub.com/view_video.php?viewkey=XXXX" --keep-thumbnail-file
```

- Site behavior, login requirements, or extractor support can change over time. If a URL stops working, updating `yt-dlp` is the first thing to try:

```powershell
python -m pip install -U yt-dlp
```
