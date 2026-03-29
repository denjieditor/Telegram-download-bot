import os
import asyncio
import logging
import re
import tempfile
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import yt_dlp
import requests

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(os.environ.get("PORT", 8080))

YOUTUBE_PATTERN = re.compile(
    r"(https?://)?(www\.)?(youtube\.com|youtu\.be|music\.youtube\.com)/.+"
)
POCKETFM_PATTERN = re.compile(
    r"(https?://)?(www\.)?pocketfm\.(com|in)/.+"
)

executor = ThreadPoolExecutor(max_workers=4)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running!")

    def log_message(self, format, *args):
        pass


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info(f"Health server running on port {PORT}")
    server.serve_forever()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "⚡ Welcome to Download Bot! ⚡\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🚀 I can download anything for you — fast & easy!\n\n"
        "✅ What I support:\n"
        "  🎬 YouTube — Videos & Shorts\n"
        "  🎙️ Pocket FM — Episodes & Shows\n"
        "  🌐 Any Direct File Link\n\n"
        "📌 How to use:\n"
        "  Just paste a link and I'll do the rest!\n\n"
        "🎵 Want audio only? Use /audio <link>\n"
        "❓ Need help? Use /help\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Ready to download? Send me a link! 👇"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📖 Help & Guide\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔗 Just send a link and I'll detect it automatically!\n\n"
        "🎬 YouTube\n"
        "  → Send any YouTube link to get the video\n"
        "  → Use /audio <link> to get MP3 audio only\n\n"
        "🎙️ Pocket FM\n"
        "  → Send a Pocket FM link to get the audio\n\n"
        "🌐 Direct Links\n"
        "  → Send any file URL to download it directly\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📋 Commands:\n"
        "  /start — Welcome message\n"
        "  /help  — Show this guide\n"
        "  /audio <link> — Download as MP3\n\n"
        "⚠️ Note: Max file size is 50MB (Telegram limit)\n"
        "━━━━━━━━━━━━━━━━━━━━━"
    )


def is_youtube_link(url: str) -> bool:
    return bool(YOUTUBE_PATTERN.match(url))


def is_pocketfm_link(url: str) -> bool:
    return bool(POCKETFM_PATTERN.match(url))


