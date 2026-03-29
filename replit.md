# Telegram Download Bot

## Project Overview
Ek Telegram bot jo YouTube, Pocket FM, aur general HTTP/HTTPS links se files download karke Telegram pe bhejta hai.

## Architecture
- **Language**: Python 3.11
- **Main file**: `bot.py`
- **Framework**: python-telegram-bot v22

## Features
- YouTube video download (best quality, max 50MB)
- YouTube audio download (`/audio` command ya auto)
- Pocket FM episode download (auto audio mode)
- General direct HTTP/HTTPS file download
- 50MB Telegram limit check

## Commands
- `/start` - Welcome message
- `/help` - Instructions
- `/audio <link>` - YouTube se sirf MP3 download

## Environment Variables / Secrets
- `TELEGRAM_BOT_TOKEN` - BotFather se mila token (required)

## Dependencies
- `python-telegram-bot` - Telegram bot framework
- `yt-dlp` - YouTube aur other platforms se download
- `requests` - Direct HTTP downloads
- `ffmpeg` (system) - Audio/video conversion

## Workflow
- Name: "Start application"
- Command: `python bot.py`
- Type: console
