#!/usr/bin/env python3
"""
Telegram Chat Backup Tool
Downloads chat history and media from a Telegram chat using the main Telegram API.
"""

import os
import sys
import asyncio
from datetime import datetime
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from telethon.errors.rpcerrorlist import TimeoutError as TelegramTimeoutError


def get_media_type(message):
    """
    Determine the type of media in a message.

    Returns: 'image', 'audio', 'video', 'other', or None
    """
    if not message.media:
        return None

    # Photo messages
    if isinstance(message.media, MessageMediaPhoto):
        return 'image'

    # Document messages (videos, audio, files, etc.)
    if isinstance(message.media, MessageMediaDocument):
        doc = message.media.document
        if hasattr(doc, 'mime_type') and doc.mime_type:
            mime = doc.mime_type.lower()
            if mime.startswith('image/'):
                return 'image'
            elif mime.startswith('audio/'):
                return 'audio'
            elif mime.startswith('video/'):
                return 'video'

        # Check attributes for media type
        for attr in doc.attributes:
            attr_type = type(attr).__name__
            if 'Audio' in attr_type or 'Voice' in attr_type:
                return 'audio'
            elif 'Video' in attr_type:
                return 'video'
            elif 'Photo' in attr_type:
                return 'image'

        return 'other'

    # Other media types
    return 'other'


def get_media_size(message):
    """
    Get the size of media in bytes.

    Returns: size in bytes or 0 if not available
    """
    if not message.media:
        return 0

    if isinstance(message.media, MessageMediaDocument):
        if hasattr(message.media.document, 'size'):
            return message.media.document.size

    if isinstance(message.media, MessageMediaPhoto):
        # For photos, get the largest size
        if hasattr(message.media.photo, 'sizes'):
            sizes = [s.size for s in message.media.photo.sizes if hasattr(s, 'size')]
            return max(sizes) if sizes else 0

    return 0


