# classin-dl

English | [中文](README.md)

Download ClassIn (eeo.cn) cloud recordings and course replays to your local disk.

The official player is web-only, so you can't watch offline and scrubbing through a lecture is
painful. This script grabs the real playback URL using your own login session and pulls the video
down as an mp4.

## Features

- Resolves replay page URLs like `live.php?lessonKey=xxx` and `webcast.php?courseKey=xxx` on its own
- Also takes an m3u8 / mp4 URL directly if you already have one
- Multi-threaded HLS segment download, including AES-128 encrypted streams
- Picks the highest quality from the master playlist by default, or choose your own (`-q 720`)
- Chunked mp4 download with resume — just re-run the same command after a dropped connection
- Remuxes to mp4 when ffmpeg is available, and still works without it (files land as `.ts`, which plays fine)
- Batch mode: pass several links, or a file full of them
- Plain `requests`, no browser automation

## Install

Requires Python 3.8 or newer.

```bash
git clone https://github.com/<your-name>/classin-dl.git
cd classin-dl
pip install -r requirements.txt
```

Then run it straight from the repo, no install step needed:

```bash
python -m classin_dl -h
```

Or install it as a command:

```bash
pip install -e .
classin-dl -h
```

ffmpeg is optional. Put it on your PATH, or point at it with `--ffmpeg`. Everything still downloads
without it — you just don't get automatic ts-to-mp4 remuxing or segment merging, and the tool will
tell you so.

## Usage

The simplest case: paste a replay link from your browser's address bar.

```bash
python -m classin_dl "https://www.eeo.cn/live.php?lessonKey=0a1b2c3d4e5f6a7b"
```

Replay pages normally require a login, so pass your cookies or nothing will resolve:

```bash
python -m classin_dl "https://www.eeo.cn/live.php?lessonKey=xxx" -c "sessionid=abc; uid=123"
```

If the cookie string is unwieldy, put it in a file. Netscape format and a single `a=b; c=d` line
are both accepted:

```bash
python -m classin_dl "https://www.eeo.cn/live.php?lessonKey=xxx" --cookies cookies.txt
```

With `browser-cookie3` installed you can pull them straight out of your browser instead:

```bash
pip install browser-cookie3
python -m classin_dl "https://www.eeo.cn/live.php?lessonKey=xxx" --from-browser chrome
```

Batch download — one link per line in `urls.txt`, `#` for comments:

```bash
python -m classin_dl -f urls.txt -o D:\classin-backup
```

If the resolver ever breaks, or you simply don't want to deal with it, you can hand it an address
you grabbed from your browser's dev tools:

```bash
python -m classin_dl --media-url "https://playback.eeo.cn/xxx/xxx.m3u8" --title "Calculus L3"
```

## Options

| Option | Description |
| --- | --- |
| `urls` | Replay page URL or direct media link; several are allowed |
| `-f, --batch FILE` | Read links from a file |
| `-o, --out DIR` | Output directory, defaults to `./downloads` |
| `-c, --cookie STR` | Cookie string |
| `--cookies FILE` | Cookie file |
| `--from-browser NAME` | Read cookies from chrome / edge / firefox / etc. |
| `--media-url URL` | Skip resolution and download this address; repeatable |
| `--title NAME` | Filename to use together with `--media-url` |
| `-q, --quality` | `best` (default) / `worst` / `720` / an index like `0` `1` `2` |
| `-t, --threads` | Concurrent threads, defaults to 8 |
| `-p, --proxy` | Proxy, e.g. `http://127.0.0.1:7890` |
| `--ffmpeg PATH` | Point at a specific ffmpeg |
| `--keep-parts` | Keep segments and intermediate files, handy for debugging |
| `--no-resume` | Start over instead of resuming |
| `--overwrite` | Overwrite existing files |
| `--dry-run` | Resolve addresses without downloading, to check it works |
| `--debug` | Dump raw API responses to `debug/`; include these when reporting a problem |

## Where files end up

One folder per course, named after the lesson where possible:

```
downloads/
└── Calculus A/
    ├── Calculus A - L03 Derivatives.mp4
    └── Calculus A - L04 Mean Value Theorem.mp4
```

If a single lesson was split into several video parts, they download as `xxx_p01.mp4`,
`xxx_p02.mp4` and so on, then ffmpeg joins them into one `xxx.mp4`. Without ffmpeg the parts stay
as they are — just queue them up in your player.

## FAQ

**It won't resolve anything**

Run it once with `--dry-run --debug` and look at the raw API response saved under `debug/`.

It's usually one of three things: no cookies, expired cookies (log in again and copy fresh ones),
or the lesson simply wasn't recorded. Cloud recordings also aren't encoded until the class is over,
so give it 10 to 30 minutes.

If ClassIn genuinely changed their API, the quickest fix is to open the replay page, hit F12, filter
the Network tab for `m3u8` or `mp4`, and feed whatever you find to `--media-url`.

**Do the links expire?**

Yes. Direct URLs typically die after 48 to 72 hours, so download soon after resolving one. If a
download gets interrupted, re-running the same command resumes it — but only while the link is
still alive. Once it expires you have to resolve again.

**Why is it so slow?**

ClassIn's CDN throttles each connection fairly aggressively, so more threads helps a lot. The
default is 8; try `-t 16` on a good connection. Don't go overboard though — hammering it can trip
their rate limiting, so keep at least a few seconds between jobs.

**Can I just play the .ts file?**

Yes. PotPlayer, VLC and mpv all handle ts directly. Install ffmpeg and run it again if you want mp4.

**No colors, or garbled text, in a Windows terminal**

Colors are auto-detected and suppressed whenever output is redirected. Garbled text is usually the
console code page — `chcp 65001` switches it to UTF-8.

## Notes

- Meant for backing up content your own account has access to; please don't redistribute it
- Keep the download rate reasonable — getting rate-limited only hurts your own account
- Resolution depends on ClassIn's current web endpoints and may break when they change things.
  Issues are welcome
- Star it if it's useful

## License

MIT
