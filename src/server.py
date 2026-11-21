# server.py — HW#5 League Server (Main Thread 1 + Table Thread M, Lobby = Mutex 1 + Condition Variable 2)
# 사용법: python3 server.py --port 9000 --seed 2026 --tables 4 --timeout 3000 --run B --out ./run_B
import argparse, socket, select, threading, time, hashlib, random, os, sys, re, traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mybots import PAIRS, prize_order, STRATEGIES
from hw5log import Logger

HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX16 = re.compile(r"^[0-9a-f]{16}$")
sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
h8 = lambda s: sha(s)[:8]


class PlayerConn:
    """Player 한 명의 연결. 수신 버퍼는 Player에 붙어 있다(테이블이 바뀌어도 이어서 읽는다).
    소켓은 그 Player가 PLAYING인 동안 그 경기의 Table Thread만 읽고 쓴다(소유권) — Lock 밖에서 I/O."""
    def __init__(self, k, strategy, sock, addr):
        self.k, self.strategy, self.sock, self.addr = k, strategy, sock, addr
        self.buf = b""
        self.state = "IDLE"        # IDLE · PLAYING · DEAD   (Lobby Mutex로 보호)
        self.busy = False          # 경기 배정됨 (DEAD 선수의 부전패 처리 중에도 True → 같은 선수 경기 겹침 방지)
        self.eof = False

    def send(self, line):
        if self.eof:
            return
        try:
            self.sock.sendall((line + "\n").encode())
        except OSError:
            self.eof = True

    def read_line(self, deadline):
        """deadline(monotonic)까지 한 줄. 마감이 지나도 이미 도착한 줄은 돌려준다. None = 마감, '' = 연결 끊김"""
        while True:
            i = self.buf.find(b"\n")
            if i >= 0:
                line, self.buf = self.buf[:i], self.buf[i + 1:]
                return line.decode("utf-8", "replace").strip()
            if self.eof:
                return ""
            rem = max(0.0, deadline - time.monotonic())
            try:
                r, _, _ = select.select([self.sock], [], [], rem)
            except (OSError, ValueError):
                self.eof = True
                return ""
            if not r:
                return None
            try:
                data = self.sock.recv(65536)
            except OSError:
                data = b""
            if not data:
                self.eof = True
                return ""
            self.buf += data


