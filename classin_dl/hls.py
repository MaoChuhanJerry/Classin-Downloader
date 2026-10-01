import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin

from .media import find_ffmpeg, remux
from .progress import Progress
from .util import info, media_ext, warn

VARIANT_TAG = "#EXT-X-STREAM-INF:"
KEY_TAG = "#EXT-X-KEY:"
MAP_TAG = "#EXT-X-MAP:"
RANGE_TAG = "#EXT-X-BYTERANGE:"
SEQ_TAG = "#EXT-X-MEDIA-SEQUENCE:"


def split_attributes(text):
    chunks = []
    buffer = []
    quoted = False
    for char in text:
        if char == '"':
            quoted = not quoted
            buffer.append(char)
        elif char == "," and not quoted:
            chunks.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    chunks.append("".join(buffer))
    return chunks


def parse_attributes(text):
    attrs = {}
    for chunk in split_attributes(text):
        if "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        attrs[name.strip().upper()] = value.strip().strip('"')
    return attrs


def parse_playlist(text, base):
    variants = []
    segments = []
    current_key = None
    map_url = None
    pending_range = None
    sequence = 0
    endlist = False
    expect_variant = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(SEQ_TAG):
            value = line.split(":", 1)[1].strip()
            sequence = int(value) if value.isdigit() else 0
        elif line.startswith(KEY_TAG):
            attrs = parse_attributes(line.split(":", 1)[1])
            if attrs.get("METHOD", "NONE").upper() == "NONE" or not attrs.get("URI"):
                current_key = None
            else:
                current_key = {"uri": urljoin(base, attrs["URI"]), "iv": attrs.get("IV")}
        elif line.startswith(MAP_TAG):
            attrs = parse_attributes(line.split(":", 1)[1])
            if attrs.get("URI"):
                map_url = urljoin(base, attrs["URI"])
        elif line.startswith(RANGE_TAG):
            pending_range = line.split(":", 1)[1].strip()
        elif line.startswith(VARIANT_TAG):
            variants.append({"attrs": parse_attributes(line.split(":", 1)[1]), "url": None})
            expect_variant = True
        elif line.startswith("#EXT-X-ENDLIST"):
            endlist = True
        elif line.startswith("#"):
            continue
        else:
            target = urljoin(base, line)
            if expect_variant and variants:
                variants[-1]["url"] = target
                expect_variant = False
            else:
                segments.append({
                    "url": target,
                    "key": current_key,
                    "range": pending_range,
                    "sequence": sequence + len(segments),
                })
                pending_range = None

    return {
        "variants": [item for item in variants if item["url"]],
        "segments": segments,
        "map": map_url,
        "endlist": endlist,
        "is_master": bool(variants),
    }


def pick_variant(variants, quality):
    if not variants:
        return None

    def bandwidth(item):
        raw = item["attrs"].get("BANDWIDTH") or item["attrs"].get("AVERAGE-BANDWIDTH") or "0"
        try:
            return int(raw)
        except ValueError:
            return 0

    ordered = sorted(variants, key=bandwidth, reverse=True)
    text = str(quality or "best").strip().lower()
    if text in ("best", "", "max"):
        return ordered[0]
    if text in ("worst", "min"):
        return ordered[-1]
    height_match = re.match(r"^(\d{3,4})p?$", text)
    if height_match:
        want = int(height_match.group(1))
        best = None
        for item in ordered:
            resolution = item["attrs"].get("RESOLUTION", "")
            if "x" not in resolution:
                continue
            tail = resolution.rsplit("x", 1)[1]
            if not tail.isdigit():
                continue
            distance = abs(int(tail) - want)
            if best is None or distance < best[0]:
                best = (distance, item)
        if best is not None:
            return best[1]
    if text.isdigit():
        index = int(text)
        if 0 <= index < len(ordered):
            return ordered[index]
    return ordered[0]


def load_playlist(sess, url):
    response = sess.get(url)
    response.raise_for_status()
    text = response.text
    if "#EXTM3U" not in text:
        raise RuntimeError("返回的不是 m3u8 内容，地址可能已过期或需要登录")
    return parse_playlist(text, response.url)


def load_key(sess, uri, cache):
    if uri not in cache:
        response = sess.get(uri)
        response.raise_for_status()
        cache[uri] = response.content
    return cache[uri]


def strip_padding(data):
    if not data:
        return data
    pad = data[-1]
    if 1 <= pad <= 16 and len(data) >= pad and data[-pad:] == bytes([pad]) * pad:
        return data[:-pad]
    return data


