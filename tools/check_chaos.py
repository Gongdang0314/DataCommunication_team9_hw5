# check_chaos.py — Run D(Crasher Run) 판정 도구
# 사용법: python check_chaos.py run_A run_D        (verify_league.py 와 같은 폴더에서)
#  run_A : 장애 없는 기준 Run (경기마다 정답 결과)    run_D : Crasher Run
# 시각은 비교하지 않는다(원격 Server와 로컬 PC의 시계가 다르므로). 모든 대조는 mid · r 과 로그 순서로 한다.
import sys, os, re, subprocess

ref, d = sys.argv[1], sys.argv[2]
X = lambda folder: os.path.basename(os.path.normpath(folder)).split("_")[-1]
F = lambda folder, n: os.path.join(folder, f"Run{X(folder)}_{n}")
rd = lambda p: open(p, encoding="utf-8").read().rstrip("\n").split("\n")
ok, notes = True, []
def check(cond, msg):
    global ok
    ok &= bool(cond); notes.append(("PASS " if cond else "FAIL ") + msg)

# 0. 파일 · verify ------------------------------------------------------------------------------
need = ["results.txt", "standings.txt", "match_log.txt", "League.txt", "Crasher.txt"] + [f"P{k}.txt" for k in range(1, 11)]
miss = [n for n in need if not os.path.exists(F(d, n))]
check(not miss, f"files {len(need) - len(miss)}/{len(need)}" + (f" missing {miss}" if miss else ""))
if miss: print("\n".join(notes)); print("CHAOS -> FAIL"); sys.exit(1)
v = subprocess.run([sys.executable, "verify_league.py", d], capture_output=True, text=True).stdout.strip()
check(v.split("\n")[-1].endswith("PASS") or "-> PASS" in v, "verify_league.py " + ("PASS" if "-> PASS" in v else "FAIL"))

REF = {int(l.split()[0]): l for l in rd(F(ref, "results.txt"))}
RES = {int(l.split()[0]): l for l in rd(F(d, "results.txt"))}
FL = {int(l.split()[1]): l.split() for l in rd(F(d, "match_log.txt")) if l.startswith("F ")}      # F mid r who reason
L = rd(F(d, "League.txt"))
PAIRS = [(i, j) for i in range(1, 11) for j in range(i + 1, 11)]
side_of = lambda mid, p: "A" if PAIRS[mid][0] == p else "B"

# 1. Crasher 로그: 사건 목록, 동시 장애 없음 -----------------------------------------------------
C = rd(F(d, "Crasher.txt"))
ev = []                                   # (kind, player)
for l in C:
    m = re.search(r"\| (CRASH|QUIT)\s*\| WARN\s*\|.*#\d+ (P\d+)", l)
    if m: ev.append((m.group(1), int(m.group(2)[1:])))
n_crash = sum(1 for k, _ in ev if k == "CRASH"); n_quit = sum(1 for k, _ in ev if k == "QUIT")
check(4 <= len(ev) <= 7, f"장애 사건 {len(ev)}건 (리그 전체 4 ~ 7건)")
check(1 <= n_quit <= 2, f"quit {n_quit}건 (1 ~ 2건 반드시 포함)")
rs = [float(x) for x in re.findall(r"\| RESTART\s*\|.* after ([\d.]+)s", "\n".join(C))]
check(len(rs) == n_crash and all(4.0 <= x <= 5.0 for x in rs), f"crash마다 RESTART {len(rs)}/{n_crash}, 간격 4 ~ 5초 " + (f"({min(rs):.2f} ~ {max(rs):.2f}s)" if rs else ""))

# 2. Player 로그: crash · quit 이 실제로 적용된 경기 (항상 경기 안: Gxx r=..) ---------------------
pcrash, pquit, prejoin = [], {}, {}
for k in range(1, 11):
    for l in rd(F(d, f"P{k}.txt")):
        m = re.search(r"\| (CRASH|QUIT)\s*\| WARN\s*\| G(\d+) r=(\d+) last=(\S+)", l)
        if m:
            (pcrash.append((k, int(m.group(2)), int(m.group(3)), m.group(4))) if m.group(1) == "CRASH"
             else pquit.__setitem__(k, (int(m.group(2)), int(m.group(3)), m.group(4))))
        if "| REJOIN" in l: prejoin[k] = prejoin.get(k, 0) + 1
check(len(pcrash) == n_crash and len(pquit) == n_quit, f"Player 로그 crash {len(pcrash)} · quit {len(pquit)} = Crasher 로그 crash {n_crash} · quit {n_quit} (쉬는 시간 crash 없음: 모두 경기 안 Gxx r=..)")
for p, _, _, _ in pcrash:
    pass