class League:
    def __init__(self, a):
        self.a = a
        self.S, self.M, self.T = a.seed, a.tables, a.timeout / 1000.0
        self.run = a.run
        os.makedirs(a.out, exist_ok=True)
        self.path = lambda n: os.path.join(a.out, f"Run{a.run}_{n}")
        self.log = Logger(self.path("League.txt"), "SERVER")
        self.players = {}
        # ---- Lobby 공유 상태: Mutex 1개 + CV 2개 ----
        self.m = threading.Lock()
        self.lobby_cv = threading.Condition(self.m)    # Table ↔ Table: "경기가 끝났다, 다시 골라 봐라"
        self.done_cv = threading.Condition(self.m)     # Table → Main: "45경기 끝"
        self.status = ["PENDING"] * 45
        self.assigned = self.finished = 0
        self.result = {}            # mid → (a, b, sA, sB, outcome)
        self.mlog = {}              # mid → match_log 줄들
        self.stats = {"dur": [], "lat": [], "stale": 0, "conf": {"OK": 0, "NO": 0, "DISPUTE": 0, "-": 0},
                      "forfeit": {}, "walkover": 0, "tables": {}, "rejoin": 0}
        self.t_start = None
        self.t_last_end = None
        self.error = None           # Table Thread에서 예상 못 한 예외 → Main이 리그를 중단한다 (무한 대기 방지)

    # ------------------------------------------------------------------ 공통 도우미
    def rel(self, t):
        return t - self.t_start

    def is_dead(self, p):
        with self.m:
            return p.state == "DEAD"

    def mark_dead(self, p, mid, why):
        with self.m:
            p.state = "DEAD"
        if why == "QUIT":
            self.log("DISCONN", "WARN", f"P{p.k} QUIT (virtual disconnect) in G{mid:02d} -> DEAD")
        else:
            self.log("DISCONN", "WARN", f"P{p.k} QUIT (TCP connection lost) in G{mid:02d} -> DEAD")

    def wait_for(self, p, kind, mid, r, deadline, st):
        """kind · mid · r이 맞는 줄을 기다린다. 다른 줄은 STALE로 버리고 REJOIN은 로그만. → (tokens, fail)"""
        while True:
            line = p.read_line(deadline)
            if line is None:
                return None, "TIMEOUT"
            if line == "" and p.eof:
                self.mark_dead(p, mid, "EOF")
                return None, "DISCONNECT"
            t = line.split()
            if not t:
                continue
            if t[0] == "QUIT":
                self.mark_dead(p, mid, "QUIT")
                return None, "DISCONNECT"
            if t[0] == "REJOIN":
                w = f"{kind} {mid}" + (f" {r}" if r is not None else "")
                self.log("REJOIN", "INFO", f"P{p.k} rejoined (waiting {w})")
                st["rejoin"] += 1
                continue
            if t[0] == kind and len(t) >= 2 and t[1] == str(mid) and (r is None or (len(t) >= 3 and t[2] == str(r))):
                return t, None
            st["stale"] += 1
            self.log("STALE", "WARN", f"P{p.k} dropped '{line[:60]}' (waiting {kind} {mid})")

    # ------------------------------------------------------------------ 한 경기 (Lock 밖)
    def play_match(self, mid, table, st):
        a, b = PAIRS[mid]
        A, B = self.players[a], self.players[b]
        t0 = time.monotonic()
        lines = [f"MATCH {mid:02d} P{a} P{b} table={table} t={self.rel(t0):.3f}"]
        self.log("MATCH", "INFO", f"G{mid:02d} P{a}({A.strategy}) vs P{b}({B.strategy}) table={table}")
        with self.m:
            deadA, deadB = A.state == "DEAD", B.state == "DEAD"
        prizes = prize_order(self.S, mid)
        sa = sb = 0
        fail = None                 # (r, who, reason)
        alive = [P for P, d in ((A, deadA), (B, deadB)) if not d]

        if deadA or deadB:
            # ---- 부전패: 살아 있는 선수의 출석 확인 (1판 COMMIT) ----
            st["walkover"] += 1
            if deadA and deadB:
                fail = (0, "BOTH", "DISCONNECT")
            else:
                Y = alive[0]
                side_y = "A" if Y is A else "B"
                Y.send(f"MATCH {mid} {side_y} P{(b if Y is A else a)}")
                Y.send(f"ROUND {mid} 1 {prizes[0]}")
                tk, f = self.wait_for(Y, "COMMIT", mid, 1, time.monotonic() + self.T, st)
                if f is None and (len(tk) != 4 or not HEX64.match(tk[3])):
                    f = "BAD_MSG"
                if f:
                    ra = "DISCONNECT" if deadA else f
                    rb = "DISCONNECT" if deadB else f
                    fail = (0, "BOTH", f"{ra}+{rb}")
                else:
                    fail = (0, "A" if deadA else "B", "DISCONNECT")
        else:
            A.send(f"MATCH {mid} A P{b}")
            B.send(f"MATCH {mid} B P{a}")
            hand = {a: set(range(1, 11)), b: set(range(1, 11))}
            for r, p in enumerate(prizes, 1):
                tr = time.monotonic()
                A.send(f"ROUND {mid} {r} {p}")
                B.send(f"ROUND {mid} {r} {p}")
                dl = tr + self.T
                fails = {}
                cm = {}
                for side, P in (("A", A), ("B", B)):
                    tk, f = self.wait_for(P, "COMMIT", mid, r, dl, st)
                    if f is None and (len(tk) != 4 or not HEX64.match(tk[3])):
                        f = "BAD_MSG"
                    if f:
                        fails[side] = f
                    else:
                        cm[side] = tk[3]
                if fails:
                    fail = (r, *self.who(fails))
                    break
                st["lat"].append(time.monotonic() - tr)
                A.send(f"COMMITS {mid} {r} {cm['A']} {cm['B']}")
                B.send(f"COMMITS {mid} {r} {cm['A']} {cm['B']}")
                dl = time.monotonic() + self.T
                rv = {}
                for side, P, k in (("A", A, a), ("B", B, b)):
                    tk, f = self.wait_for(P, "REVEAL", mid, r, dl, st)
                    if f is None:
                        if len(tk) != 5 or not HEX16.match(tk[4]) or not re.match(r"^-?\d+$", tk[3]):
                            f = "BAD_MSG"
                        elif sha(f"{tk[3]}:{tk[4]}") != cm[side]:
                            f = "BAD_HASH"
                        elif int(tk[3]) not in hand[k]:
                            f = "BAD_CARD"
                    if f:
                        fails[side] = f
                    else:
                        rv[side] = (int(tk[3]), tk[4])
                if fails:
                    fail = (r, *self.who(fails))
                    break
                (ca, na), (cb, nb) = rv["A"], rv["B"]
                hand[a].discard(ca); hand[b].discard(cb)
                w = "A" if ca > cb else ("B" if cb > ca else "-")
                sa += p if w == "A" else 0
                sb += p if w == "B" else 0
                lines.append(f"R {mid:02d} {r} {p} {ca} {na} {cm['A']} {cb} {nb} {cm['B']} {w} {sa} {sb}")
                A.send(f"REVEALS {mid} {r} {ca} {na} {cb} {nb} {w} {sa} {sb}")
                B.send(f"REVEALS {mid} {r} {ca} {na} {cb} {nb} {w} {sa} {sb}")

        if fail:
            r, who, reason = fail
            sa, sb = {"A": (0, 55), "B": (55, 0), "BOTH": (0, 0)}[who]
            outcome = "FORFEIT_" + who
            lines.append(f"F {mid:02d} {r} {who} {reason}")
            key = "walkover" if r == 0 else reason
            st["forfeit"][key] = st["forfeit"].get(key, 0) + 1
            self.log("FORFEIT", "WARN", f"G{mid:02d} P{a} vs P{b} round={r} forfeit={who} reason={reason}")
            for P in (A, B):
                if not self.is_dead(P):
                    P.send(f"FORFEIT {mid} {who} {reason}")
        else:
            outcome = "WIN_A" if sa > sb else ("WIN_B" if sb > sa else "DRAW")

        # ---- MATCH_END → CONFIRM (마감 timeout) ----
        conf = {}
        for P in (A, B):
            if not self.is_dead(P):
                P.send(f"MATCH_END {mid} {outcome} {sa} {sb}")
        dl = time.monotonic() + self.T
        for side, P in (("A", A), ("B", B)):
            if self.is_dead(P):
                conf[side] = "-"
                continue
            tk, f = self.wait_for(P, "CONFIRM", mid, None, dl, st)
            if f == "TIMEOUT":
                conf[side] = "NO"
            elif f:
                conf[side] = "-"
            else:
                conf[side] = "OK" if len(tk) >= 3 and tk[2] == f"{sa}:{sb}" else "DISPUTE"
        for c in conf.values():
            st["conf"][c] += 1
        t1 = time.monotonic()
        lines.append(f"END {mid:02d} {outcome} {sa}:{sb} t={self.rel(t1):.3f}")
        st["dur"].append(t1 - t0)
        self.log("RESULT", "SUCCESS", f"G{mid:02d} P{a} {sa}:{sb} P{b} {outcome} confirm={conf['A']}/{conf['B']} "
                 f"{int((t1 - t0) * 1000)}ms")
        return (a, b, sa, sb, outcome), lines, t1, t1 - t0

    @staticmethod
    def who(fails):
        if len(fails) == 2:
            return "BOTH", f"{fails['A']}+{fails['B']}"
        side = next(iter(fails))
        return side, fails[side]

    # ------------------------------------------------------------------ Lobby
    def pick(self):
        """Lock을 잡은 상태에서 호출: 두 선수 모두 쉬는(배정 안 된) PENDING 경기 중 무작위 하나"""
        cand = [mid for mid in range(45) if self.status[mid] == "PENDING"
                and not self.players[PAIRS[mid][0]].busy and not self.players[PAIRS[mid][1]].busy]
        return random.choice(cand) if cand else None

    def table(self, t):
        try:
            self._table(t)
        except Exception as e:
            fr = traceback.extract_tb(e.__traceback__)[-1]
            why = f"{type(e).__name__}: {e}"
            self.log("TERMINATE", "FAIL", f"table {t} crashed: {why} ({os.path.basename(fr.filename)}:{fr.lineno} {fr.name})")
            with self.m:
                if self.error is None:
                    self.error = f"table {t}: {why}"
                self.lobby_cv.notify_all()
                self.done_cv.notify()

    def _table(self, t):
        st = {"dur": [], "lat": [], "stale": 0, "conf": {"OK": 0, "NO": 0, "DISPUTE": 0, "-": 0},
              "forfeit": {}, "walkover": 0, "rejoin": 0}
        n = 0
        busy = lobby_wait = 0.0
        while True:
            w0 = time.monotonic()
            with self.m:
                while True:
                    if self.assigned == 45 or self.error:
                        mid = None
                        break
                    mid = self.pick()
                    if mid is not None:
                        break
                    self.lobby_cv.wait()
                lobby_wait += time.monotonic() - w0
                if mid is None:
                    break
                a, b = PAIRS[mid]
                for k in (a, b):
                    P = self.players[k]
                    P.busy = True
                    if P.state != "DEAD":
                        P.state = "PLAYING"
                self.status[mid] = "PLAYING"
                self.assigned += 1
            # ---- Lock 밖에서 경기 진행 (send · recv) ----
            res, lines, t_end, dur = self.play_match(mid, t, st)
            n += 1
            busy += dur
            with self.m:
                self.result[mid] = res
                self.mlog[mid] = lines
                self.status[mid] = "DONE"
                for k in (a, b):
                    P = self.players[k]
                    P.busy = False
                    if P.state != "DEAD":
                        P.state = "IDLE"
                self.finished += 1
                if self.finished == 45:
                    self.t_last_end = t_end
                self.lobby_cv.notify_all()
                if self.finished == 45:
                    self.done_cv.notify()
        with self.m:
            self.stats["tables"][t] = (n, busy, lobby_wait)
            for key in ("dur", "lat"):
                self.stats[key] += st[key]
            self.stats["stale"] += st["stale"]
            self.stats["rejoin"] += st["rejoin"]
            self.stats["walkover"] += st["walkover"]
            for c, v in st["conf"].items():
                self.stats["conf"][c] += v
            for c, v in st["forfeit"].items():
                self.stats["forfeit"][c] = self.stats["forfeit"].get(c, 0) + v
        self.log("TABLE", "INFO", f"table {t} exit: matches={n} busy={busy:.2f}s lobby_wait={lobby_wait:.2f}s")

    # ------------------------------------------------------------------ Main
    def accept_players(self):
        """HELLO는 select로 여러 연결을 함께 기다린다 (연결 하나가 HELLO를 안 보내도 다른 Player 접속이 막히지 않는다)"""
        ls = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ls.bind(("0.0.0.0", self.a.port))
        ls.listen(16)
        self.log("INIT", "SUCCESS", f"seed={self.S} tables={self.M} timeout={self.a.timeout}ms run={self.run} "
                 f"listen 0.0.0.0:{self.a.port}")
        waiting = {}                # sock → (PlayerConn 임시, HELLO 마감)

        def reject(s, addr, line):
            self.log("CONNECT", "FAIL", f"bad or duplicate HELLO '{line}' from {addr[0]}:{addr[1]}")
            try:
                s.sendall(b"ERROR bad HELLO\n")
            except OSError:
                pass
            try:
                s.close()
            except OSError:
                pass

        while len(self.players) < 10:
            now = time.monotonic()
            for s, (tmp, dl) in list(waiting.items()):
                if now >= dl:
                    del waiting[s]
                    reject(s, tmp.addr, "(no HELLO in 10s)")
            tmo = max(0.0, min((dl for _, dl in waiting.values()), default=now + 1.0) - now)
            r, _, _ = select.select([ls] + list(waiting), [], [], tmo)
            for s in r:
                if s is ls:
                    c, addr = ls.accept()
                    c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    waiting[c] = (PlayerConn(0, "?", c, addr), time.monotonic() + 10)
                    continue
                tmp, _ = waiting[s]
                line = tmp.read_line(time.monotonic())        # 도착한 데이터만 읽고 바로 돌아온다
                if line is None:
                    continue                                   # 아직 한 줄이 다 오지 않음
                del waiting[s]
                t = line.split()
                ok = (len(t) == 3 and t[0] == "HELLO" and re.match(r"^P([1-9]|10)$", t[1]) and t[2] in STRATEGIES)
                if not ok or int(t[1][1:]) in self.players:
                    reject(s, tmp.addr, line)
                    continue
                k = int(t[1][1:])
                P = PlayerConn(k, t[2], s, tmp.addr)
                P.buf = tmp.buf
                self.players[k] = P
                P.send(f"WELCOME P{k} {self.S} {self.a.timeout}")
                self.log("CONNECT", "SUCCESS", f"P{k} strategy={t[2]} from {tmp.addr[0]}:{tmp.addr[1]} "
                         f"({len(self.players)}/10)")
                if len(self.players) == 10:
                    break
        for s, (tmp, _) in waiting.items():
            reject(s, tmp.addr, "(league full)")
        ls.close()

    def run_league(self):
        self.accept_players()
        for P in self.players.values():
            P.send("START 45")
        self.t_start = time.monotonic()
        self.log("START", "INFO", f"45 matches, {self.M} tables")
        th = [threading.Thread(target=self.table, args=(t,), name=f"Table{t}") for t in range(1, self.M + 1)]
        for x in th:
            x.start()
        with self.m:
            while self.finished < 45 and not self.error:
                self.done_cv.wait()
            err = self.error
        for x in th:
            x.join()
        if err:
            # 다른 테이블은 진행 중인 경기를 끝내고 나온다. 결과가 45경기가 아니므로 파일은 저장하지 않는다.
            for P in self.players.values():
                P.send("BYE")
            time.sleep(0.3)
            for P in self.players.values():
                try:
                    P.sock.shutdown(socket.SHUT_RDWR)
                    P.sock.close()
                except OSError:
                    pass
            self.log("TERMINATE", "FAIL", f"league aborted ({err}), finished {self.finished}/45")
            self.log.close()
            sys.exit(1)
        # ---- Lock 밖에서 저장 ----
        rt, sd, table = self.build_files()
        ml = f"LEAGUE seed={self.S} tables={self.M}\n" + "".join("\n".join(self.mlog[m]) + "\n" for m in range(45))
        for name, text in (("results.txt", rt), ("standings.txt", sd), ("match_log.txt", ml)):
            with open(self.path(name), "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
        self.log("SAVE", "SUCCESS", f"Run{self.run}_results.txt hash={h8(rt)} Run{self.run}_standings.txt hash={h8(sd)}")
        # ---- LEAGUE_END · BYE ----
        for k, P in sorted(self.players.items()):
            if not self.is_dead(P):
                P.send(f"LEAGUE_END {rank_of(table, k)} {pts_of(table, k)}")
            P.send("BYE")
        self.write_stats(table)
        time.sleep(0.3)
        for P in self.players.values():
            try:
                P.sock.shutdown(socket.SHUT_RDWR)
                P.sock.close()
            except OSError:
                pass
        self.log.close()

    def build_files(self):
        res = self.result
        rt = "".join(f"{m:02d} P{a} P{b} {x}:{y} {oc}\n" for m, (a, b, x, y, oc) in sorted(res.items()))
        st = {p: [0, 0, 0, 0, 0, 0] for p in range(1, 11)}          # W D L PTS GF GA
        for a, b, x, y, oc in res.values():
            st[a][4] += x; st[a][5] += y; st[b][4] += y; st[b][5] += x
            if oc == "DRAW":
                for p in (a, b):
                    st[p][1] += 1; st[p][3] += 1
            elif oc == "FORFEIT_BOTH":
                st[a][2] += 1; st[b][2] += 1
            else:
                w, l = (a, b) if oc in ("WIN_A", "FORFEIT_B") else (b, a)
                st[w][0] += 1; st[w][3] += 3; st[l][2] += 1
        order = sorted(st, key=lambda p: (-st[p][3], -(st[p][4] - st[p][5]), -st[p][4], p))
        sd = "".join(f"{i} P{p} " + " ".join(map(str, st[p])) + "\n" for i, p in enumerate(order, 1))
        table = [(p, st[p]) for p in order]
        return rt, sd, table

    def write_stats(self, table):
        S = self.stats
        el = self.t_last_end - self.t_start
        d = S["dur"]
        lat = S["lat"] or [0]
        conc = sum(d) / el if el else 0
        self.log("STAT", "INFO", f"Elapsed {el:.2f}s (START -> 45th match end), tables={self.M}")
        self.log("STAT", "INFO", f"Match time avg {sum(d)/len(d):.3f}s max {max(d):.3f}s min {min(d):.3f}s, "
                 f"avg concurrency {conc:.2f}")
        for t in sorted(S["tables"]):
            n, busy, lw = S["tables"][t]
            self.log("STAT", "INFO", f"Table{t}: matches={n} busy={busy:.2f}s util={100*busy/el:.0f}% lobby_wait={lw:.2f}s")
        self.log("STAT", "INFO", f"Round latency (ROUND -> both COMMIT) avg {1000*sum(lat)/len(lat):.1f}ms "
                 f"max {1000*max(lat):.1f}ms (n={len(S['lat'])})")
        oc = {}
        for (_, _, _, _, o) in self.result.values():
            oc[o] = oc.get(o, 0) + 1
        self.log("STAT", "INFO", "Outcomes " + " ".join(f"{k}={v}" for k, v in sorted(oc.items())) +
                 " | forfeit " + (" ".join(f"{k}={v}" for k, v in sorted(S["forfeit"].items())) or "none") +
                 f" | stale={S['stale']} rejoin={S['rejoin']}")
        c = S["conf"]
        self.log("STAT", "INFO", f"CONFIRM OK={c['OK']} NO={c['NO']} DISPUTE={c['DISPUTE']} -={c['-']}")
        by = {}
        for (a, b, x, y, o) in self.result.values():
            for k, gf, ga, me in ((a, x, y, "A"), (b, y, x, "B")):
                s = self.players[k].strategy
                e = by.setdefault(s, [0, 0, 0, 0, 0])
                win = o in (("WIN_A", "FORFEIT_B") if me == "A" else ("WIN_B", "FORFEIT_A"))
                lose = o == "FORFEIT_BOTH" or o in (("WIN_B", "FORFEIT_A") if me == "A" else ("WIN_A", "FORFEIT_B"))
                e[0] += win; e[1] += (o == "DRAW"); e[2] += lose; e[3] += gf; e[4] += 1
        self.log("STAT", "INFO", "By strategy " + " | ".join(
            f"{s} W{e[0]} D{e[1]} L{e[2]} avg {e[3]/e[4]:.1f}" for s, e in sorted(by.items())))
        self.log("TERMINATE", "SUCCESS", f"45 matches in {el:.2f}s, avg concurrency {conc:.2f}, stale {S['stale']}, "
                 f"tables joined")


def rank_of(table, k):
    for i, (p, _) in enumerate(table, 1):
        if p == k:
            return i


def pts_of(table, k):
    for p, s in table:
        if p == k:
            return s[3]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--tables", type=int, default=4, choices=range(1, 6))
    ap.add_argument("--timeout", type=int, default=3000)
    ap.add_argument("--run", required=True, choices=list("ABCD"))
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    a.out = a.out or f"./run_{a.run}"
    League(a).run_league()


if __name__ == "__main__":
    main()
