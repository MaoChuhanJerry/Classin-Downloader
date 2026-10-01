import os
import re
import sys
import time

MEDIA_EXTS = (".m3u8", ".mp4", ".flv", ".ts", ".m4s", ".mkv", ".mov", ".m4a", ".mp3", ".aac")

_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_MULTI_SPACE = re.compile(r"\s+")
_TAIL_DOTS = re.compile(r"[. ]+$")


def _enable_ansi():
    if not sys.stdout.isatty():
        return False
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


ANSI_ON = _enable_ansi()

_COLORS = {"red": 31, "green": 32, "yellow": 33, "blue": 34, "cyan": 36, "gray": 90}


def paint(text, color):
    if not ANSI_ON:
        return text
    return "\033[{}m{}\033[0m".format(_COLORS.get(color, 37), text)


def info(msg):
    print("{} {}".format(paint("[*]", "cyan"), msg))


def ok(msg):
    print("{} {}".format(paint("[OK]", "green"), msg))


def warn(msg):
    print("{} {}".format(paint("[!!]", "yellow"), msg))


def fail(msg):
    print("{} {}".format(paint("[XX]", "red"), msg), file=sys.stderr)


def human_size(num):
    if num is None:
        return "?"
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return "{}B".format(int(value))
            return "{:.2f}{}".format(value, unit)
        value /= 1024
    return "{:.2f}TB".format(value)


def human_time(seconds):
    if seconds is None:
        return "--:--"
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "--:--"
    if seconds != seconds or seconds < 0 or seconds > 86400 * 30:
        return "--:--"
    seconds = int(seconds)
    hour, rest = divmod(seconds, 3600)
    minute, second = divmod(rest, 60)
    if hour:
        return "{}:{:02d}:{:02d}".format(hour, minute, second)
    return "{:02d}:{:02d}".format(minute, second)


def safe_name(name, limit=110):
    text = _BAD_CHARS.sub("_", str(name or "")).strip()
    text = _MULTI_SPACE.sub(" ", text)
    text = _TAIL_DOTS.sub("", text)
    if not text:
        text = "untitled"
    if len(text) > limit:
        text = text[:limit].rstrip() + "_"
    return text


def media_ext(url):
    path = str(url).split("#", 1)[0].split("?", 1)[0].lower()
    for ext in MEDIA_EXTS:
        if path.endswith(ext):
            return ext
    return ""


def is_media_url(url):
    if not isinstance(url, str) or len(url) < 12:
        return False
    low = url.lower()
    if not (low.startswith("http://") or low.startswith("https://")):
        return False
    return bool(media_ext(url))


def iter_strings(obj, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = "{}/{}".format(path, key) if path else str(key)
            for item in iter_strings(value, child):
                yield item
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            for item in iter_strings(value, "{}[{}]".format(path, index)):
                yield item
    elif isinstance(obj, str):
        yield path, obj


def to_seconds(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number < 0:
            return None
        if number > 1e12:
            return number / 1000.0
        if number > 1e8:
            return number
        return number
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.isdigit():
        return to_seconds(int(text))
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%H:%M:%S"):
        try:
            parsed = time.strptime(text, fmt)
        except ValueError:
            continue
        if fmt.startswith("%Y"):
            return time.mktime(parsed)
        return parsed.tm_hour * 3600 + parsed.tm_min * 60 + parsed.tm_sec
    return None
