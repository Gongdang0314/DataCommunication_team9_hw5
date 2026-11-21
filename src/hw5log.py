# hw5log.py — 공통 로그 형식: [HH:MM:SS.mmm] NODE | EVENT | STATUS | message   (시각은 KST = UTC+9)
import threading, time, os, sys, datetime

KST = datetime.timezone(datetime.timedelta(hours=9))


def ts():
    return datetime.datetime.now(KST).strftime("%H:%M:%S.%f")[:-3]


class Logger:
    def __init__(self, path, node, echo=True):
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.f = open(path, "w", encoding="utf-8", newline="\n")
        self.node, self.echo = node, echo
        self.lk = threading.Lock()            # 로그 파일 전용 Lock (게임 상태 Lock과 별개)

    def __call__(self, event, status, msg):
        line = f"[{ts()}] {self.node} | {event:<9} | {status:<7} | {msg}"
        with self.lk:
            self.f.write(line + "\n")
            self.f.flush()
            if self.echo:
                try:
                    sys.stdout.write(line + "\n")
                    sys.stdout.flush()
                except Exception:
                    pass

    def close(self):
        with self.lk:
            self.f.close()
