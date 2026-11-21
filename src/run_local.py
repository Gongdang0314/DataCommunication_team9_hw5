# run_local.py — (개발 · 테스트용) Server · Crasher · Player를 모두 이 PC에서 띄워 Run 하나를 끝까지 돌린다.
# 정식 제출 결과는 원격 Server로 만든다 (run_remote.py). 사용법:
#   python run_local.py A out_dir [--config players_std.txt] [--port 9500] [--crasher-seed N]
import sys, os, subprocess, argparse, time, shutil, glob

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "..", "config")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", choices=list("ABCD"))
    ap.add_argument("outroot")
    ap.add_argument("--config", default=None)
    ap.add_argument("--port", type=int, default=9500)
    ap.add_argument("--cport", type=int, default=9700)
    ap.add_argument("--tables", type=int, default=None)
    ap.add_argument("--crasher-seed", type=int, default=None)
    a = ap.parse_args()
    X = a.run
    cfg = a.config or os.path.join(CFG, "players_fault.txt" if X == "C" else "players_std.txt")
    tables = a.tables or (1 if X == "A" else 4)
    rd = os.path.join(a.outroot, f"run_{X}")
    logs = os.path.join(a.outroot, f"logs_{X}")
    for d in (rd, logs):
        shutil.rmtree(d, ignore_errors=True)
    py = sys.executable
    out = subprocess.DEVNULL
    srv = subprocess.Popen([py, os.path.join(HERE, "server.py"), "--port", str(a.port), "--seed", "2026",
                            "--tables", str(tables), "--timeout", "3000", "--run", X, "--out", rd], stdout=out)
    cr = None
    extra = []
    if X == "D":
        cmd = [py, os.path.join(HERE, "crasher.py"), "--port", str(a.cport), "--run", "D", "--out", logs]
        if a.crasher_seed is not None:
            cmd += ["--seed", str(a.crasher_seed)]
        cr = subprocess.Popen(cmd, stdout=out)
        extra = ["--crasher", f"127.0.0.1:{a.cport}"]
    time.sleep(0.8)
    t0 = time.time()
    subprocess.run([py, os.path.join(HERE, "run_players.py"), "127.0.0.1", str(a.port), cfg, X, "--out", logs] + extra,
                   stdout=out)
    srv.wait()
    if cr:
        cr.wait()
    for f in glob.glob(os.path.join(logs, f"Run{X}_*.txt")):
        shutil.copy(f, rd)
    print(f"Run {X} done in {time.time() - t0:.1f}s -> {rd}")


if __name__ == "__main__":
    main()
