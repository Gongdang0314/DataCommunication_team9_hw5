# run_remote.py — 정식 Run 실행기: 원격(EC2) Server를 ssh로 시작 → (Run D) 로컬 Crasher → 로컬 Player 10개
#                 → Server 종료 대기 → 결과를 scp로 내려받아 Player · Crasher 로그와 합쳐 run_X/ 를 만든다.
# 사용법: python run_remote.py <Run A|B|C|D> <outroot> --key HaEeee.pem --host 13.61.180.113 [--user ubuntu]
#                             [--port 9000] [--connect host:port] [--crasher-seed N]
#   --connect : Player가 접속할 주소 (기본 = --host:--port). 서버 실행 위치는 항상 --host.
import sys, os, subprocess, argparse, time, shutil, glob

HERE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(HERE, "..", "config")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", choices=list("ABCD"))
    ap.add_argument("outroot", nargs="?", default=os.path.join(HERE, ".."))
    ap.add_argument("--key", required=True)
    ap.add_argument("--host", required=True)
    ap.add_argument("--user", default="ubuntu")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--cport", type=int, default=9700)
    ap.add_argument("--connect", default=None)
    ap.add_argument("--crasher-seed", type=int, default=None)
    ap.add_argument("--remote-dir", default="hw5")
    a = ap.parse_args()
    X = a.run
    tables = 1 if X == "A" else 4
    cfg = os.path.join(CFG, "players_fault.txt" if X == "C" else "players_std.txt")
    ssh = ["ssh", "-n", "-i", a.key, "-o", "BatchMode=yes", f"{a.user}@{a.host}"]
    rd, logs = os.path.join(a.outroot, f"run_{X}"), os.path.join(a.outroot, f"logs_{X}")
    for d in (rd, logs):
        shutil.rmtree(d, ignore_errors=True)
    os.makedirs(rd)
    # 1) 원격 Server 시작 (setsid · stdin 분리 → ssh는 바로 돌아온다)
    R = a.remote_dir
    subprocess.run(["scp", "-q", "-i", a.key] + [os.path.join(HERE, f) for f in ("server.py", "mybots.py", "hw5log.py")]
                   + [f"{a.user}@{a.host}:~/{R}/src/"], check=True)
    cmd = (f"cd ~/{R}; pkill -f '^python3 src/server.py --port {a.port}'; rm -rf run_{X}; "
           f"(setsid nohup python3 src/server.py --port {a.port} --seed 2026 --tables {tables} --timeout 3000 "
           f"--run {X} --out ./run_{X} > server_{X}.out 2>&1 < /dev/null &); "
           f"sleep 1; pgrep -f '^python3 src/server.py --port {a.port}' >/dev/null && echo SERVER_UP")
    out = subprocess.run(ssh + [cmd], capture_output=True, text=True).stdout
    if "SERVER_UP" not in out:
        sys.exit("server did not start: " + out)
    print(f"[run_remote] Run {X}: server up on {a.host}:{a.port} (tables={tables})")
    # 2) Crasher (Run D)
    py = sys.executable
    cr, extra = None, []
    if X == "D":
        c = [py, os.path.join(HERE, "crasher.py"), "--port", str(a.cport), "--run", "D", "--out", logs]
        if a.crasher_seed is not None:
            c += ["--seed", str(a.crasher_seed)]
        cr = subprocess.Popen(c, stdout=subprocess.DEVNULL)
        extra = ["--crasher", f"127.0.0.1:{a.cport}"]
        time.sleep(0.5)
    # 3) Player 10개
    ch, cp = (a.connect.rsplit(":", 1) if a.connect else (a.host, str(a.port)))
    t0 = time.time()
    subprocess.run([py, os.path.join(HERE, "run_players.py"), ch, cp, cfg, X, "--out", logs] + extra)
    if cr:
        cr.wait()
    # 4) Server 종료 대기 → 결과 내려받기
    for _ in range(60):
        o = subprocess.run(ssh + [f"pgrep -f '^python3 src/server.py --port {a.port}' || echo DONE"], capture_output=True, text=True).stdout
        if "DONE" in o:
            break
        time.sleep(1)
    subprocess.run(["scp", "-q", "-i", a.key, f"{a.user}@{a.host}:~/{R}/run_{X}/*", rd + "/"], check=True)
    for f in glob.glob(os.path.join(logs, f"Run{X}_*.txt")):
        shutil.copy(f, rd)
    print(f"[run_remote] Run {X} finished in {time.time() - t0:.1f}s -> {rd} ({len(os.listdir(rd))} files)")


if __name__ == "__main__":
    main()