check(all(prejoin.get(p, 0) >= sum(1 for q, *_ in pcrash if q == p) for p, *_ in pcrash), "crash마다 REJOIN 송신 (Player 로그)")

# 3. Server 로그 순서로 각 Player의 경기 차례 · REJOIN을 받은 경기 · DEAD 시점 ---------------------
order = {p: [] for p in range(1, 11)}       # Server가 경기를 시작한 순서
rejoin_at = {p: [] for p in range(1, 11)}   # REJOIN을 받은 순간 기다리던 경기
dead_at = {}
conf = {}
for l in L:
    m = re.search(r"\| MATCH\s*\| INFO\s*\| G(\d+) P(\d+)\(\S+\) vs P(\d+)", l)
    if m:
        mid = int(m.group(1)); order[int(m.group(2))].append(mid); order[int(m.group(3))].append(mid)
    m = re.search(r"\| REJOIN\s*\| INFO\s*\| P(\d+) rejoined \(waiting \S+ (\d+)", l)
    if m: rejoin_at[int(m.group(1))].append(int(m.group(2)))
    m = re.search(r"\| DISCONN\s*\| WARN\s*\| P(\d+) QUIT .* G(\d+)", l)
    if m: dead_at[int(m.group(1))] = int(m.group(2))
    m = re.search(r"\| RESULT\s*\| SUCCESS \| G(\d+) .* confirm=(\S+)/(\S+)", l)
    if m: conf[int(m.group(1))] = (m.group(2), m.group(3))

affected = {}                                # mid → 설명
faulty_at = {}                               # mid → 그 경기에서 장애였던 선수들 (crash 구간 · quit 경기)
# 3-1. crash: crash한 경기부터 REJOIN을 받은 경기까지 (Server 순서)
cr_iter = {}
for p, mid, r, last in pcrash:
    seq = order[p]; i0 = seq.index(mid)
    rj = rejoin_at[p][cr_iter.get(p, 0)] if len(rejoin_at[p]) > cr_iter.get(p, 0) else None
    cr_iter[p] = cr_iter.get(p, 0) + 1
    i1 = seq.index(rj) if rj in seq[i0:] else i0
    span = seq[i0:i1 + 1]
    for m_ in span: faulty_at.setdefault(m_, set()).add(p)
    for j, m_ in enumerate(span):
        line = RES[m_]; s = side_of(m_, p); f = FL.get(m_)
        if f and f[3] in (s, "BOTH") and "TIMEOUT" in f[4]:
            affected[m_] = f"crash P{p}: {' '.join(line.split()[3:])} (r={f[2]} {f[4]})" + (" — 두 선수 모두 장애, 경기 전체 몰수" if f[3] == "BOTH" else "")
        elif not f and line == REF[m_] and (j > 0 or conf.get(m_, ("", ""))[0 if s == 'A' else 1] in ("NO", "OK")):
            affected[m_] = f"crash P{p}: 결과 정상(= Run A), confirm={'/'.join(conf.get(m_, ('?', '?')))}"
        else:
            check(False, f"crash P{p} G{m_:02d}: 기대 = P{p} TIMEOUT 몰수 또는 정상 결과, 실제 = {line}")
    check(True, f"crash P{p} at G{mid:02d} r={r} (last {last}) → 영향 경기 {' '.join(f'G{x:02d}' for x in span)}, REJOIN 받은 경기 G{rj:02d}" if rj is not None else f"crash P{p} at G{mid:02d}: REJOIN 없음")
    if rj is None and i0 == len(seq) - 1:                 # 그 선수의 마지막 경기에서 crash: 이후 읽을 경기가 없어 Server가 못 볼 수 있다
        check(True, f"P{p}: 마지막 경기에서 crash → 이후 경기 없음, Server의 REJOIN 기록은 없어도 됨")
    else:
        check(rj is not None, f"P{p} REJOIN이 Server 로그에 있음")

