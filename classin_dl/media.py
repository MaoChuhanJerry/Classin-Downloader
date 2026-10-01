import os
import shutil
import subprocess

from .util import warn

COMMON_PATHS = (
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
    r"D:\ffmpeg\bin\ffmpeg.exe",
    r"/usr/local/bin/ffmpeg",
    r"/opt/homebrew/bin/ffmpeg",
)


def find_ffmpeg(explicit=None):
    if explicit:
        if os.path.isfile(explicit):
            return explicit
        found = shutil.which(explicit)
        if found:
            return found
        warn("指定的 ffmpeg 不可用: {}".format(explicit))
    found = shutil.which("ffmpeg")
    if found:
        return found
    for path in COMMON_PATHS:
        if os.path.isfile(path):
            return path
    return None


def run(tool, args):
    command = [tool, "-hide_banner", "-loglevel", "error", "-y"] + args
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if process.returncode != 0:
        message = process.stdout.decode("utf-8", "ignore").strip()
        raise RuntimeError("ffmpeg 出错: {}".format(message or process.returncode))


def remux(tool, src, dst):
    args = ["-i", src, "-c", "copy"]
    if dst.lower().endswith(".mp4"):
        args += ["-movflags", "+faststart"]
    args.append(dst)
    run(tool, args)


def concat(tool, parts, dst, workdir):
    listfile = os.path.join(workdir, "concat.txt")
    with open(listfile, "w", encoding="utf-8") as handle:
        for part in parts:
            escaped = os.path.abspath(part).replace("\\", "/").replace("'", "'\\''")
            handle.write("file '{}'\n".format(escaped))
    run(tool, ["-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", dst])
    return dst
