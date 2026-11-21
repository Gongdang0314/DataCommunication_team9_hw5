# make_compare.py — 네 Run 폴더로 compare_result.txt 를 만든다.
# 사용법: python make_compare.py <조번호> run_A run_B run_C run_D     (verify_league.py · check_chaos.py 와 같은 폴더에서)
# 파일 이름 규칙: run_<X>/Run<X>_results.txt · Run<X>_standings.txt · Run<X>_match_log.txt ... (X = A, B, C, D)
import sys, subprocess, hashlib, os

team, runs = sys.argv[1], sys.argv[2:6]
h8 = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()[:8]
lines = ["# HW#5 compare_result.txt", f"TEAM {team}", "RUN  TABLES  RESULTS   STANDINGS  VERIFY"]
hs = []
for name, d in zip("ABCD", runs):
    X = os.path.basename(os.path.normpath(d)).split("_")[-1]
    if X != name:
        print(f"경고: {d} 는 Run {name} 폴더 이름(run_{name})이 아니다")
    F = lambda n: os.path.join(d, f"Run{X}_{n}")
    tables = open(F("match_log.txt")).readline().split("tables=")[1].split()[0]
    out = subprocess.run([sys.executable, "verify_league.py", d], capture_output=True, text=True).stdout
    v = "PASS" if "-> PASS" in out else "FAIL"
    r, s = h8(F("results.txt")), h8(F("standings.txt"))
    hs.append((r, s)); lines.append(f"{name}    {tables:<7} {r}  {s}   {v}")
same = hs[0] == hs[1]
lines.append(f"A=B  {'SAME -> PASS' if same else 'DIFF -> FAIL'}")
if len(runs) >= 4:
    out = subprocess.run([sys.executable, "check_chaos.py", runs[0], runs[3]], capture_output=True, text=True).stdout.strip().split("\n")
    summ = [l for l in out if l.startswith("# ")]
    lines.append(f"CHAOS D  {summ[0][2:] if summ else ''}  -> {'PASS' if out and out[-1].endswith('PASS') else 'FAIL'}")
open("compare_result.txt", "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
print("\n".join(lines))
