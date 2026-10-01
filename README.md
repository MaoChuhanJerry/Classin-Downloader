# classin-dl

把 ClassIn（eeo.cn）的云端录课 / 课程回放保存到本地。

平时上完课想留个备份，官方只给一个网页播放器，离线看不了，拖动还卡。这个脚本就是干这个的：
拿着你的登录状态去问 ClassIn 要真实播放地址，再把视频拉下来存成 mp4。

## 功能

- 支持 `live.php?lessonKey=xxx`、`webcast.php?courseKey=xxx` 这类回放页面地址，自动解析
- 也支持直接喂 m3u8 / mp4 直链
- HLS 分片多线程下载，支持 AES-128 加密流
- m3u8 主列表自动挑最高清晰度，也可以自己指定（`-q 720`）
- mp4 分块并发 + 断点续传，网络断了重跑就行
- 有 ffmpeg 就自动转封装 mp4，没有也能用，存成 ts 一样能播
- 一次给多个链接或整个文件批量下载
- 纯 requests 实现，不需要浏览器自动化

## 安装

需要 Python 3.8 以上。

```bash
git clone https://github.com/<your-name>/classin-dl.git
cd classin-dl
pip install -r requirements.txt
```

然后直接跑就行，不用安装：

```bash
python -m classin_dl -h
```

想装成命令的话：

```bash
pip install -e .
classin-dl -h
```

ffmpeg 是可选的，装在 PATH 里就行，或者用 `--ffmpeg` 指定路径。没有它也能下载，只是
HLS 的 ts 分片不会自动转成 mp4，多个分段也不会自动合并，会提示你手动处理。

## 使用

最简单的用法，把浏览器地址栏里的回放链接丢进去：

```bash
python -m classin_dl "https://www.eeo.cn/live.php?lessonKey=0a1b2c3d4e5f6a7b"
```

回放页一般要登录才能看，所以要带上 Cookie，否则解析不到地址：

```bash
python -m classin_dl "https://www.eeo.cn/live.php?lessonKey=xxx" -c "sessionid=abc; uid=123"
```

Cookie 太长的话存成文件更省事，Netscape 格式或者一行 `a=b; c=d` 都认：

```bash
python -m classin_dl "https://www.eeo.cn/live.php?lessonKey=xxx" --cookies cookies.txt
```

装了 `browser-cookie3` 的话可以直接从浏览器读，不用手动复制：

```bash
pip install browser-cookie3
python -m classin_dl "https://www.eeo.cn/live.php?lessonKey=xxx" --from-browser chrome
```

批量下载，`urls.txt` 一行一个链接，`#` 开头当注释：

```bash
python -m classin_dl -f urls.txt -o D:\课程备份
```

如果哪天的接口挂了，或者你不想折腾解析，直接用抓包拿到的地址下载也可以：

```bash
python -m classin_dl --media-url "https://playback.eeo.cn/xxx/xxx.m3u8" --title "高数第3讲"
```

## 参数

| 参数 | 说明 |
| --- | --- |
| `urls` | 回放页面地址或媒体直链，可以给多个 |
| `-f, --batch FILE` | 从文件批量读链接 |
| `-o, --out DIR` | 保存目录，默认 `./downloads` |
| `-c, --cookie STR` | Cookie 字符串 |
| `--cookies FILE` | Cookie 文件 |
| `--from-browser NAME` | 从 chrome / edge / firefox 等浏览器读 Cookie |
| `--media-url URL` | 跳过解析，直接下载该地址，可重复 |
| `--title NAME` | 配合 `--media-url` 指定文件名 |
| `-q, --quality` | `best`（默认）/ `worst` / `720` / `0` `1` `2` 序号 |
| `-t, --threads` | 并发线程数，默认 8 |
| `-p, --proxy` | 代理，例如 `http://127.0.0.1:7890` |
| `--ffmpeg PATH` | 手动指定 ffmpeg |
| `--keep-parts` | 保留分片，方便排查问题 |
| `--no-resume` | 不续传，从头下 |
| `--overwrite` | 覆盖同名文件 |
| `--dry-run` | 只解析地址不下载，先看看能不能拿到 |
| `--debug` | 把接口原始返回写到 `debug/`，反馈问题时带上 |

## 下载完放在哪

按课程名建文件夹，文件名优先用课节名：

```
downloads/
└── 高等数学A/
    ├── 高等数学A - 第3讲 导数与微分.mp4
    └── 高等数学A - 第4讲 中值定理.mp4
```

如果一个课节被拆成了多段视频，会先下成 `xxx_p01.mp4`、`xxx_p02.mp4`，再用 ffmpeg 合成
一个完整的 `xxx.mp4`。没有 ffmpeg 的话这几段就保持原样，播放器里接着播就行。

## 常见问题

**解析不到地址怎么办**

先加 `--dry-run --debug` 跑一遍，看看 `debug/` 里存下来的接口返回长什么样。

常见原因就三个：没带 Cookie、Cookie 过期了（重新登录再复制一次）、或者这个课节压根没开录课。
另外云端录课是下课后才开始编码的，一般要等 10 到 30 分钟。

如果确实是 ClassIn 改接口了，最快的办法是浏览器打开回放页按 F12，在 Network 里筛 `m3u8`
或 `mp4`，拿到地址后走 `--media-url`。

**地址有有效期吗**

有，直链通常 48 到 72 小时就失效了，解析出来尽快下。下载一半断了重跑同一条命令会续传，
但如果地址已经过期，那只能重新解析一次。

**为什么这么慢**

ClassIn 的 CDN 对单连接限速比较明显，多开线程会好很多。默认 8 线程，网络好的话可以
`-t 16`。但别开太夸张，下载请求太密集有可能触发风控，建议至少隔几秒发一个任务。

**ts 文件能不能直接看**

能，PotPlayer、VLC、mpv 都直接播 ts。想转成 mp4 的话装个 ffmpeg 再跑一次就行。

**Windows 上终端没有颜色 / 中文乱码**

颜色是自动检测的，重定向到文件时本来就不输出。中文乱码一般是终端代码页的问题，
`chcp 65001` 切到 UTF-8 就好。

## 说明

- 只用来备份你自己账号有权限观看的内容，别拿去做二次分发
- 下载频率别太高，被风控了账号自己受影响
- 解析逻辑依赖 ClassIn 现有的网页接口，对方改版后可能失效，欢迎提 issue
- 觉得有用的话给个 star

## License

MIT
# Classin-Downloader