async def download_chat(api_id, api_hash, chat_username, output_dir='backup', download_media=False,
                       media_filter='all', media_max_size=None):
    """
    Download chat history and media from a Telegram chat.

    Args:
        api_id: Telegram API ID
        api_hash: Telegram API hash
        chat_username: Username of the chat to backup
        output_dir: Directory to save backup files
        download_media: Whether to download media files (default: False)
        media_filter: Type of media to download: 'image', 'audio', 'video', 'other', 'all' (default: 'all')
        media_max_size: Maximum media file size in bytes (default: None = unlimited)
    """
    # Create output directory structure
    os.makedirs(output_dir, exist_ok=True)
    media_dir = None
    if download_media:
        media_dir = os.path.join(output_dir, 'media')
        os.makedirs(media_dir, exist_ok=True)
        print(f"Media download enabled - Filter: {media_filter}", end='')
        if media_max_size:
            print(f", Max size: {media_max_size:,} bytes ({media_max_size / 1024 / 1024:.1f} MB)")
        else:
            print(", Max size: unlimited")

    # Initialize client with longer timeout for network operations
    # timeout is per read operation, not for entire file download
    client = TelegramClient(
        'session',
        api_id,
        api_hash,
        timeout=60,  # 60 seconds per network operation
        request_retries=5,  # Retry failed requests
        connection_retries=5  # Retry failed connections
    )

    try:
        await client.start()
        print(f"Connected to Telegram as {await client.get_me()}")

        # Get the chat entity
        try:
            chat = await client.get_entity(chat_username)
            print(f"Found chat: {chat_username}")
        except Exception as e:
            print(f"Error: Could not find chat '{chat_username}': {e}")
            return

        # Open output file for chat history
        chat_file = os.path.join(output_dir, f'{chat_username}_history.txt')

        with open(chat_file, 'w', encoding='utf-8') as f:
            message_count = 0
            media_count = 0
            media_skipped = 0
            media_filtered = 0
            media_failed = 0

            print(f"Starting to download messages from {chat_username}...")
            print("Press Ctrl+C to stop\n")

            # Iterate through all messages in the chat
            async for message in client.iter_messages(chat):
                message_count += 1

                # Get sender name
                if message.sender:
                    sender_name = getattr(message.sender, 'username', None) or \
                                  getattr(message.sender, 'first_name', 'Unknown')
                else:
                    sender_name = 'Unknown'

                # Format timestamp
                timestamp = message.date.strftime('%Y-%m-%d %H:%M:%S') if message.date else ''

                # Write message in IRC style
                if message.message:
                    f.write(f"[{timestamp}] <{sender_name}> {message.message}\n")

                # Handle media
                if message.media:
                    if download_media:
                        # Check if media matches filter criteria
                        media_type = get_media_type(message)
                        media_size = get_media_size(message)

                        # Apply filters
                        should_download = True
                        skip_reason = None

                        # Type filter
                        if media_filter != 'all' and media_type != media_filter:
                            should_download = False
                            skip_reason = f"filtered ({media_type})"

                        # Size filter
                        if should_download and media_max_size and media_size > media_max_size:
                            should_download = False
                            skip_reason = f"too large ({media_size:,} bytes)"

                        if not should_download:
                            media_filtered += 1
                            f.write(f"[{timestamp}] <{sender_name}> [MEDIA: {skip_reason}]\n")
                        else:
                            # Try to download media with retries
                            max_retries = 3
                            retry_count = 0
                            download_success = False

                            while retry_count < max_retries and not download_success:
                                try:
                                    # Create a unique filename based on message ID
                                    media_filename = f"msg_{message.id}"

                                    if isinstance(message.media, MessageMediaPhoto):
                                        media_filename += ".jpg"
                                    elif isinstance(message.media, MessageMediaDocument):
                                        # Try to get original filename
                                        for attr in message.media.document.attributes:
                                            if hasattr(attr, 'file_name'):
                                                _, ext = os.path.splitext(attr.file_name)
                                                media_filename = f"msg_{message.id}{ext}"
                                                break

                                    media_path = os.path.join(media_dir, media_filename)

                                    # Progress callback to show activity
                                    last_update = [0]  # Mutable to modify in callback
                                    def progress_callback(current, total):
                                        # Print a dot every 100KB to show activity
                                        if current - last_update[0] >= 100 * 1024:
                                            print('.', end='', flush=True)
                                            last_update[0] = current

                                    # Download the media with progress callback
                                    print(f"  Downloading {media_filename} ", end='', flush=True)

                                    # Let Telethon handle the download with its internal timeout
                                    # The timeout here is per-operation, not for the whole file
                                    await client.download_media(
                                        message,
                                        media_path,
                                        progress_callback=progress_callback
                                    )

                                    media_count += 1
                                    download_success = True
                                    print(" ✓")

                                    # Log media in chat history
                                    f.write(f"[{timestamp}] <{sender_name}> [MEDIA: {media_filename}]\n")

                                except Exception as e:
                                    retry_count += 1
                                    error_msg = str(e)
                                    if 'Timeout' in error_msg or 'timeout' in error_msg:
                                        print(f" timeout (retry {retry_count}/{max_retries})")
                                    else:
                                        print(f" error: {error_msg[:50]} (retry {retry_count}/{max_retries})")

                                    if retry_count >= max_retries:
                                        media_failed += 1
                                        f.write(f"[{timestamp}] <{sender_name}> [MEDIA: Download failed - {error_msg}]\n")
                                    else:
                                        await asyncio.sleep(3)  # Wait before retry
                    else:
                        # Just note that media exists without downloading
                        media_skipped += 1
                        f.write(f"[{timestamp}] <{sender_name}> [MEDIA: not downloaded]\n")

                # Progress indicator
                if message_count % 50 == 0:
                    status = f"Progress: {message_count} messages"
                    if download_media:
                        status += f", {media_count} downloaded"
                        if media_filtered > 0:
                            status += f", {media_filtered} filtered"
                        if media_failed > 0:
                            status += f", {media_failed} failed"
                    else:
                        status += f", {media_skipped} media skipped"
                    print(status)
                elif message_count % 10 == 0:
                    print(f"  {message_count} messages...", end='\r', flush=True)

        print(f"\n{'='*60}")
        print(f"Backup complete!")
        print(f"{'='*60}")
        print(f"Total messages: {message_count}")
        if download_media:
            print(f"Media downloaded: {media_count}")
            if media_filtered > 0:
                print(f"Media filtered: {media_filtered}")
            if media_failed > 0:
                print(f"Media failed: {media_failed}")
            print(f"Media saved to: {media_dir}")
        else:
            print(f"Media skipped: {media_skipped} (use --download-media to download)")
        print(f"Chat history saved to: {chat_file}")
        print(f"{'='*60}")

    finally:
        await client.disconnect()


