import json
import os
import re

from .util import info, is_media_url, iter_strings, to_seconds, warn

KEY_PATTERNS = (
    ("lessonKey", re.compile(r"lessonKey=([0-9a-zA-Z_\-]+)", re.I)),
    ("courseKey", re.compile(r"courseKey=([0-9a-zA-Z_\-]+)", re.I)),
    ("lessonid", re.compile(r"lessonid=([0-9a-zA-Z_\-]+)", re.I)),
    ("courseId", re.compile(r"courseId=(\d+)", re.I)),
    ("classId", re.compile(r"classId=(\d+)", re.I)),
)

AJAX_ENDPOINTS = (
    ("https://www.eeo.cn/saasajax/webcast.ajax.php", "getLessonLiveInfo"),
    ("https://www.eeo.cn/saasajax/webcast.ajax.php", "getLessonRecordInfo"),
    ("https://www.eeo.cn/saasajax/classin.ajax.php", "getLessonRecordInfo"),
    ("https://www.eeo.cn/saasajax/webcast.ajax.php", "getLessonInfo"),
)

TIME_KEYS = ("startTime", "start_time", "start", "beginTime", "beginTimeStr",
             "playTime", "offset", "index", "sort", "seq", "order")

TITLE_KEYS = ("lessonName", "className", "lessonTitle", "title", "name", "courseName", "subject")
COURSE_KEYS = ("courseName", "courseTitle", "schoolName", "orgName")

URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>\\\)\]]+")
PROTOCOL_RELATIVE = re.compile(r"[\"'](//[^\s\"'<>]+\.(?:m3u8|mp4|flv)[^\s\"'<>]*)[\"']", re.I)


def parse_target(url):
    keys = {}
    for name, pattern in KEY_PATTERNS:
        match = pattern.search(url)
        if match:
            keys.setdefault(name, match.group(1))
    return keys


def normalize_url(url):
    text = url.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    text = text.replace("&amp;", "&").strip().strip("\"'")
    return text


def _order_of(node, fallback):
    for key in TIME_KEYS:
        if key in node:
            value = to_seconds(node[key])
            if value is not None:
                return value
    return fallback


def extract_media(data):
    entries = []
    seen = set()

    def push(value, order):
        text = normalize_url(value)
        if not is_media_url(text) or text in seen:
            return
        seen.add(text)
        entries.append((order, text))

    def scan(node, inherited=None):
        if isinstance(node, dict):
            order = _order_of(node, inherited)
            for value in node.values():
                if isinstance(value, str):
                    push(value, order)
                    if value.strip().startswith("{"):
                        try:
                            inner = json.loads(normalize_url(value))
                        except ValueError:
                            inner = None
                        if inner is not None:
                            scan(inner, order)
                else:
                    scan(value, order)
        elif isinstance(node, list):
            for index, value in enumerate(node):
                if isinstance(value, str):
                    push(value, index)
                else:
                    scan(value, index)

    scan(data)
    timed = [item for item in entries if item[0] is not None]
    untimed = [item for item in entries if item[0] is None]
    if len(timed) > 1:
        timed.sort(key=lambda item: item[0])
        entries = timed + untimed
    return [item[1] for item in entries]


def pick_text(data, keys):
    for key in keys:
        for path, value in iter_strings(data):
            name = path.rsplit("/", 1)[-1].split("[", 1)[0]
            if name != key:
                continue
            text = value.strip()
            if text and not text.startswith("http") and len(text) < 200:
                return text
    return ""


def build_result(data, media):
    lesson = pick_text(data, TITLE_KEYS)
    course = pick_text(data, COURSE_KEYS)
    title = lesson
    if course and lesson and course != lesson:
        title = "{} - {}".format(course, lesson)
    elif not title:
        title = course
    return {"title": title, "course": course or lesson, "media": media}


def dump_debug(folder, name, payload):
    try:
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "{}.json".format(name))
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except (OSError, TypeError, ValueError):
        pass


def scan_page(sess, url, debug_dir=None):
    found = []
    seen = set()

    def push(candidate):
        text = normalize_url(candidate)
        if is_media_url(text) and text not in seen:
            seen.add(text)
            found.append(text)

    try:
        response = sess.get(url)
    except Exception as exc:
        warn("打开回放页面失败: {}".format(exc))
        return found

    text = response.text
    if debug_dir:
        try:
            os.makedirs(debug_dir, exist_ok=True)
            with open(os.path.join(debug_dir, "live_page.html"), "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError:
            pass

    if "login" in response.url.lower() and len(text) < 4000:
        warn("页面似乎跳转到了登录页，Cookie 可能已失效")

    for match in URL_IN_TEXT.finditer(text):
        push(match.group(0))
    for match in PROTOCOL_RELATIVE.finditer(text):
        push("https:" + match.group(1))
    return found


def resolve(sess, url, debug_dir=None):
    if is_media_url(url):
        return {"title": "", "course": "", "media": [url]}

    keys = parse_target(url)
    if not keys:
        raise RuntimeError(
            "没能从这个链接里解析出 lessonKey / courseKey\n"
            "确认一下是不是 ClassIn 的回放页面地址，或者直接用 --media-url 传直链"
        )
    info("解析到的参数: " + ", ".join("{}={}".format(k, v) for k, v in keys.items()))

    healthy = False
    for base, action in AJAX_ENDPOINTS:
        endpoint = "{}?action={}".format(base, action)
        try:
            response = sess.post(endpoint, data=dict(keys))
        except Exception:
            continue
        if response.status_code >= 400:
            continue
        try:
            payload = response.json()
        except ValueError:
            continue
        healthy = True
        if debug_dir:
            dump_debug(debug_dir, action, payload)
        media = extract_media(payload)
        if media:
            info("{} 返回了 {} 个媒体地址".format(action, len(media)))
            return build_result(payload, media)

    if healthy:
        warn("接口有响应但没有视频地址，改从页面里找 ...")
    media = scan_page(sess, url, debug_dir)
    if media:
        info("在页面里找到 {} 个媒体地址".format(len(media)))
        return {"title": "", "course": "", "media": media}

    raise RuntimeError(
        "没有找到视频地址，可能的原因：\n"
        "  1. 没有带 Cookie，或者 Cookie 已经过期\n"
        "  2. 这个课节没有开录课，或者录课还在生成中（一般课后 10-30 分钟）\n"
        "  3. ClassIn 调整了接口\n"
        "可以先在浏览器里打开回放页，F12 抓一下 m3u8/mp4 地址，再用 --media-url 直接下载"
    )
