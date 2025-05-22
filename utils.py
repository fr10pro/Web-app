# utils.py

import os
import aiohttp
import yt_dlp
import mimetypes
from moviepy.editor import VideoFileClip
from PIL import Image

async def download_from_url(url, message):
    filename = "downloaded_file"
    temp_dir = "downloads"
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, filename)

    # Choose yt-dlp for media
    if any(x in url for x in ["youtube.com", "youtu.be", "instagram.com", "facebook.com", "tiktok.com", "twitter.com"]):
        ydl_opts = {
            'outtmpl': f'{temp_dir}/%(title)s.%(ext)s',
            'format': 'best',
            'quiet': True,
            'noplaylist': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
            filename = os.path.basename(file_path)
    else:
        # Direct file download
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                content_type = resp.headers.get("Content-Type", "")
                ext = mimetypes.guess_extension(content_type.split(";")[0]) or ".bin"
                filename = "file" + ext
                file_path = os.path.join(temp_dir, filename)
                with open(file_path, "wb") as f:
                    f.write(await resp.read())

    file_size = os.path.getsize(file_path)
    return file_path, filename, file_size

def get_thumbnail(file_path):
    thumb_path = file_path + ".jpg"
    try:
        clip = VideoFileClip(file_path)
        frame = clip.get_frame(1)
        image = Image.fromarray(frame)
        image.save(thumb_path)
        return thumb_path
    except Exception:
        return None

def format_bytes(size):
    power = 2**10
    n = 0
    power_labels = ['B', 'KB', 'MB', 'GB', 'TB']
    while size > power and n < len(power_labels) - 1:
        size /= power
        n += 1
    return f"{size:.2f}{power_labels[n]}"