def is_direct_link(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


MAX_TG_SIZE = 50 * 1024 * 1024
MAX_SUPPORTED_SIZE = 5 * 1024 * 1024 * 1024


def format_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{round(size_bytes / (1024**3), 2)} GB"
    elif size_bytes >= 1024 * 1024:
        return f"{round(size_bytes / (1024**2), 1)} MB"
    elif size_bytes >= 1024:
        return f"{round(size_bytes / 1024, 1)} KB"
    return f"{size_bytes} B"


def ytdlp_smart_download(url: str, audio_only: bool = False) -> dict:
    info_opts = {
        "format": "bestaudio/best" if audio_only else "best[height<=1080]/best",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(info_opts) as ydl:
        info = ydl.extract_info(url, download=False)

    title = info.get("title", "Downloaded file")
    direct_url = info.get("url", "")
    filesize = info.get("filesize") or info.get("filesize_approx") or 0
    ext = info.get("ext", "mp4")

    if filesize > MAX_SUPPORTED_SIZE:
        raise Exception(f"File is too large even for link sharing ({format_size(filesize)}). Max supported: 5GB.")

    if filesize > MAX_TG_SIZE or (filesize == 0 and not audio_only):
        return {
            "type": "link",
            "url": direct_url,
            "title": title,
            "size": filesize,
            "ext": ext,
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        dl_opts = {
            "format": "bestaudio/best" if audio_only else "best[filesize<50M]/best[height<=720]/best",
            "outtmpl": os.path.join(tmpdir, "%(title)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
        }
        if audio_only:
            dl_opts["postprocessors"] = [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }]

        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            ydl.extract_info(url, download=True)

        files = list(Path(tmpdir).iterdir())
        if not files:
            return {"type": "link", "url": direct_url, "title": title, "size": filesize, "ext": ext}

        file_path = str(files[0])
        file_ext = Path(file_path).suffix
        with open(file_path, "rb") as f:
            file_data = f.read()

        if len(file_data) > MAX_TG_SIZE:
            return {"type": "link", "url": direct_url, "title": title, "size": len(file_data), "ext": ext}

    return {
        "type": "file",
        "data": file_data,
        "title": title,
        "ext": file_ext,
    }


def direct_download(url: str) -> dict:
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    response = requests.get(url, headers=headers, stream=True, timeout=60)
    response.raise_for_status()

    content_disposition = response.headers.get("Content-Disposition", "")
    filename = (
        content_disposition.split("filename=")[-1].strip('"').strip()
        if "filename=" in content_disposition
        else url.split("/")[-1].split("?")[0] or "downloaded_file"
    )

    content_length = int(response.headers.get("Content-Length", 0))

    if content_length > MAX_SUPPORTED_SIZE:
        raise Exception(f"File is larger than 5GB ({format_size(content_length)}). Cannot process.")

    if content_length > MAX_TG_SIZE:
        return {"type": "link", "url": url, "filename": filename, "size": content_length}

    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if chunk:
            total += len(chunk)
            if total > MAX_TG_SIZE:
                return {"type": "link", "url": url, "filename": filename, "size": total}
            chunks.append(chunk)

    return {"type": "file", "data": b"".join(chunks), "filename": filename}


async def send_large_file_link(msg, title_or_name: str, size: int, link: str, is_video: bool = True):
    icon = "🎬" if is_video else "📁"
    size_text = format_size(size) if size else "Unknown"
    await msg.edit_text(
        f"📦 File is {size_text} — Too Large for Telegram!\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{icon} {title_or_name}\n\n"
        f"✅ Direct Download Link:\n"
        f"{link}\n\n"
        f"👆 Open this link in browser or IDM/ADM to download!\n"
        f"⚠️ Link may expire in a few hours."
    )


async def handle_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not is_direct_link(url):
        await update.message.reply_text(
            "⚠️ Invalid Link!\n"
            "Please send a valid link starting with http:// or https://"
        )
        return

    msg = await update.message.reply_text("🔍 Analyzing your link...")
    loop = asyncio.get_event_loop()

    try:
        if is_youtube_link(url) or is_pocketfm_link(url):
            audio_only = is_pocketfm_link(url)
            platform = "Pocket FM" if is_pocketfm_link(url) else "YouTube"
            icon = "🎙️" if is_pocketfm_link(url) else "🎬"
            await msg.edit_text(f"{icon} {platform} link detected!\n⏳ Processing... Please wait.")

            result = await loop.run_in_executor(executor, ytdlp_smart_download, url, audio_only)

            if result["type"] == "link":
                await send_large_file_link(msg, result["title"], result["size"], result["url"], not audio_only)
                return

            file_data = result["data"]
            title = result["title"]
            file_ext = result["ext"]

            await msg.edit_text("✅ Download complete!\n📤 Uploading to Telegram...")

            if audio_only or file_ext in [".mp3", ".m4a", ".aac", ".ogg"]:
                suffix = ".mp3" if audio_only else file_ext
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                    f.write(file_data)
                    tmp_path = f.name
                try:
                    with open(tmp_path, "rb") as f:
                        await update.message.reply_audio(audio=f, title=title, filename=f"{title}{suffix}")
                finally:
                    os.unlink(tmp_path)
            else:
                suffix = file_ext if file_ext else ".mp4"
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                    f.write(file_data)
                    tmp_path = f.name
                try:
                    with open(tmp_path, "rb") as f:
                        await update.message.reply_video(video=f, caption=f"🎬 {title}", supports_streaming=True)
                finally:
                    os.unlink(tmp_path)

        else:
            await msg.edit_text("🌐 Direct link detected!\n⏳ Downloading file... Please wait.")
            result = await loop.run_in_executor(executor, direct_download, url)

            if result["type"] == "link":
                await send_large_file_link(msg, result["filename"], result["size"], result["url"], False)
                return

            file_data = result["data"]
            filename = result["filename"]

            await msg.edit_text("✅ Download complete!\n📤 Uploading to Telegram...")
            suffix = "." + filename.split(".")[-1] if "." in filename else ""
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
                f.write(file_data)
                tmp_path = f.name
            try:
                with open(tmp_path, "rb") as f:
                    await update.message.reply_document(document=f, filename=filename)
            finally:
                os.unlink(tmp_path)

        await msg.delete()

    except Exception as e:
        logger.error(f"Error downloading {url}: {e}")
        err_msg = str(e)
        if "private" in err_msg.lower() or "login" in err_msg.lower():
            await msg.edit_text(
                "🔒 Private Content!\n"
                "━━━━━━━━━━━━━━━\n"
                "This content is private or requires a login.\n"
                "Cannot download private links."
            )
        elif "not available" in err_msg.lower() or "unavailable" in err_msg.lower():
            await msg.edit_text(
                "🚫 Content Unavailable!\n"
                "━━━━━━━━━━━━━━━\n"
                "This content is not available or has been deleted."
            )
        else:
            await msg.edit_text(
                f"❌ Download Failed!\n"
                f"━━━━━━━━━━━━━━━\n"
                f"Something went wrong. Please try again.\n\n"
                f"Error: {err_msg[:200]}"
            )


async def audio_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "🎵 Audio Download\n"
            "━━━━━━━━━━━━━━━\n"
            "Usage: /audio <link>\n\n"
            "Example:\n"
            "/audio https://youtube.com/watch?v=..."
        )
        return

    url = context.args[0]
    if not is_direct_link(url):
        await update.message.reply_text("⚠️ Please provide a valid link.")
        return

    msg = await update.message.reply_text(
        "🎵 Audio Download Started!\n"
        "⏳ Converting to MP3... Please wait."
    )

    loop = asyncio.get_event_loop()

    try:
        file_data, title, _ = await loop.run_in_executor(
            executor, ytdlp_download, url, True
        )

        await msg.edit_text(
            "✅ Conversion complete!\n"
            "📤 Uploading MP3..."
        )
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(file_data)
            tmp_path = f.name
        try:
            with open(tmp_path, "rb") as f:
                await update.message.reply_audio(
                    audio=f,
                    title=title,
                    filename=f"{title}.mp3"
                )
        finally:
            os.unlink(tmp_path)

        await msg.delete()

    except Exception as e:
        logger.error(f"Audio download error: {e}")
        await msg.edit_text(
            f"❌ Audio Download Failed!\n"
            f"━━━━━━━━━━━━━━━\n"
            f"Error: {str(e)[:200]}"
        )


def main():
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set!")

    health_thread = threading.Thread(target=run_health_server, daemon=True)
    health_thread.start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("audio", audio_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))

    logger.info("Bot is running! Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
