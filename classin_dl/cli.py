import argparse
import os
import time

from . import __version__
from .downloader import download_media
from .hls import download_hls
from .media import concat, find_ffmpeg
from .resolver import resolve
from .session import Session
from .util import fail, human_size, info, ok, safe_name, warn

BANNER = """
==============================================================
  ClassIn 云端录课下载工具   v{version}
  只用来备份你自己有权限观看的课程，不要再往外传
=============================================================="""

DEBUG_DIR = "debug"


def build_parser():
    parser = argparse.ArgumentParser(
        prog="classin-dl",
        description="把 ClassIn 云端录课（课程回放）下载到本地",
    )
    parser.add_argument("urls", nargs="*", help="回放页面地址，也可以直接给 m3u8 / mp4 直链")
    parser.add_argument("-f", "--batch", metavar="FILE", help="从文本文件批量读取链接，一行一个，# 开头忽略")
    parser.add_argument("-o", "--out", default="downloads", help="保存目录，默认 ./downloads")
    parser.add_argument("-c", "--cookie", help="Cookie 字符串，从浏览器开发者工具里复制")
    parser.add_argument("--cookies", metavar="FILE", help="Netscape 格式的 cookies.txt")
    parser.add_argument("--from-browser", choices=["chrome", "edge", "firefox", "brave", "chromium", "opera"],
                        help="自动从浏览器读取 Cookie，需要 pip install browser-cookie3")
    parser.add_argument("-p", "--proxy", help="代理地址，例如 http://127.0.0.1:7890")
    parser.add_argument("-t", "--threads", type=int, default=8, help="并发线程数，默认 8")
    parser.add_argument("-q", "--quality", default="best",
                        help="清晰度选择：best / worst / 720 / 0、1、2 这样的序号")
    parser.add_argument("--media-url", action="append", default=[], metavar="URL",
                        help="跳过解析，直接下载这个地址，可以重复给多个")
    parser.add_argument("--title", help="配合 --media-url 使用，指定保存的文件名")
    parser.add_argument("--ffmpeg", help="ffmpeg 路径，默认自动在 PATH 里找")
    parser.add_argument("--keep-parts", action="store_true", help="保留分片和中间文件")
    parser.add_argument("--no-resume", action="store_true", help="不续传，已经下了一半也重来")
    parser.add_argument("--overwrite", action="store_true", help="同名文件存在时覆盖")
    parser.add_argument("--dry-run", action="store_true", help="只解析地址，不下载")
    parser.add_argument("--debug", action="store_true", help="把接口返回的原始数据存到 debug/ 目录")
    parser.add_argument("--ua", help="自定义 User-Agent")
    parser.add_argument("--timeout", type=int, default=30, help="请求超时秒数，默认 30")
    parser.add_argument("--retries", type=int, default=3, help="失败重试次数，默认 3")
    parser.add_argument("-v", "--version", action="version", version="classin-dl {}".format(__version__))
    return parser


def collect_urls(args):
    urls = list(args.urls)
    if args.batch:
        if not os.path.isfile(args.batch):
            raise SystemExit("批量文件不存在: {}".format(args.batch))
        with open(args.batch, "r", encoding="utf-8-sig") as handle:
            for line in handle:
                line = line.strip()
                if line and not line.startswith("#"):
                    urls.append(line)
    return urls


def save_dir(args, target):
    if args.media_url:
        os.makedirs(args.out, exist_ok=True)
        return args.out
    folder = os.path.join(args.out, safe_name(target.get("course") or "ClassIn"))
    os.makedirs(folder, exist_ok=True)
    return folder


def build_basename(args, target):
    if args.title:
        return safe_name(args.title)
    if target.get("title"):
        return safe_name(target["title"])
    return "classin_" + time.strftime("%Y%m%d_%H%M%S")


