# Telegram Chat Backup Tool

A Python tool to backup Telegram chat history and media using the Telegram API. Messages are saved in IRC-style text format.

> **Note:** This tool was created by an LLM (Claude) based on user specifications written by Salvatore Sanfilippo.

## Features

- Downloads chat history in IRC-style format: `[timestamp] <username> message`
- Optional media download with filtering by type and size
- Progress reporting with retry handling
- Read-only operation (safe, won't modify your chats)
- Minimal dependencies (only Telethon)

## Installation

```bash
pip install -r requirements.txt
```

Requires Python 3.7 or later.

## Getting Telegram API Credentials

Before using this tool, you need to obtain API credentials from Telegram:

1. Go to https://my.telegram.org/auth
2. Log in with your phone number
3. Click on "API development tools"
4. Fill in the application details (name and platform)
5. Copy your `api_id` (numeric) and `api_hash` (hexadecimal string)

These credentials are tied to your Telegram account and should be kept private.

## Usage

View all options:
```bash
python telegram_backup.py --help
```

Basic usage:
```bash
python telegram_backup.py <api_id> <api_hash> <chat_username>
```

### Examples

Download chat history only (no media):
```bash
python telegram_backup.py 12345678 abcdef1234567890 mychat
```

Download chat with all media:
```bash
python telegram_backup.py 12345678 abcdef1234567890 mychat --download-media
```

Download only images:
```bash
python telegram_backup.py 12345678 abcdef1234567890 mychat --download-media --media-filter image
```

Download images under 5MB:
```bash
python telegram_backup.py 12345678 abcdef1234567890 mychat --download-media --media-filter image --media-max-size 5242880
```

## Options

- `--download-media` - Download media files (disabled by default)
- `--media-filter TYPE` - Filter by type: `image`, `audio`, `video`, `other`, `all` (default: `all`)
- `--media-max-size BYTES` - Maximum file size in bytes (default: unlimited)
- `--output-dir DIR` - Output directory (default: `backup`)

## Authentication

On first run, Telegram will send a verification code to your account. Enter it when prompted. A session file will be created for future runs.

## Output

The tool creates:

1. **Chat history**: `<chat_username>_history.txt`
   ```
   [2025-01-01 12:34:56] <Alice> Hello!
   [2025-01-01 12:35:10] <Bob> Hi there!
   [2025-01-01 12:35:30] <Alice> [MEDIA: msg_12345.jpg]
   ```

2. **Media folder**: `media/` (if `--download-media` is used)
   - Files are named `msg_<id>.<ext>`
   - Filtered files are noted in the chat log

## Notes

- Large media downloads show progress dots (one per 100KB)
- Timeouts are handled with automatic retries (3 attempts)
- Media download is optional to avoid long wait times
- All text is saved in UTF-8 encoding
