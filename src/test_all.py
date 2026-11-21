# test_all.py — (개발용) 로컬에서 Run A · B · C · D를 돌리고 verify · check_chaos · 로그 검사를 한 번에 한다.
#   python test_all.py <outroot> [runs=ABCD] [--crasher-seed N]
import sys, os, subprocess, re, glob

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, "..", "tools")


def sh(args, cwd=None):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True, cwd=cwd, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8")).stdout


def main():
    root = os.path.abspath(sys.argv[1])
    runs = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("-") else "ABCD"
    extra = sys.argv[sys.argv.index("--crasher-seed"):][:2] if "--crasher-seed" in sys.argv else []
    ok = True
    for X in runs:
        print(sh([os.path.join(HERE, "run_local.py"), X, root] + (extra if X == "D" else [])).strip())
        d = os.path.join(root, f"run_{X}")
        v = sh(["verify_league.py", d], cwd=TOOLS).strip()
        print("  verify:", v)
        ok &= "-> PASS" in v
        league = open(os.path.join(d, f"Run{X}_League.txt"), encoding="utf-8").read()
        conf = re.findall(r"confirm=(\S+)/(\S+)", league)
        bad = [c for c in conf if c != ("OK", "OK")]
        vf = sum(open(f, encoding="utf-8").read().count("| VERIFY    | FAIL") for f in glob.glob(os.path.join(d, f"Run{X}_P*.txt")))
        print(f"  confirm not OK/OK: {len(bad)} {bad[:8]}  VERIFY FAIL: {vf}")
        for l in league.splitlines():
            if "| STAT" in l or "| FORFEIT" in l or "| DISCONN" in l or "| SAVE" in l:
                print("   ", l.split("| ", 3)[-1] if "| STAT" not in l else l.split("| ", 3)[-1])
        if X in "AB":
            ok &= not bad and vf == 0
    if "A" in runs and "D" in runs:
        c = sh(["check_chaos.py", os.path.join(root, "run_A"), os.path.join(root, "run_D")], cwd=TOOLS)
        print(c)
        ok &= c.strip().endswith("PASS")
    print("ALL OK" if ok else "SOMETHING FAILED")


if __name__ == "__main__":
    main()
