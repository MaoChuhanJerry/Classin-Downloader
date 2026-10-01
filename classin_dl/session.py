import os
import time

import requests
from requests.adapters import HTTPAdapter

from .util import warn

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

BROWSER_COOKIE_DOMAINS = ("eeo.cn", "classin.com", "classin-sdk.com", "classinpaas.com")

BROWSER_LOADERS = {
    "chrome": "chrome",
    "edge": "edge",
    "firefox": "firefox",
    "brave": "brave",
    "chromium": "chromium",
    "opera": "opera",
}


class RetryAdapter(HTTPAdapter):
    def __init__(self, retries=3, **kwargs):
        self.retries = max(0, int(retries))
        super().__init__(**kwargs)

    def send(self, request, **kwargs):
        attempt = 0
        while True:
            try:
                response = super().send(request, **kwargs)
            except requests.RequestException:
                if attempt >= self.retries:
                    raise
                time.sleep(min(2 ** attempt, 8))
                attempt += 1
                continue
            if response.status_code in (429, 500, 502, 503, 504) and attempt < self.retries:
                response.close()
                time.sleep(min(2 ** attempt, 8))
                attempt += 1
                continue
            return response


def parse_netscape(text):
    jar = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_"):]
        elif line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) >= 7:
            jar[fields[5]] = fields[6]
            continue
        if "\t" not in line and "=" in line:
            name, _, value = line.partition("=")
            if name.strip():
                jar[name.strip()] = value.strip()
    return jar


def parse_cookie_string(text):
    jar = {}
    text = text.strip()
    if text.lower().startswith("cookie:"):
        text = text[7:]
    for chunk in text.replace("\n", ";").split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        if name.strip():
            jar[name.strip()] = value.strip()
    return jar


class Session:
    def __init__(self, cookie=None, cookie_file=None, browser=None, proxy=None,
                 user_agent=None, timeout=30, retries=3):
        self.timeout = timeout
        self.cookies = {}
        self.http = requests.Session()
        self.http.headers.update({
            "User-Agent": user_agent or DEFAULT_UA,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        })
        adapter = RetryAdapter(retries=retries, pool_connections=32, pool_maxsize=32)
        self.http.mount("http://", adapter)
        self.http.mount("https://", adapter)
        if proxy:
            self.http.proxies = {"http": proxy, "https": proxy}
        if cookie_file:
            self.load_cookie_file(cookie_file)
        if cookie:
            self.load_cookie_string(cookie)
        if browser:
            self.load_from_browser(browser)
        if self.cookies:
            self.http.cookies.update(self.cookies)

    def load_cookie_file(self, path):
        if not os.path.isfile(path):
            warn("Cookie 文件不存在: {}".format(path))
            return
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            text = handle.read()
        jar = parse_netscape(text)
        if not jar:
            jar = parse_cookie_string(text)
        self.cookies.update(jar)

    def load_cookie_string(self, text):
        self.cookies.update(parse_cookie_string(text))

    def load_from_browser(self, name):
        try:
            import browser_cookie3
        except ImportError:
            warn("未安装 browser-cookie3，无法自动读取浏览器 Cookie")
            warn("需要的话执行: pip install browser-cookie3")
            return
        loader_name = BROWSER_LOADERS.get(str(name).lower())
        loader = getattr(browser_cookie3, loader_name, None) if loader_name else None
        if loader is None:
            warn("暂不支持从 {} 读取 Cookie".format(name))
            return
        found = {}
        for domain in BROWSER_COOKIE_DOMAINS:
            try:
                jar = loader(domain_name=domain)
            except Exception:
                continue
            for item in jar:
                found[item.name] = item.value
        if not found:
            warn("没有从 {} 读到相关站点的 Cookie，请确认浏览器里登录过 ClassIn".format(name))
            return
        self.cookies.update(found)

    def get(self, url, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        return self.http.get(url, **kwargs)

    def post(self, url, data=None, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        return self.http.post(url, data=data, **kwargs)

    def probe(self, url):
        size = None
        ranged = False
        try:
            response = self.http.head(url, timeout=self.timeout, allow_redirects=True)
            if response.status_code < 400:
                length = response.headers.get("Content-Length")
                if length and length.isdigit() and int(length) > 0:
                    size = int(length)
                ranged = response.headers.get("Accept-Ranges", "").lower() == "bytes"
        except requests.RequestException:
            pass
        if size is None or not ranged:
            try:
                response = self.http.get(url, headers={"Range": "bytes=0-0"},
                                         stream=True, timeout=self.timeout)
                if response.status_code == 206:
                    content_range = response.headers.get("Content-Range", "")
                    if "/" in content_range:
                        tail = content_range.rsplit("/", 1)[1].strip()
                        if tail.isdigit():
                            size = int(tail)
                            ranged = True
                response.close()
            except requests.RequestException:
                pass
        return size, ranged

    def close(self):
        try:
            self.http.close()
        except Exception:
            pass
