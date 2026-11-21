# player.py — HW#5 Player (bot). Main Thread = Server 연결, (Run D) 제어 Thread = Crasher 연결
# 사용법: python3 player.py --host H --port 9500 --id 3 --strategy MATCH --think 18,22 --run B --out ./logs
#         [--fault slow@11,4 | badcard@30,7 | badhash@40,3 | quit@21,6]  [--crasher 127.0.0.1:9700]
import argparse, socket, select, threading, time, hashlib, secrets, random, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mybots import Bot
from hw5log import Logger

sha = lambda s: hashlib.sha256(s.encode()).hexdigest()


class Player:
    def __init__(self, a):
        self.a, self.k = a, a.id
        self.log = Logger(os.path.join(a.out, f"Run{a.run}_P{a.id}.txt"), f"P{a.id}", echo=False)
        lo, hi = (float(x) for x in a.think.split(","))
        self.think = (lo / 1000.0, hi / 1000.0)
        self.fault = None
        if a.fault:
            kind, rest = a.fault.split("@")
            fm, fr = rest.split(",")
            self.fault = (kind, int(fm), int(fr))
        # ---- 공유 상태 (Mutex st로 보호): main Thread ↔ 제어 Thread ----
        self.st = threading.Lock()
        self.mode = "IDLE"          # IDLE · PLAYING · CRASHED · RESTARTING · QUIT
        self.pending = None         # IDLE 중 받은 CRASH · QUIT
        self.mid = None             # 지금 경기
        self.last_r, self.last_kind = 0, "-"
        self.left_at = None
        self.ctrl = None
        self.buf = b""
        self.wdl = [0, 0, 0]
        self.rank = self.pts = None
        self.dropped = 0
        self.m = None               # 경기 상태 dict

    # -------------------------------------------------------------- 송신 (항상 st 안에서, mode 확인과 같이)
    def _send(self, line):
        try:
            self.sock.sendall((line + "\n").encode())
        except OSError:
            pass

    def send_if_playing(self, mid, line, kind):
        with self.st:
            if self.mode == "PLAYING" and self.mid == mid:
                self._send(line)
                self.last_kind = kind
                return True
            return False

    def ctrl_send(self, line):
        if self.ctrl:
            try:
                self.ctrl.sendall((line + "\n").encode())
            except OSError:
                pass

    # -------------------------------------------------------------- 제어 Thread (Crasher)
    def control_thread(self):
        buf = b""
        while True:
            try:
                data = self.ctrl.recv(4096)
            except OSError:
                return
            if not data:
                return
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                cmd = line.decode().strip()
                with self.st:
                    if cmd == "CRASH":
                        if self.mode == "PLAYING":
                            self.apply_crash("(now)")
                        elif self.mode == "IDLE":
                            self.pending = "CRASH"
                            self.log("CRASH", "INFO", "received while IDLE -> apply at next MATCH")
                    elif cmd == "QUIT":
                        if self.mode == "PLAYING":
                            self.apply_quit("(now, socket kept open)")
                        elif self.mode == "IDLE":
                            self.pending = "QUIT"
                            self.log("QUIT", "INFO", "received while IDLE -> apply at next MATCH")
                    elif cmd == "RESTART" and self.mode == "CRASHED":
                        self.mode = "RESTARTING"          # 실제 복귀는 main loop가 한다

    def apply_crash(self, note):          # st 안에서
        self.mode = "CRASHED"
        self.log("CRASH", "WARN", f"G{self.mid:02d} r={self.last_r} last={self.last_kind} {note}")
        self.ctrl_send(f"STATE P{self.k} CRASHED {self.mid}")

    def apply_quit(self, note):           # st 안에서
        self._send(f"QUIT {self.mid}")
        self.mode = "QUIT"
        self.left_at = self.mid
        self.log("QUIT", "WARN", f"G{self.mid:02d} r={self.last_r} last={self.last_kind} QUIT sent {note}")
        self.ctrl_send(f"STATE P{self.k} QUIT")

    # -------------------------------------------------------------- 수신
    def read_line(self, timeout):
        while True:
            i = self.buf.find(b"\n")
            if i >= 0:
                line, self.buf = self.buf[:i], self.buf[i + 1:]
                return line.decode("utf-8", "replace").strip()
            r, _, _ = select.select([self.sock], [], [], timeout)
            if not r:
                return None
            data = self.sock.recv(65536)
            if not data:
                return ""
            self.buf += data
            timeout = 0

    def drain(self):
        """복귀 직전: 버퍼에 쌓인 줄과 소켓에 이미 도착한 줄을 모두 버린다"""
        n = self.buf.count(b"\n")
        self.buf = b""
        while True:
            r, _, _ = select.select([self.sock], [], [], 0)
            if not r:
                break
            data = self.sock.recv(65536)
            if not data:
                break
            n += data.count(b"\n")
        return n

    # -------------------------------------------------------------- 실행
    def run(self):
        a = self.a
        self.sock = socket.create_connection((a.host, a.port))
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._send(f"HELLO P{self.k} {a.strategy}")
        t = (self.read_line(30) or "").split()
        if len(t) < 4 or t[0] != "WELCOME":
            self.log("CONNECT", "FAIL", f"no WELCOME ({' '.join(t)})")
            return
        self.S, self.timeout = int(t[2]), int(t[3])
        self.log("CONNECT", "SUCCESS", f"WELCOME seed={self.S} timeout={self.timeout}ms strategy={a.strategy} "
                 f"server={a.host}:{a.port}" + (f" fault={a.fault}" if a.fault else ""))
        if a.crasher:
            h, p = a.crasher.rsplit(":", 1)
            self.ctrl = socket.create_connection((h, int(p)))
            self.ctrl_send(f"CTRL P{self.k}")
            threading.Thread(target=self.control_thread, daemon=True).start()
        while True:
            with self.st:
                restarting = self.mode == "RESTARTING"
            if restarting:
                n = self.drain() + self.dropped
                self.dropped = 0
                with self.st:
                    self._send(f"REJOIN P{self.k}")
                    self.mode, self.mid, self.m = "IDLE", None, None
                    self.log("REJOIN", "INFO", f"REJOIN sent, dropped {n} buffered line(s), wait for next MATCH")
                    self.ctrl_send(f"STATE P{self.k} IDLE")
            line = self.read_line(0.05)
            if line is None:
                continue
            if line == "":
                self.log("TERMINATE", "FAIL", "server closed connection")
                break
            t = line.split()
            with self.st:
                silent = self.mode in ("CRASHED", "QUIT", "RESTARTING")
            if silent:
                if t[0] == "BYE":
                    self.finish()
                    break
                self.dropped += 1
                continue
            if not self.handle(t):
                break
        try:
            self.sock.close()
        except OSError:
            pass
        if self.ctrl:
            try:
                self.ctrl.close()
            except OSError:
                pass
        self.log.close()

    def finish(self):
        W, D, L = self.wdl
        with self.st:
            mode = self.mode
        if mode == "QUIT":
            self.log("TERMINATE", "WARN", f"left at G{self.left_at:02d} (virtual disconnect) W{W} D{D} L{L}")
        elif self.rank is None:
            self.log("TERMINATE", "WARN", f"BYE received while {mode} (no LEAGUE_END) W{W} D{D} L{L}")
        else:
            self.log("TERMINATE", "SUCCESS", f"rank={self.rank} pts={self.pts} W{W} D{D} L{L}")
        self.ctrl_send(f"STATE P{self.k} END")

    def handle(self, t):
        kind = t[0]
        m = self.m
        if kind == "START":
            self.log("START", "INFO", f"league start: {t[1]} matches")
        elif kind == "MATCH":
            mid, side, opp = int(t[1]), t[2], t[3]
            self.m = m = {"mid": mid, "side": side, "opp": opp, "bot": Bot(self.a.strategy, self.S, mid, self.k),
                          "sa": 0, "sb": 0, "forfeit": None, "verify_fail": 0, "rounds": 0}
            with self.st:
                self.mode, self.mid, self.last_r, self.last_kind = "PLAYING", mid, 0, "-"
                self.ctrl_send(f"STATE P{self.k} PLAYING {mid}")
                self.log("MATCH", "INFO", f"G{mid:02d} side={side} vs {opp}")
                pend, self.pending = self.pending, None
                if pend == "CRASH":
                    self.apply_crash("(pending, received while IDLE)")
                elif pend == "QUIT":
                    self.apply_quit("(pending, received while IDLE, socket kept open)")
        elif kind == "ROUND":
            mid, r, p = int(t[1]), int(t[2]), int(t[3])
            if not m or m["mid"] != mid:
                return True
            with self.st:
                self.last_r = r
            f = self.fault if self.fault and self.fault[1] == mid and self.fault[2] == r else None
            if f and f[0] == "quit":
                with self.st:
                    if self.mode == "PLAYING":
                        self._send(f"QUIT {mid}")
                        self.mode = "QUIT"
                        self.left_at = mid
                        self.log("FAULT", "WARN", f"G{mid:02d} r={r} QUIT sent (virtual disconnect, socket kept open)")
                return True
            card = m["bot"].choose(p, r)
            if f and f[0] == "badcard":
                card = 11
                self.log("FAULT", "WARN", f"G{mid:02d} r={r} badcard: COMMIT/REVEAL card 11 (not in hand)")
            nonce = secrets.token_hex(8)
            m.update(r=r, p=p, card=card, nonce=nonce, reveal=card)
            if f and f[0] == "badhash":
                m["reveal"] = card % 10 + 1
                self.log("FAULT", "WARN", f"G{mid:02d} r={r} badhash: COMMIT card {card}, REVEAL card {m['reveal']}")
            if f and f[0] == "slow":
                self.log("FAULT", "WARN", f"G{mid:02d} r={r} slow: sleep {self.timeout + 1000}ms before COMMIT")
                time.sleep(self.timeout / 1000.0 + 1.0)
            time.sleep(random.uniform(*self.think))                     # think 18 ~ 22 ms
            self.send_if_playing(mid, f"COMMIT {mid} {r} {sha(f'{card}:{nonce}')}", "COMMIT")
        elif kind == "COMMITS":
            mid, r = int(t[1]), int(t[2])
            if not m or m["mid"] != mid or m.get("r") != r:
                return True
            m["hA"], m["hB"] = t[3], t[4]
            self.send_if_playing(mid, f"REVEAL {mid} {r} {m['reveal']} {m['nonce']}", "REVEAL")
        elif kind == "REVEALS":
            mid, r = int(t[1]), int(t[2])
            if not m or m["mid"] != mid or m.get("r") != r:
                return True
            cA, nA, cB, nB, w, sA, sB = int(t[3]), t[4], int(t[5]), t[6], t[7], int(t[8]), int(t[9])
            mine, oppc, oppn, opph = ((cA, cB, nB, m.get("hB")) if m["side"] == "A" else (cB, cA, nA, m.get("hA")))
            p = m["p"]
            ew = "A" if cA > cB else ("B" if cB > cA else "-")
            m["sa"] += p if ew == "A" else 0
            m["sb"] += p if ew == "B" else 0
            probs = []
            if sha(f"{oppc}:{oppn}") != opph:
                probs.append("opponent hash")
            if mine != m["reveal"]:
                probs.append("my card")
            if (ew, m["sa"], m["sb"]) != (w, sA, sB):
                probs.append("winner/score")
            if probs:
                m["verify_fail"] += 1
                self.log("VERIFY", "FAIL", f"G{mid:02d} r={r} {', '.join(probs)} mismatch: {' '.join(t)}")
            if m["card"] in m["bot"].hand:
                m["bot"].play(p, r, m["card"], oppc)
            m["rounds"] += 1
        elif kind == "FORFEIT":
            mid = int(t[1])
            if not m or m["mid"] != mid:
                return True
            m["forfeit"] = t[2]
            self.log("FORFEIT", "WARN", f"G{mid:02d} forfeit={t[2]} reason={t[3]}")
        elif kind == "MATCH_END":
            mid, oc, sA, sB = int(t[1]), t[2], int(t[3]), int(t[4])
            if not m or m["mid"] != mid:
                return True
            if m["forfeit"] is None:
                cs = (m["sa"], m["sb"])                       # 내가 계산한 점수로 확인
                eo = "WIN_A" if cs[0] > cs[1] else ("WIN_B" if cs[1] > cs[0] else "DRAW")
                if (eo, cs) != (oc, (sA, sB)):
                    self.log("VERIFY", "FAIL", f"G{mid:02d} MATCH_END {oc} {sA}:{sB} != mine {eo} {cs[0]}:{cs[1]}")
                elif m["verify_fail"] == 0:
                    self.log("VERIFY", "SUCCESS", f"G{mid:02d} {m['rounds']} rounds: hash · card · score ok")
            else:
                cs = (sA, sB)                                 # 몰수는 기록 점수
            me = m["side"]
            mys, ops = (sA, sB) if me == "A" else (sB, sA)
            if oc == "DRAW":
                res = "D"
            elif oc == "FORFEIT_BOTH":
                res = "L"
            else:
                res = "W" if oc in (("WIN_A", "FORFEIT_B") if me == "A" else ("WIN_B", "FORFEIT_A")) else "L"
            with self.st:              # 확인 · CONFIRM 송신 · IDLE 전환을 한 Lock 안에서 (crash가 끼어들지 않게)
                ok = self.mode == "PLAYING" and self.mid == mid
                if ok:
                    self._send(f"CONFIRM {mid} {cs[0]}:{cs[1]}")
                    self.last_kind = "CONFIRM"
                    self.wdl["WDL".index(res)] += 1
                    self.log("RESULT", "INFO", f"G{mid:02d} {oc} me {mys}:{ops} -> {res}")
                    self.mode, self.mid = "IDLE", None
                    self.ctrl_send(f"STATE P{self.k} IDLE")
            self.m = None
        elif kind == "LEAGUE_END":
            self.rank, self.pts = int(t[1]), int(t[2])
        elif kind == "BYE":
            self.finish()
            return False
        return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=9500)
    ap.add_argument("--id", type=int, required=True, choices=range(1, 11))
    ap.add_argument("--strategy", required=True, choices=["RANDOM", "MATCH", "PLUS1", "BIGSMALL", "TEAM"])
    ap.add_argument("--think", default="18,22")
    ap.add_argument("--run", required=True, choices=list("ABCD"))
    ap.add_argument("--out", default="./logs")
    ap.add_argument("--fault", default=None)
    ap.add_argument("--crasher", default=None)
    Player(ap.parse_args()).run()


if __name__ == "__main__":
    main()
