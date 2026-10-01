import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from .progress import Progress
from .util import human_size

BLOCK = 262144
CHUNK_MIN = 4 * 1024 * 1024
CHUNK_MAX = 64 * 1024 * 1024


def _remove(paths):
    for path in paths:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def download_media(sess, url, dest, threads=8, resume=True):
    size, ranged = sess.probe(url)
    if size and ranged and threads > 1 and size >= CHUNK_MIN * 2:
        return _download_ranged(sess, url, dest, size, threads, resume)
    return _download_stream(sess, url, dest, size, resume)


def _download_stream(sess, url, dest, size, resume):
    part = dest + ".part"
    done = os.path.getsize(part) if resume and os.path.exists(part) else 0
    if size and done >= size:
        os.replace(part, dest)
        return dest
    headers = {"Range": "bytes={}-".format(done)} if done else {}
    response = sess.get(url, headers=headers, stream=True)
    if response.status_code not in (200, 206):
        raise RuntimeError("下载失败，HTTP {}".format(response.status_code))
    if done and response.status_code == 200:
        done = 0
    total = size
    if total is None:
        length = response.headers.get("Content-Length")
        total = (int(length) + done) if length and length.isdigit() else None
    bar = Progress(total, os.path.basename(dest)).start()
    if done:
        bar.add(done)
    mode = "ab" if done else "wb"
    with open(part, mode) as handle:
        for block in response.iter_content(BLOCK):
            if not block:
                continue
            handle.write(block)
            bar.add(len(block))
    bar.close()
    if total and os.path.getsize(part) != total:
        raise RuntimeError("文件不完整，已下载 {}，应为 {}".format(
            human_size(os.path.getsize(part)), human_size(total)))
    os.replace(part, dest)
    return dest


def _plan_ranges(size, threads, dest):
    chunk = max(CHUNK_MIN, min(CHUNK_MAX, -(-size // max(1, threads))))
    jobs = []
    offset = 0
    index = 0
    while offset < size:
        end = min(size - 1, offset + chunk - 1)
        jobs.append({
            "index": index,
            "start": offset,
            "end": end,
            "path": "{}.part{}".format(dest, index),
            "size": end - offset + 1,
            "have": 0,
        })
        offset = end + 1
        index += 1
    return jobs


def _download_ranged(sess, url, dest, size, threads, resume):
    jobs = _plan_ranges(size, threads, dest)
    for job in jobs:
        if resume and os.path.exists(job["path"]):
            have = os.path.getsize(job["path"])
            job["have"] = have if have <= job["size"] else 0
    pending = [job for job in jobs if job["have"] < job["size"]]
    bar = Progress(size, os.path.basename(dest)).start()
    bar.add(sum(job["have"] for job in jobs))

    def fetch(job):
        start = job["start"] + job["have"]
        headers = {"Range": "bytes={}-{}".format(start, job["end"])}
        response = sess.get(url, headers=headers, stream=True)
        if response.status_code not in (200, 206):
            raise RuntimeError("分片 {} 请求失败，HTTP {}".format(job["index"], response.status_code))
        written = job["have"]
        mode = "ab" if job["have"] else "wb"
        with open(job["path"], mode) as handle:
            for block in response.iter_content(BLOCK):
                if not block:
                    continue
                handle.write(block)
                written += len(block)
                bar.add(len(block))
        if written != job["size"]:
            raise RuntimeError("分片 {} 数据不完整 ({}/{})".format(job["index"], written, job["size"]))

    if pending:
        pool = ThreadPoolExecutor(max_workers=min(threads, len(pending)))
        futures = [pool.submit(fetch, job) for job in pending]
        error = None
        try:
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    error = exc
                    for other in futures:
                        other.cancel()
                    break
        finally:
            pool.shutdown(wait=True)
        bar.close()
        if error:
            raise error
    else:
        bar.close()

    with open(dest, "wb") as out:
        for job in jobs:
            with open(job["path"], "rb") as src:
                shutil.copyfileobj(src, out, 1024 * 1024)
    _remove([job["path"] for job in jobs])
    return dest
