# crasher.py — HW#5 Crasher (Run D 장애 주입기). Player 10명의 제어 연결만 받는다 (League Server와 통신 없음)
# 사용법: python3 crasher.py --port 9700 --run D --out ./logs [--seed 11]
# Thread: 수신 Thread × 10 (STATE 읽기) · 이벤트 Thread(main) · crash마다 타이머 Thread
# 공유 상태(state · mid_of · faulty · ends)는 Mutex 1개 + Condition Variable 1개로 보호, busy-wait 없음.
import argparse, socket, threading, random, time, os, sys, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mybots import PAIRS
from hw5log import Logger


class Crasher:
    def __init__(self, a):
        self.a = a
        self.seed = a.seed if a.seed is not None else random.SystemRandom().randrange(1, 1000000)
        self.rng = random.Random(self.seed)
        self.log = Logger(os.path.join(a.out, f"Run{a.run}_Crasher.txt"), "CRASHER")
        self.m = threading.Lock()
        self.cv = threading.Condition(self.m)
        self.conn = {}
        self.state = {k: "IDLE" for k in range(1, 11)}     # IDLE · PLAYING · CRASHED · QUIT · END
        self.mid_of = {k: None for k in range(1, 11)}
        self.faulty = set()          # crash 중 · quit 함 · 명령 대기 (C4)
        self.crash_no = {}           # k → 사건 번호 (crash 진행 중)
        self.quit_no = {}
        self.crashed_at = {}         # k → STATE CRASHED 받은 시각
        self.ends = 0                # PLAYING → IDLE 횟수
        self.timers = []
        self.ended = set()           # STATE END(또는 연결 종료)를 보낸 Player
        self.cooldown = set()        # crash 복귀 후 첫 경기를 아직 끝내지 않은 Player (여전히 faulty)

    def over(self):                  # Lock 안에서
        return all(s in ("END", "QUIT") for s in self.state.values())

    def opponent(self, k, mid):
        a, b = PAIRS[mid]
        return b if a == k else a

    # ---------------------------------------------------------------- 수신 Thread (Player마다)
    def reader(self, k, sock, buf):
        while True:
            while b"\n" not in buf:
                try:
                    data = sock.recv(4096)
                except OSError:
                    data = b""
                if not data:
                    with self.m:
                        if self.state[k] not in ("QUIT", "END"):
                            self.state[k] = "END"
                        self.ended.add(k)
                        self.cv.notify_all()
                    return
                buf += data
            line, buf = buf.split(b"\n", 1)
            t = line.decode().split()
            if len(t) < 3 or t[0] != "STATE":
                continue
            new = t[2]
            logs = []
            with self.m:
                old = self.state[k]
                if new == "PLAYING":
                    self.state[k], self.mid_of[k] = "PLAYING", int(t[3])
                elif new == "IDLE":
                    if old == "PLAYING":
                        self.ends += 1
                        if k in self.cooldown:        # 복귀 후 첫 경기를 끝냄 → 장애 해제
                            self.cooldown.discard(k)
                            self.faulty.discard(k)
                    if k in self.crash_no and old in ("CRASHED",):
                        n = self.crash_no.pop(k)
                        # REJOIN이 Server에 닿기 전에 다음 경기가 배정되었을 수 있다(Server는 그 경기에서
                        # REJOIN을 읽는다). 그 경기까지는 crash 구간이므로 복귀 후 첫 경기를 끝낼 때까지
                        # 장애 중으로 두어, 이 선수와 그 상대에게 새 명령을 보내지 않는다.
                        self.cooldown.add(k)
                        logs.append(("REJOINED", "INFO", f"#{n} P{k} back to IDLE"))
                    self.state[k] = "IDLE"
                elif new == "CRASHED":
                    self.state[k] = "CRASHED"
                    self.crashed_at[k] = time.monotonic()
                    n = self.crash_no.get(k, 0)
                    logs.append(("CRASH_ACK", "INFO", f"#{n} P{k} crashed in G{int(t[3]):02d}"))
                    th = threading.Thread(target=self.restart_after, args=(k, n))
                    self.timers.append(th)
                    th.start()
                elif new == "QUIT":
                    self.state[k] = "QUIT"
                    n = self.quit_no.get(k, 0)
                    logs.append(("QUIT_ACK", "INFO", f"#{n} P{k} reported QUIT"))
                elif new == "END":
                    if old != "QUIT":
                        self.state[k] = "END"
                    self.ended.add(k)
                self.cv.notify_all()
            for e in logs:
                self.log(*e)

    # ---------------------------------------------------------------- 타이머 Thread (crash마다)
    def restart_after(self, k, n):
        d = self.rng_delay()
        time.sleep(d)
        with self.m:
            el = time.monotonic() - self.crashed_at[k]
            sent = self.state[k] == "CRASHED"
            if sent:
                try:
                    self.conn[k].sendall(b"RESTART\n")
                except OSError:
                    sent = False
            now = self.state[k]
        self.log("RESTART", "INFO", f"#{n} P{k} after {el:.2f}s" +
                 ("" if sent else f" (not sent: P{k} is {now}, league already over for it)"))

    def rng_delay(self):
        with self.m:
            return self.rng.uniform(4.05, 4.9)

    # ---------------------------------------------------------------- 이벤트 Thread (main)
    def run(self):
        F = self.rng.randint(4, 7)
        Q = self.rng.randint(1, 2)
        kinds = ["QUIT"] * Q + ["CRASH"] * (F - Q)
        self.rng.shuffle(kinds)
        trig = sorted(self.rng.sample(range(2, 31), F))
        self.log("PLAN", "INFO", f"seed={self.seed} events={F} (crash {F - Q}, quit {Q}) = {100 * F / 45:.1f}% of 45  "
                 f"kinds={' '.join(kinds)}  triggers(finished)={trig}")
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("0.0.0.0", self.a.port))
        ls.listen(16)
        pending = {}
        while len(self.conn) < 10:
            s, addr = ls.accept()
            s.settimeout(10)                         # CTRL 줄을 안 보내는 연결이 다른 Player 접속을 막지 않게
            buf = b""
            try:
                while b"\n" not in buf:
                    d = s.recv(1024)
                    if not d:
                        break
                    buf += d
            except OSError:
                pass
            s.settimeout(None)
            line, _, buf = buf.partition(b"\n")
            t = line.decode("utf-8", "replace").split()
            if (not _ or len(t) != 2 or t[0] != "CTRL" or not re.match(r"^P([1-9]|10)$", t[1])
                    or int(t[1][1:]) in self.conn):
                self.log("CONNECT", "FAIL", f"bad or duplicate CTRL '{line[:40].decode('utf-8', 'replace')}' "
                         f"from {addr[0]}:{addr[1]}")
                s.close()
                continue
            k = int(t[1][1:])
            self.conn[k] = s
            pending[k] = buf
            self.log("CONNECT", "SUCCESS", f"P{k} ({len(self.conn)}/10)")
        ls.close()
        for k, s in self.conn.items():
            threading.Thread(target=self.reader, args=(k, s, pending[k]), daemon=True).start()

        fired = {"CRASH": 0, "QUIT": 0}
        for n, (kind, tg) in enumerate(zip(kinds, trig), 1):
            with self.m:
                while self.ends // 2 < tg and not self.over():
                    self.cv.wait()
                if self.over():
                    break
            sent = False
            while not sent:
                with self.m:
                    while True:
                        if self.over():
                            break
                        cand = [k for k in range(1, 11) if self.state[k] == "PLAYING" and k not in self.faulty
                                and self.opponent(k, self.mid_of[k]) not in self.faulty]
                        if cand:
                            break
                        self.cv.wait()
                    if self.over():
                        break
                    k = self.rng.choice(cand)
                    mid = self.mid_of[k]
                    delay = self.rng.uniform(0, 0.3)
                time.sleep(delay)                       # C5: 0 ~ 0.3초 뒤 (경기 안의 임의의 판)
                with self.m:
                    if (self.state[k] == "PLAYING" and self.mid_of[k] == mid and k not in self.faulty
                            and self.opponent(k, mid) not in self.faulty):
                        self.faulty.add(k)
                        if kind == "CRASH":
                            self.crash_no[k] = n
                        else:
                            self.quit_no[k] = n
                        try:
                            self.conn[k].sendall((kind + "\n").encode())
                        except OSError:
                            pass
                        sent = True
                        fired[kind] += 1
                        self.log(kind, "WARN", f"#{n} P{k} (PLAYING G{mid:02d}) finished≈{self.ends // 2}")
            if not sent:
                break
        for th in list(self.timers):
            th.join()
        tot = fired["CRASH"] + fired["QUIT"]
        self.log("SUMMARY", "INFO", f"fired {tot}/{F} events: crash {fired['CRASH']}, quit {fired['QUIT']}  "
                 f"({100 * tot / 45:.1f}% of 45)")
        with self.m:
            while len(self.ended) < 10:
                if not self.cv.wait(timeout=120):
                    break
        for th in list(self.timers):
            th.join()
        self.log("TERMINATE", "SUCCESS", "all players ended")
        self.log.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9700)
    ap.add_argument("--run", default="D", choices=list("ABCD"))
    ap.add_argument("--out", default="./logs")
    ap.add_argument("--seed", type=int, default=None)
    Crasher(ap.parse_args()).run()


if __name__ == "__main__":
    main()