def decrypt(data, key, iv):
    try:
        from Crypto.Cipher import AES
    except ImportError:
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
            return strip_padding(decryptor.update(data) + decryptor.finalize())
        except ImportError:
            raise RuntimeError("该视频使用 AES-128 加密，请先安装 pycryptodome: pip install pycryptodome")
    return strip_padding(AES.new(key, AES.MODE_CBC, iv).decrypt(data))


def make_iv(iv_text, sequence):
    if iv_text:
        raw = iv_text[2:] if iv_text.lower().startswith("0x") else iv_text
        try:
            value = bytes.fromhex(raw)
            if len(value) == 16:
                return value
        except ValueError:
            pass
    return int(sequence).to_bytes(16, "big")


def download_hls(sess, url, out_path, threads=8, quality="best", keep_parts=False, ffmpeg=None):
    info("解析 m3u8 ...")
    playlist = load_playlist(sess, url)
    if playlist["is_master"]:
        variant = pick_variant(playlist["variants"], quality)
        if variant is None:
            raise RuntimeError("主播放列表里没有可用的清晰度")
        label = variant["attrs"].get("RESOLUTION") or variant["attrs"].get("BANDWIDTH") or "default"
        info("选择清晰度 {}，共 {} 个可选".format(label, len(playlist["variants"])))
        playlist = load_playlist(sess, variant["url"])

    segments = playlist["segments"]
    if not segments:
        raise RuntimeError("m3u8 里没有分片，可能是空播放列表或地址已失效")
    if not playlist["endlist"]:
        warn("这个 m3u8 没有结束标记，可能还在直播，录制长度会不完整")

    work = out_path + ".parts"
    os.makedirs(work, exist_ok=True)
    key_cache = {}
    last_end = {}

    if playlist["map"]:
        info("下载初始化分片 ...")
        response = sess.get(playlist["map"])
        response.raise_for_status()
        init_path = os.path.join(work, "init" + (media_ext(playlist["map"]) or ".mp4"))
        with open(init_path, "wb") as handle:
            handle.write(response.content)
    else:
        init_path = None

    def fetch(item):
        index, segment = item
        extension = media_ext(segment["url"]) or ".ts"
        path = os.path.join(work, "seg{:05d}{}".format(index, extension))
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return path, index
        headers = {}
        raw_range = segment.get("range")
        if raw_range:
            if "@" in raw_range:
                length_text, offset_text = raw_range.split("@", 1)
                start = int(offset_text)
                length = int(length_text)
            else:
                length = int(raw_range)
                start = last_end.get(segment["url"], 0)
            last_end[segment["url"]] = start + length
            headers["Range"] = "bytes={}-{}".format(start, start + length - 1)
        response = sess.get(segment["url"], headers=headers)
        response.raise_for_status()
        data = response.content
        if segment["key"]:
            key_bytes = load_key(sess, segment["key"]["uri"], key_cache)
            iv = make_iv(segment["key"].get("iv"), segment["sequence"])
            data = decrypt(data, key_bytes, iv)
        with open(path, "wb") as handle:
            handle.write(data)
        return path, index

    bar = Progress(len(segments), os.path.basename(out_path)).start()
    results = []
    pool = ThreadPoolExecutor(max_workers=max(1, threads))
    futures = [pool.submit(fetch, item) for item in enumerate(segments)]
    try:
        for future in as_completed(futures):
            path, _ = future.result()
            results.append(path)
            bar.add(1)
    except Exception:
        for future in futures:
            future.cancel()
        bar.close()
        pool.shutdown(wait=False)
        raise
    pool.shutdown(wait=True)
    bar.close()

    results.sort()
    if init_path:
        results.insert(0, init_path)
    extension = os.path.splitext(results[-1])[1].lower()
    merged = os.path.join(work, "merged" + (extension or ".ts"))
    info("合并 {} 个分片 ...".format(len(results)))
    with open(merged, "wb") as out:
        for path in results:
            with open(path, "rb") as src:
                shutil.copyfileobj(src, out, 1024 * 1024)

    target = out_path
    if extension in (".ts", ".m4s", "") and out_path.lower().endswith(".mp4"):
        tool = find_ffmpeg(ffmpeg)
        if tool:
            info("转封装为 MP4 ...")
            remux(tool, merged, out_path)
        else:
            target = os.path.splitext(out_path)[0] + ".ts"
            warn("没有 ffmpeg，先保存为 TS 文件，播放器可以直接打开")
            shutil.move(merged, target)
    else:
        shutil.move(merged, target)

    if not keep_parts:
        shutil.rmtree(work, ignore_errors=True)
    return target