# 3-2. quit: QUIT한 경기는 DISCONNECT 몰수(또는 CONFIRM 단계면 정상 결과), 이후 경기는 모두 판 0 부전패
for p, (mid, r, last) in pquit.items():
    faulty_at.setdefault(mid, set()).add(p)
    check(dead_at.get(p) == mid, f"quit P{p}: Server DISCONN 경기 G{dead_at.get(p, -1):02d} = Player QUIT 경기 G{mid:02d}")
    f = FL.get(mid); s = side_of(mid, p)
    if f and f[3] in (s, "BOTH") and "DISCONNECT" in f[4]:
        affected[mid] = f"quit P{p}: r={f[2]} DISCONNECT"
    elif not f and RES[mid] == REF[mid]:
        affected[mid] = f"quit P{p}: CONFIRM 단계 QUIT, 결과 정상"
    else:
        check(False, f"quit P{p} G{mid:02d}: 기대 DISCONNECT 몰수, 실제 {RES[mid]}")
    after = order[p][order[p].index(mid) + 1:]
    bad = [m_ for m_ in after if not (FL.get(m_) and FL[m_][2] == "0" and "DISCONNECT" in FL[m_][4] and FL[m_][3] in (side_of(m_, p), "BOTH"))]
    for m_ in after:
        faulty_at.setdefault(m_, set()).add(p)
        affected.setdefault(m_, f"P{p} 부전패 (판 0)" + (" — 상대도 응답 없음, 경기 전체 몰수" if FL.get(m_) and FL[m_][3] == "BOTH" else ""))
    check(not bad, f"quit P{p}: 이후 경기 {len(after)}개 모두 판 0 부전패" + (f" — 어긋남 {bad}" if bad else ""))
    tail = rd(F(d, f"P{p}.txt"))[-1]
    check("left at" in tail, f"quit P{p}: BYE 받고 TERMINATE(left at) 로 종료")

# 3-3. 한 경기 장애 1명 규칙: Crasher는 상대가 장애 중인 선수에게 명령을 보내면 안 된다
viol = []
for p, mid in [(p, mid) for p, mid, _, _ in pcrash] + [(p, v[0]) for p, v in pquit.items()]:
    o = [x for x in PAIRS[mid] if x != p][0]
    if o in faulty_at.get(mid, set()): viol.append(f"G{mid:02d}(P{p}, 상대 P{o})")
check(not viol, f"상대가 장애 중인 선수에게 보낸 명령 {len(viol)}건 (0이어야 함)" + (f" {viol}" if viol else ""))
# 두 선수가 모두 장애였던 경기(일정상 생김: crash가 이어지거나 quit 선수와의 부전패)는 경기 전체 몰수(FORFEIT_BOTH)여야 한다
two = [m_ for m_, ps in faulty_at.items() if len(ps) > 1]
bad2 = [m_ for m_ in two if not (FL.get(m_) and FL[m_][3] == "BOTH")]
check(not bad2, f"두 선수 모두 장애였던 경기 {len(two)}건 → 모두 FORFEIT_BOTH (어긋남 {len(bad2)})" + (f" {bad2}" if bad2 else ""))
# 4. 나머지 경기는 모두 Run A와 같다, 설명 안 되는 몰수 · confirm NO 없음 ------------------------
others = [m_ for m_ in range(45) if m_ not in affected]
diff = [m_ for m_ in others if RES[m_] != REF[m_]]
check(not diff, f"장애와 무관한 {len(others)}경기 = Run A 결과 (다름 {len(diff)})" + (f" {diff[:8]}" if diff else ""))
noconf = [m_ for m_ in others if "NO" in conf.get(m_, ())]
check(not noconf, f"장애와 무관한 경기의 confirm=NO {len(noconf)}건")
unexpl = [m_ for m_ in FL if m_ not in affected]
check(not unexpl, f"설명되지 않는 몰수 {len(unexpl)}건" + (f" {unexpl}" if unexpl else ""))

# 5. 복귀 뒤 첫 경기는 정상 ------------------------------------------------------------------------
for p, mid, r, last in pcrash:
    seq = order[p]; rj = rejoin_at[p][0] if rejoin_at[p] else None
    nxt = [m_ for m_ in seq[seq.index(mid) + 1:] if m_ not in affected or not affected[m_].startswith(f"crash P{p}")]
    if nxt:
        m_ = nxt[0]
        okk = RES[m_] == REF[m_] or (FL.get(m_) and m_ in affected and not affected[m_].startswith(f"crash P{p}"))
        check(okk, f"P{p} 복귀 뒤 첫 경기 G{m_:02d}: {RES[m_]}")
wo = sum(1 for v_ in affected.values() if "부전패" in v_)
print("\n".join(notes))
print(f"# 장애 사건 {len(ev)} (crash {n_crash}, quit {n_quit}) = {100*len(ev)/45:.1f}%  |  영향 경기 {len(affected) - wo} + 부전패 {wo}  |  정상 경기 {len(others)} (= Run A)")
for m_ in sorted(affected): print(f"   G{m_:02d}  {affected[m_]}")
print(f"CHAOS {X(d)} -> {'PASS' if ok else 'FAIL'}")
