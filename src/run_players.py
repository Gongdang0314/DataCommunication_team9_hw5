# run_players.py — Player 설정 파일(4_config)을 읽어 Player 10개를 독립 프로세스로 한꺼번에 띄운다.
# 사용법: python run_players.py <host> <port> <설정파일> <Run A|B|C|D> [--crasher host:port] [--out ./logs]
#   예)  python run_players.py 13.61.180.113 9000 ../config/players_std.txt B
#        python run_players.py 13.61.180.113 9000 ../config/players_std.txt D --crasher 127.0.0.1:9700
import sys, os, subprocess, argparse

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("port")
    ap.add_argument("config")
    ap.add_argument("run", choices=list("ABCD"))
    ap.add_argument("--crasher", default=None)
    ap.add_argument("--out", default="./logs")
    ap.add_argument("--think", default="18,22")
    a = ap.parse_args()
    procs = []
    with open(a.config, encoding="utf-8") as f:
        for line in f:
            t = line.split()
            if not t or t[0].startswith("#"):
                continue
            cmd = [sys.executable, os.path.join(HERE, "player.py"), "--host", a.host, "--port", a.port,
                   "--id", t[0], "--strategy", t[1], "--think", a.think, "--run", a.run, "--out", a.out]
            if len(t) > 2:
                cmd += ["--fault", t[2]]
            if a.crasher:
                cmd += ["--crasher", a.crasher]
            procs.append(subprocess.Popen(cmd))
    rc = [p.wait() for p in procs]
    print(f"players finished, exit codes {rc}")


if __name__ == "__main__":
    main()