def print_help():
    """Print help message"""
    print("Telegram Chat Backup Tool")
    print("=" * 60)
    print("\nUsage: python telegram_backup.py <api_id> <api_hash> <chat_username> [options]")
    print("\nRequired Arguments:")
    print("  api_id                        Your Telegram API ID")
    print("  api_hash                      Your Telegram API hash")
    print("  chat_username                 Username of the chat to backup")
    print("\nOptions:")
    print("  --help                        Show this help message")
    print("  --download-media              Download media files (photos, videos, etc.)")
    print("  --media-filter TYPE           Filter media type: image, audio, video, other, all")
    print("                                (default: all)")
    print("  --media-max-size BYTES        Maximum media file size in bytes")
    print("                                (default: unlimited)")
    print("  --output-dir DIR              Output directory (default: backup)")
    print("\nExamples:")
    print("  # Show help")
    print("  python telegram_backup.py --help")
    print("")
    print("  # Download chat history only (no media)")
    print("  python telegram_backup.py 12345 abcdef123456 username")
    print("")
    print("  # Download chat history with all media")
    print("  python telegram_backup.py 12345 abcdef123456 username --download-media")
    print("")
    print("  # Download only images")
    print("  python telegram_backup.py 12345 abcdef123456 username --download-media --media-filter image")
    print("")
    print("  # Download images under 5MB (5,242,880 bytes)")
    print("  python telegram_backup.py 12345 abcdef123456 username --download-media --media-filter image --media-max-size 5242880")
    print("")
    print("  # Download only audio files")
    print("  python telegram_backup.py 12345 abcdef123456 username --download-media --media-filter audio")


def main():
    """Main entry point"""
    # Check for help flag first
    if '--help' in sys.argv or '-h' in sys.argv:
        print_help()
        sys.exit(0)

    # Validate minimum arguments
    if len(sys.argv) < 4:
        print("Error: Missing required arguments")
        print("\nRun with --help for usage information:")
        print("  python telegram_backup.py --help")
        sys.exit(1)

    # Parse required arguments
    try:
        api_id = int(sys.argv[1])
    except ValueError:
        print(f"Error: Invalid api_id '{sys.argv[1]}'. Must be a number.")
        sys.exit(1)

    api_hash = sys.argv[2]
    chat_username = sys.argv[3]

    # Valid options
    valid_options = {
        '--download-media': 0,      # No argument
        '--media-filter': 1,         # Takes 1 argument
        '--media-max-size': 1,       # Takes 1 argument
        '--output-dir': 1,           # Takes 1 argument
    }

    # Parse optional arguments
    download_media = False
    output_dir = 'backup'
    media_filter = 'all'
    media_max_size = None

    # Validate all options
    i = 4  # Start after required arguments
    while i < len(sys.argv):
        arg = sys.argv[i]

        if not arg.startswith('--'):
            print(f"Error: Invalid argument '{arg}'. Arguments must start with --")
            print("Run with --help for usage information")
            sys.exit(1)

        if arg not in valid_options:
            print(f"Error: Unknown option '{arg}'")
            print("Run with --help for usage information")
            sys.exit(1)

        # Handle options
        if arg == '--download-media':
            download_media = True
            i += 1

        elif arg == '--output-dir':
            if i + 1 >= len(sys.argv):
                print(f"Error: {arg} requires a directory path")
                sys.exit(1)
            output_dir = sys.argv[i + 1]
            i += 2

        elif arg == '--media-filter':
            if i + 1 >= len(sys.argv):
                print(f"Error: {arg} requires a media type (image, audio, video, other, all)")
                sys.exit(1)
            media_filter = sys.argv[i + 1].lower()
            if media_filter not in ['image', 'audio', 'video', 'other', 'all']:
                print(f"Error: Invalid media filter '{media_filter}'")
                print("Valid options: image, audio, video, other, all")
                sys.exit(1)
            i += 2

        elif arg == '--media-max-size':
            if i + 1 >= len(sys.argv):
                print(f"Error: {arg} requires a size in bytes")
                sys.exit(1)
            try:
                media_max_size = int(sys.argv[i + 1])
                if media_max_size <= 0:
                    print("Error: Media max size must be greater than 0")
                    sys.exit(1)
            except ValueError:
                print(f"Error: Invalid media max size '{sys.argv[i + 1]}'. Must be a number in bytes.")
                sys.exit(1)
            i += 2

    # Run the async function
    asyncio.run(download_chat(api_id, api_hash, chat_username, output_dir, download_media,
                             media_filter, media_max_size))


if __name__ == '__main__':
    main()
