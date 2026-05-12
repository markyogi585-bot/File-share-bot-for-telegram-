"""
Helper utilities — formatting, escaping, emoji mapping.
"""

import html
import math


def format_size(size_bytes: int) -> str:
    """Format bytes into human-readable size."""
    if size_bytes == 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(max(size_bytes, 1), 1024)))
    i = min(i, len(size_name) - 1)
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"


def escape_html(text: str) -> str:
    """Escape HTML special chars for Telegram HTML parse mode."""
    return html.escape(str(text))


def get_file_type_emoji(file_type: str) -> str:
    """Get emoji for file type."""
    mapping = {
        "document": "📄",
        "video": "🎬",
        "audio": "🎵",
        "photo": "🖼️",
        "sticker": "🎭",
        "voice": "🎤",
        "video_note": "📹",
        "animation": "🎞️",
    }
    return mapping.get(file_type, "📁")


def truncate(text: str, max_len: int = 50) -> str:
    """Truncate text with ellipsis."""
    return text[:max_len] + "..." if len(text) > max_len else text
