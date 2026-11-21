# verify_league.py  —  사용법: python verify_league.py run_B
# run_B/RunB_match_log.txt를 처음부터 다시 계산(replay)해 RunB_results.txt · RunB_standings.txt와 비교한다.
# 파일 이름 규칙: 폴더 run_<X> 안의 파일은 모두 Run<X>_ 로 시작한다 (X = A, B, C, D).
import sys, os, hashlib
M31 = 2 ** 31
def seed_of(text):                       # SHA-256 앞 8자리 → 정수 mod 2^31
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16) % M31
def lcg(seed):
    x = seed % M31
    while True:
        x = (1103515245 * x + 12345) % M31
        yield x >> 16                    # 상위 비트만 사용 (0 ~ 32767)
def prize_order(seed, mid):
    r, a = lcg(seed_of(f"{seed}:{mid}")), list(range(1, 11))
    for i in range(9, 0, -1):
        j = next(r) % (i + 1); a[i], a[j] = a[j], a[i]
    return a
H = lambda c, n: hashlib.sha256(f"{c}:{n}".encode()).hexdigest()
PAIRS = [(i, j) for i in range(1, 11) for j in range(i + 1, 11)]

d = sys.argv[1]
X = os.path.basename(os.path.normpath(d)).split("_")[-1]          # run_B → B
F = lambda name: os.path.join(d, f"Run{X}_{name}")                  # → run_B/RunB_<name>
need = ["results.txt", "standings.txt", "match_log.txt", "League.txt"] + [f"P{k}.txt" for k in range(1, 11)]
miss = [f"Run{X}_{n}" for n in need if not os.path.exists(F(n))]
if miss: print("파일 이름 규칙 위반 또는 파일 없음:", " ".join(miss))
rd = lambda p: open(p).read() if os.path.exists(p) else ""             # 없는 파일은 빈 내용으로
L = rd(F("match_log.txt")).split("\n")
seed = int(L[0].split()[1].split("=")[1]) if L[0].startswith("LEAGUE") else 0
res, spans, err, i = {}, [], [], 1
while L[0].startswith("LEAGUE") and i < len(L) and L[i]:
    _, mid, pa, pb, _, t0 = L[i].split(); mid = int(mid); a, b = int(pa[1:]), int(pb[1:]); i += 1
    if PAIRS[mid] != (a, b): err.append(f"G{mid:02d} 대진 오류")
    hand, sa, sb, oc, po = {a: set(range(1, 11)), b: set(range(1, 11))}, 0, 0, None, prize_order(seed, mid)
    while not L[i].startswith("END"):
        t = L[i].split()
        if t[0] == "R":
            r, p, ca, na, ha, cb, nb, hb = int(t[2]), int(t[3]), int(t[4]), t[5], t[6], int(t[7]), t[8], t[9]
            if po[r - 1] != p: err.append(f"G{mid:02d} r{r} 상금 카드")
            if H(ca, na) != ha or H(cb, nb) != hb: err.append(f"G{mid:02d} r{r} commit hash")
            if ca not in hand[a] or cb not in hand[b]: err.append(f"G{mid:02d} r{r} 카드 중복/범위")
            hand[a].discard(ca); hand[b].discard(cb)
            w = "A" if ca > cb else ("B" if cb > ca else "-")
            sa += p if w == "A" else 0; sb += p if w == "B" else 0
            if (w, sa, sb) != (t[10], int(t[11]), int(t[12])): err.append(f"G{mid:02d} r{r} 판정")
        elif t[0] == "F":
            oc = "FORFEIT_" + t[3]; sa, sb = {"A": (0, 55), "B": (55, 0), "BOTH": (0, 0)}[t[3]]
        i += 1
    e = L[i].split(); i += 1
    oc = oc or ("WIN_A" if sa > sb else "WIN_B" if sb > sa else "DRAW")
    if e[2] != oc or e[3] != f"{sa}:{sb}": err.append(f"G{mid:02d} END 불일치")
    res[mid] = (a, b, sa, sb, oc)
    t0, t1 = float(t0[2:]), float(e[4][2:]); spans += [(a, t0, t1), (b, t0, t1)]
overlap = 0
for p in range(1, 11):
    s = sorted(x for x in spans if x[0] == p)
    overlap += sum(y[1] < x[2] for x, y in zip(s, s[1:]))
# results.txt · standings.txt 다시 만들기
rt = "".join(f"{m:02d} P{a} P{b} {sa}:{sb} {oc}\n" for m, (a, b, sa, sb, oc) in sorted(res.items()))
st = {p: [0, 0, 0, 0, 0, 0] for p in range(1, 11)}          # W D L PTS GF GA
for a, b, sa, sb, oc in res.values():
    st[a][4] += sa; st[a][5] += sb; st[b][4] += sb; st[b][5] += sa
    if oc == "DRAW":
        for p in (a, b): st[p][1] += 1; st[p][3] += 1
    elif oc == "FORFEIT_BOTH":
        st[a][2] += 1; st[b][2] += 1
    else:
        w, l = (a, b) if oc in ("WIN_A", "FORFEIT_B") else (b, a)
        st[w][0] += 1; st[w][3] += 3; st[l][2] += 1
order = sorted(st, key=lambda p: (-st[p][3], -(st[p][4] - st[p][5]), -st[p][4], p))
sd = "".join(f"{k} P{p} " + " ".join(map(str, st[p])) + "\n" for k, p in enumerate(order, 1))
ok_r = rt == rd(F("results.txt"))
ok_s = sd == rd(F("standings.txt"))
h8 = lambda s: hashlib.sha256(s.encode()).hexdigest()[:8]
ok = len(res) == 45 and not err and not overlap and ok_r and ok_s and not miss
print(f"files {len(need)-len(miss)}/{len(need)}  matches {len(res)}/45  round-errors {len(err)}  overlap {overlap}  results {'MATCH' if ok_r else 'DIFF'}  "
      f"standings {'MATCH' if ok_s else 'DIFF'}  results_hash={h8(rt)} standings_hash={h8(sd)}  -> {'PASS' if ok else 'FAIL'}")
for x in err[:10]: print("   ", x)
