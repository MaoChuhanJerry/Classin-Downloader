import shutil
import sys
import threading
import time

from .util import human_size, human_time


class Progress:
    def __init__(self, total=None, label=""):
        self.total = total
        self.label = label
        self.done = 0
        self.started = time.time()
        self.samples = [(self.started, 0)]
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.thread = None
        self.last_len = 0
        self.active = sys.stdout.isatty()

    def start(self):
        if not self.active:
            return self
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        return self

    def _loop(self):
        while not self.stop_flag.wait(0.35):
            self.render()

    def add(self, count):
        if count <= 0:
            return
        with self.lock:
            self.done += count

    def speed(self):
        now = time.time()
        self.samples.append((now, self.done))
        while len(self.samples) > 10:
            self.samples.pop(0)
        if len(self.samples) < 2:
            return 0.0
        first_time, first_done = self.samples[0]
        span = now - first_time
        if span <= 0.2:
            return 0.0
        return max(0.0, (self.done - first_done) / span)

    def render(self):
        rate = self.speed()
        columns = shutil.get_terminal_size((110, 24)).columns
        if self.total:
            percent = min(100.0, self.done * 100.0 / self.total)
            bar_width = max(10, min(32, columns - 66))
            filled = int(bar_width * percent / 100.0)
            bar = "#" * filled + "-" * (bar_width - filled)
            eta = (self.total - self.done) / rate if rate > 1024 else None
            line = "{} [{}] {:5.1f}%  {}/{}  {}/s  ETA {}".format(
                self.label, bar, percent, human_size(self.done), human_size(self.total),
                human_size(rate), human_time(eta),
            )
        else:
            line = "{}  {}  {}/s".format(self.label, human_size(self.done), human_size(rate))
        line = line[: max(20, columns - 1)]
        padding = " " * max(0, self.last_len - len(line))
        sys.stdout.write("\r" + line + padding)
        sys.stdout.flush()
        self.last_len = len(line)

    def close(self):
        self.stop_flag.set()
        if self.thread is not None:
            self.thread.join(timeout=1.0)
            self.thread = None
        if self.active and self.last_len:
            sys.stdout.write("\r" + " " * self.last_len + "\r")
            sys.stdout.flush()
            self.last_len = 0