def grab_one(sess, media_url, out_path, args, ffmpeg):
    if os.path.exists(out_path) and not args.overwrite:
        ok("已经存在，跳过 {}".format(os.path.basename(out_path)))
        return out_path
    if media_url.split("?")[0].lower().endswith(".m3u8"):
        return download_hls(sess, media_url, out_path, threads=args.threads,
                            quality=args.quality, keep_parts=args.keep_parts, ffmpeg=ffmpeg)
    info("开始下载 {}".format(os.path.basename(out_path)))
    result = download_media(sess, media_url, out_path, threads=args.threads,
                            resume=not args.no_resume)
    ok("下载完成 {} ({})".format(os.path.basename(result), human_size(os.path.getsize(result))))
    return result


def merge_segments(parts, dest, args, ffmpeg):
    if len(parts) < 2:
        return parts[0] if parts else dest
    if os.path.exists(dest) and not args.overwrite:
        ok("已经存在，跳过合并 {}".format(os.path.basename(dest)))
        return dest
    if not ffmpeg:
        warn("没找到 ffmpeg，{} 个分段保留为独立文件，播放器里按顺序播放即可".format(len(parts)))
        return parts[0]
    info("合并 {} 个分段 ...".format(len(parts)))
    concat(ffmpeg, parts, dest, os.path.dirname(os.path.abspath(dest)))
    ok("合并完成 {} ({})".format(os.path.basename(dest), human_size(os.path.getsize(dest))))
    if not args.keep_parts:
        for part in parts:
            try:
                os.remove(part)
            except OSError:
                pass
    return dest


def handle(sess, url, args, ffmpeg):
    if args.media_url:
        target = {"title": args.title or "", "course": args.title or "", "media": list(args.media_url)}
    else:
        target = resolve(sess, url, debug_dir=DEBUG_DIR if args.debug else None)

    media = target["media"]
    if not media:
        raise RuntimeError("没有拿到可下载的地址")

    if args.dry_run:
        ok("解析到 {} 个地址".format(len(media)))
        for item in media:
            print("    " + item)
        return

    folder = save_dir(args, target)
    base = build_basename(args, target)
    finished = []

    for index, item in enumerate(media, 1):
        suffix = "_p{:02d}".format(index) if len(media) > 1 else ""
        out_path = os.path.join(folder, base + suffix + ".mp4")
        finished.append(grab_one(sess, item, out_path, args, ffmpeg))

    if len(finished) > 1:
        merge_segments(finished, os.path.join(folder, base + ".mp4"), args, ffmpeg)


def main(argv=None):
    args = build_parser().parse_args(argv)
    print(BANNER.format(version=__version__))

    try:
        urls = collect_urls(args)
    except SystemExit as exc:
        fail(str(exc))
        return 2

    if not urls and not args.media_url:
        fail("请给一个回放页面地址，具体用法看 -h")
        return 2
    if not urls:
        urls = [""]

    if args.threads < 1:
        args.threads = 1

    sess = Session(cookie=args.cookie, cookie_file=args.cookies, browser=args.from_browser,
                   proxy=args.proxy, user_agent=args.ua, timeout=args.timeout, retries=args.retries)

    if sess.cookies:
        info("已载入 {} 个 Cookie".format(len(sess.cookies)))
    else:
        info("没有提供 Cookie，如果回放需要登录会解析失败")

    ffmpeg = find_ffmpeg(args.ffmpeg)
    if ffmpeg:
        info("ffmpeg: {}".format(ffmpeg))
    else:
        warn("没有找到 ffmpeg，TS 分片会直接存成 .ts 文件，播放不受影响")

    failed = 0
    try:
        for index, url in enumerate(urls, 1):
            if url:
                print()
                info("[{}/{}] {}".format(index, len(urls), url))
            try:
                handle(sess, url, args, ffmpeg)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                failed += 1
                fail(str(exc))
    except KeyboardInterrupt:
        print()
        warn("手动中断，已下载的部分保留着，下次加同样的参数可以续传")
        sess.close()
        return 130
    finally:
        sess.close()

    print()
    if failed:
        warn("跑完了，有 {} 个任务失败".format(failed))
        return 1
    ok("全部完成，文件在 {}".format(os.path.abspath(args.out)))
    return 0
