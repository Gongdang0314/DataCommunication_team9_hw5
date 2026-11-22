================================================================================
HW#5 - Card Duel League (League Server가 심판하는 10-Player 동시 대전 리그)
9조
================================================================================

문서 수정일: 2026-11-21 KST


1. 조원 정보
================================================================================

  김대영 (20223087)
    - League Server 구현 (Main/Table Thread, Lobby Mutex + Condition Variable,
      timeout · 몰수 · 부전패 · stale 처리), EC2 배포, 원격 실행 스크립트

  김민재 (20223089)
    - Player 구현 (Commit-Reveal, VERIFY, CONFIRM, Run C 고장, Crasher 제어 Thread),
      mybots (seed_of · LCG · 상금 순서 · 표준 전략 4종), TEAM 전략 설계

  황태웅 (20223152)
    - Crasher 구현 (C1 ~ C8), 검증 도구 실행과 반복 테스트, 로그 명세,
      문서 정리, 시연 영상


2. 프로그램 개요
================================================================================

프로그램 설명

  - Python 표준 라이브러리만 사용하는 TCP 기반 카드 대전 리그
  - League Server: AWS EC2에서 실행, Player 10명을 받아 45경기(서로 한 번씩) 진행
  - Player: 로컬 PC의 독립 프로세스 10개 (P1 ~ P10, 정해진 전략으로 두는 bot)
  - Crasher: 로컬 PC에서 실행, Run D에서 경기 중인 Player를 멈추고 · 되살리고 · 떠나게 함
  - 한 경기 = 10판, 상금 카드 1 ~ 10. 큰 카드가 상금을 가져가고 같으면 아무도 못 가짐
  - 매 판 두 선수의 카드를 Commit-Reveal(SHA-256)로 동시에 공개
  - Table Thread M개(1 ~ 5)로 여러 경기를 동시에 진행
  - 늦거나 속이거나 사라진 선수는 규칙대로 몰수 · 부전패 처리

  리그 설정

    경기 수            45 (mid 0 ~ 44, pairs[mid] = (A, B), A = 번호가 작은 쪽)
    승점               승 3 · 무 1 · 패 0
    응답 마감          3,000ms (COMMIT · REVEAL · CONFIRM)
    think              18 ~ 22ms 균등 무작위
    리그 seed          2026
    Player 설정        P1 · P2 RANDOM, P3 · P4 MATCH, P5 · P6 PLUS1,
                       P7 · P8 BIGSMALL, P9 · P10 TEAM

  Run 구성

    Run A   테이블 1개 (기준)
    Run B   테이블 4개 (결과 hash가 Run A와 같아야 함)
    Run C   테이블 4개, 고장 Player 4명 (players_fault.txt)
    Run D   테이블 4개, Crasher 무작위 장애

프로그램 구성요소

  src/
    ├── server.py              League Server (Main 1 + Table Thread M, Lobby, 판정, 저장)
    ├── player.py              Player (Server 연결 main Thread + Crasher 제어 Thread)
    ├── crasher.py             Crasher (Run D 장애 주입기, Player 제어 연결만 받음)
    ├── mybots.py              seed_of, LCG, prize_order, 표준 전략 4종, TEAM 전략, Bot
    ├── hw5log.py              공통 로그 형식 [HH:MM:SS.mmm] NODE | EVENT | STATUS | msg
    ├── run_players.py         설정 파일을 읽어 Player 10개를 독립 프로세스로 실행
    ├── run_remote.py          EC2 Server 시작 → Crasher → Player → 결과 회수 (정식 실행)
    ├── run_local.py           (개발용) 한 PC에서 Run 하나를 끝까지 실행
    └── test_all.py            (개발용) Run A ~ D + verify + check_chaos 일괄 검사

  config/                      kit 4_config 그대로 (players_std · players_fault · players_sample)
  tools/                       kit 2_tools/python 그대로 (verify_league · check_chaos · make_compare)
  run_A/ ~ run_D/              원격 정식 실행 결과
  AllDefinedLogs.txt           로그 이벤트 정의
  compare_result.txt           make_compare 결과
  download.txt                 시연 영상 다운로드 링크


3. 실행 환경 및 필수 준비물
================================================================================

실행 환경

  Server:      AWS EC2 t3.small, eu-north-1a (Stockholm), Ubuntu 26.04 LTS, Python 3.14.4
  Player:      로컬 PC (Windows 11, Python 3.13)
  Crasher:     로컬 PC (Player와 같은 PC)
  네트워크:    TCP Socket, League Server 9000번 / Crasher 로컬 127.0.0.1:9700
  라이브러리:  Python 표준 라이브러리만 사용 (pip 설치 불필요, 컴파일 단계 없음)
  시간 기록:   모든 로그는 KST. EC2 OS 시계는 UTC이지만 hw5log가 KST로 변환한다.
               경과 시간은 각 프로세스의 time.monotonic()으로만 잰다.
  왕복 지연:   로컬 PC ↔ EC2 TCP 연결 기준 약 300 ~ 325ms (한국 → 스톡홀름)

필수 준비물

  로컬 PC
    - Python 3.8 이상: python --version
    - OpenSSH의 ssh / scp 명령
    - src/, config/, tools/가 들어 있는 프로젝트 폴더
    - EC2 접속 키 파일 (HaEeee.pem)

  AWS
    - 실행 중인 Ubuntu EC2 인스턴스와 공인 IP
    - 실행 PC에서 TCP 22, 9000번으로 접속할 수 있는 보안 그룹

  아래 명령은 src/가 보이는 프로젝트 루트에서 실행한다.
  EC2에서는 python3, Windows 예시에서는 python을 사용한다.


4. AWS EC2 서버 준비
================================================================================

4-1. 인스턴스 및 보안 그룹

  사용 인스턴스 유형: t3.small
  리전: eu-north-1 (eu-north-1a)
  OS: Ubuntu 26.04 LTS
  실험에 사용한 공인 IP: 13.61.180.113

  인바운드 규칙:
    - SSH (TCP 22): SSH 접속 PC의 공인 IP 허용
    - 사용자 지정 TCP (TCP 9000): Player 실행 PC의 공인 IP 허용

  Player끼리는 직접 연결하지 않는다(Star 구조). Crasher는 로컬에서만 연결되므로
  다른 포트는 열 필요가 없다.

4-2. 로컬 PowerShell 공통 변수

  실제 키 위치와 현재 EC2 공인 IP에 맞춰 설정한다.
  새 PowerShell 창을 열었다면 다시 설정한다.

    $Ec2Key = "$env:USERPROFILE\.ssh\HaEeee.pem"
    $Ec2Ip = "13.61.180.113"

  개인키는 소스 폴더나 저장소, 제출 ZIP에 넣지 않는다.

4-3. SSH 접속 확인

  로컬 PowerShell:

    ssh -i "$Ec2Key" "ubuntu@$Ec2Ip"

  EC2 터미널:

    python3 --version
    ss -ltnp 'sport = :9000'

  9000번 포트를 이전 실행(HW#4 Assigner 포함)이 쓰고 있지 않은지 확인한다.
  확인 후 exit를 입력하면 로컬 PowerShell로 돌아온다.


5. 소스코드 업로드 (EC2)
================================================================================

  Server 실행에 필요한 파일은 3개다.

    ssh -i "$Ec2Key" "ubuntu@$Ec2Ip" "mkdir -p ~/hw5/src"
    scp -i "$Ec2Key" ./src/server.py ./src/mybots.py ./src/hw5log.py "ubuntu@${Ec2Ip}:~/hw5/src/"

  배포 결과

    ~/hw5/
      ├── src/                 server.py, mybots.py, hw5log.py
      └── run_X/               실행 후 생성 (RunX_League.txt, results, standings, match_log)

  코드를 고친 뒤에는 EC2에도 다시 전송한다. Server와 Player의 mybots.py가 다르면
  hash가 달라진다. run_remote.py는 실행할 때마다 위 3개 파일을 자동으로 전송한다.


6. 명령행 인자 참고
================================================================================

League Server (python3 src/server.py)

  --port        연결을 받을 TCP 포트 (기본: 9000)
  --seed        리그 seed (기본: 2026)
  --tables      Table Thread 수 M, 1 ~ 5 (Run A = 1, Run B · C · D = 4)
  --timeout     COMMIT · REVEAL · CONFIRM 응답 마감 ms (기본: 3000)
  --run         Run 이름 A · B · C · D (출력 파일 접두어 RunX_, 필수)
  --out         결과 폴더 (기본: ./run_X)

Player (python src/player.py)

  --host        League Server 주소 (필수)
  --port        League Server 포트 (기본: 9000)
  --id          Player 번호 1 ~ 10 (필수)
  --strategy    RANDOM · MATCH · PLUS1 · BIGSMALL · TEAM (필수)
  --think       think 시간 범위 ms (기본: 18,22)
  --run         Run 이름 (필수)
  --out         로그 폴더 (기본: ./logs)
  --fault       (Run C) 고장 kind@mid,r   kind ∈ slow · badcard · badhash · quit
  --crasher     (Run D) Crasher 주소 host:port

Crasher (python src/crasher.py)

  --port        제어 연결 포트 (기본: 9700)
  --run         D
  --out         로그 폴더 (기본: ./logs)
  --seed        장애 계획 seed. 생략하면 무작위 (PLAN 줄에 기록)

Player 실행 도우미 (python src/run_players.py)

    python src/run_players.py <host> <port> <설정파일> <Run> [--crasher host:port] [--out 폴더]

  설정 파일 한 줄 "번호 전략 [고장]"을 읽어 Player를 하나씩 독립 프로세스로 띄우고,
  고장이 있으면 --fault를 붙인다.

원격 실행 스크립트 (python src/run_remote.py)

    python src/run_remote.py <A|B|C|D> <outroot> --key <pem> --host <EC2 IP> [--port 9000]
                             [--cport 9700] [--crasher-seed N]


7. 프로그램 실행
================================================================================

7-1. 한 번에 실행 (권장)

  run_remote.py가 다음을 차례로 한다.
    1) server.py · mybots.py · hw5log.py를 EC2로 전송
    2) ssh로 EC2 Server 시작 (setsid nohup, ssh는 바로 돌아옴)
    3) (Run D) 로컬 Crasher 시작
    4) 로컬 Player 10개 실행
    5) Server 종료를 확인하고 결과를 scp로 내려받아 Player · Crasher 로그와 합침

    python src/run_remote.py A . --key "$Ec2Key" --host $Ec2Ip --port 9000
    python src/run_remote.py B . --key "$Ec2Key" --host $Ec2Ip --port 9000
    python src/run_remote.py C . --key "$Ec2Key" --host $Ec2Ip --port 9000
    python src/run_remote.py D . --key "$Ec2Key" --host $Ec2Ip --port 9000

  원격 Run은 하나씩 순서대로 실행한다(같은 포트로 동시에 실행하지 않는다).

7-2. 직접 실행 (시연 영상)

  EC2 터미널에서 Server를 실행한다 (Run B 예).

    cd ~/hw5
    python3 src/server.py --port 9000 --seed 2026 --tables 4 --timeout 3000 --run B --out ./run_B

  INIT 줄이 출력되면 접속을 기다리는 상태이다.

  연결 확인 (로컬 PowerShell):

    Test-NetConnection $Ec2Ip -Port 9000

  TcpTestSucceeded : True이면 연결할 수 있다.

  로컬 PowerShell에서 Player 10개를 띄운다.

    python src/run_players.py 13.61.180.113 9000 config/players_std.txt B --out logs

  Run별 차이

    Run A   Server --tables 1 --run A,   Player players_std.txt A
    Run B   Server --tables 4 --run B,   Player players_std.txt B
    Run C   Server --tables 4 --run C,   Player players_fault.txt C
            (P2 slow@11,4 · P5 badcard@30,7 · P7 badhash@40,3 · P8 quit@21,6)
    Run D   로컬 Crasher → EC2 Server → 로컬 Player 순서로 실행

    python src/crasher.py --port 9700 --run D --out logs
    python3 src/server.py --port 9000 --seed 2026 --tables 4 --timeout 3000 --run D --out ./run_D   (EC2)
    python src/run_players.py 13.61.180.113 9000 config/players_std.txt D --crasher 127.0.0.1:9700 --out logs

7-3. 완료 및 종료 확인

  10명이 모두 접속해야 START가 나간다. 45경기가 끝나면 세 프로그램 모두 자동 종료한다.
  로그에서 다음 항목을 확인한다.

    RunX_League.txt:
      SAVE | SUCCESS (results · standings hash)
      TABLE | INFO table t exit (M개)
      TERMINATE | SUCCESS 45 matches in ...

    RunX_P1.txt ~ RunX_P10.txt:
      TERMINATE | SUCCESS rank=r pts=p Ww Dd Ll
      (QUIT한 Player는 TERMINATE | WARN left at Gxx)

    RunD_Crasher.txt:
      SUMMARY | INFO fired F/F events
      TERMINATE | SUCCESS all players ended

  중간에 중단하려면 각 창에서 Ctrl+C를 누른다. 중단한 실행은 결과로 쓰지 않고
  처음부터 다시 실행한다.


8. 로컬 전용 테스트 (EC2 없이)
================================================================================

bot 단위 테스트

  kit 1_bot_test_kit/python 폴더의 mybots.py를 src/mybots.py로 바꾼 뒤 실행한다.

    python bot_test.py              → 마지막 줄 ALL PASS
    python strategy_arena.py        → 5 x 5 상성표 (TEAM 설계용)

샘플 설정으로 정답 hash 확인

  P9 · P10 = RANDOM인 샘플 설정으로 돌리면 kit 3_sample과 같은 hash가 나와야 한다.

    python src/run_local.py A out_sample --config config/players_sample.txt
    → results_hash=cfde2bce standings_hash=c8a0c732 -> PASS

전체 로컬 테스트

    python src/test_all.py out_test          (Run A · B · C · D + verify + check_chaos)

  마지막 줄이 ALL OK이면 통과다. 로컬에서는 경기 하나가 약 0.22초로 끝나므로
  Run D에서 Crasher가 계획한 사건을 모두 내지 못하는 경우가 있다(G-3 참고).
  재실행할 때는 out_test2처럼 새 폴더를 쓴다.


9. 로그 회수 및 검증
================================================================================

로그 위치

  EC2:   ~/hw5/run_X/RunX_League.txt, RunX_results.txt, RunX_standings.txt,
         RunX_match_log.txt
  로컬:  logs/RunX_P1.txt ~ RunX_P10.txt (Run D는 logs/RunD_Crasher.txt도)

  run_remote.py를 쓰면 자동으로 run_X/에 모인다. 직접 실행했다면:

    scp -i "$Ec2Key" "ubuntu@${Ec2Ip}:~/hw5/run_B/*" ./run_B/
    copy logs\RunB_P*.txt run_B\

  run_A ~ run_C는 14개, run_D는 15개 파일이 된다.

검증

  tools 폴더에서 실행한다 (check_chaos와 make_compare는 같은 폴더의 verify_league를 부른다).
  Windows에서는 한글 출력 때문에 UTF-8 모드로 실행한다(G-5 참고).

    cd tools
    $env:PYTHONUTF8 = "1"
    python verify_league.py ../run_A
    python check_chaos.py ../run_A ../run_D
    python make_compare.py 9 ../run_A ../run_B ../run_C ../run_D

  결과: 네 Run 모두 verify -> PASS, A=B SAME -> PASS, CHAOS D -> PASS


10. EC2 인스턴스 중지
================================================================================

  1) Server · Player · Crasher가 모두 정상 종료했는지 확인한다.
  2) run_X/ 결과를 로컬로 회수하고 검증 결과를 보관한다.
  3) 다른 조원이 같은 인스턴스를 사용 중인지 확인한다.
  4) 모든 작업이 끝났다면 EC2 콘솔에서 인스턴스를 중지한다.

  다시 시작하면 공인 IP가 바뀔 수 있으므로 $Ec2Ip를 갱신한다.


11. 문제 해결
================================================================================

League Server에 연결되지 않음

  확인: Server 실행 여부, 현재 공인 IP, 보안 그룹의 TCP 9000 규칙.

Address already in use

  확인: EC2에서 ss -ltnp 'sport = :9000'
  본인의 이전 Server면 다음 명령으로 종료한다.
    ssh -i "$Ec2Key" "ubuntu@$Ec2Ip" "pkill -f '^python3 src/server.py'"

Player가 접속 후 끝나지 않음

  10명이 모두 접속해야 START가 나간다. 설정 파일이 10줄인지 확인한다.
  Run D는 Crasher를 먼저 실행해야 Player가 CTRL 연결을 할 수 있다.

Server 로그에 CONNECT | FAIL이 남음

  HELLO 형식이 틀렸거나, 번호가 중복이거나, 10초 안에 HELLO를 보내지 않은 연결이다.
  그 연결만 닫고 나머지 Player 접속은 계속 받는다.

Server 로그에 TERMINATE | FAIL league aborted가 남음

  Table Thread에서 예상하지 못한 예외가 난 것이다. 같은 줄 앞의 "table t crashed"에
  예외와 위치가 기록된다. 결과 파일은 저장하지 않으므로 원인을 고친 뒤 다시 실행한다.

hash가 Run A와 다름

  Server와 로컬의 mybots.py가 같은 버전인지 확인한다. TEAM 전략을 고쳤다면 Run A부터
  다시 실행한다.

검증 도구에서 UnicodeDecodeError

  PYTHONUTF8=1로 실행한다(9항).


12. 제출 파일 구성
================================================================================

  제출 파일명: G9HW5.zip (조원 1명이 제출)

  포함 항목
    - src/: server · player · crasher 소스와 실행 스크립트
    - config/, tools/: kit 설정 파일과 검증 도구 (수정 없음)
    - run_A/ ~ run_C/ (14개씩), run_D/ (15개): 원격 정식 실행 결과
    - compare_result.txt, AllDefinedLogs.txt, download.txt, Readme.txt

  SSH 키 파일은 넣지 않는다.


================================================================================

A. League Server - Thread, Lock, Condition 설계
================================================================================

Thread 구성

  - Main Thread 1개: listen → HELLO 10개 확인 → WELCOME → START 45 → Table M개 생성
    → done_cv.wait() → join → (Lock 밖) 결과 저장 → LEAGUE_END · BYE → STAT → TERMINATE
  - Table Thread M개: 경기를 하나씩 골라 끝까지 진행
  - 경기마다, Player마다 Thread를 만들지 않는다.

Table Thread 한 바퀴

  Lock → pick() (고를 경기가 없으면 lobby_cv.wait()) → 두 선수 busy · PLAYING,
  assigned += 1 → Unlock → play_match (Lock 밖에서 send · recv) → Lock → 결과 기록,
  두 선수 IDLE (DEAD는 유지), finished += 1, lobby_cv.notify_all(),
  finished == 45면 done_cv.notify() → Unlock.
  assigned == 45가 되면 TABLE exit 로그를 남기고 끝난다.

공유 상태와 동기화

  - Mutex m 하나로 Player 상태(IDLE · PLAYING · DEAD, busy), 경기 상태(PENDING · PLAYING ·
    DONE), assigned · finished, 결과 · match_log 줄을 보호한다.
  - Condition 두 개를 같은 m에 연결한다.
      lobby_cv   Table ↔ Table: "경기가 끝났다, 다시 골라 봐라"
      done_cv    Table → Main: "45경기 끝" (또는 Table 예외)
  - wait()는 while 조건으로 감싸 깨어난 뒤에도 조건을 다시 확인한다. busy-wait은 없다.
  - Lock을 잡은 채 send · recv · 파일 저장을 하지 않는다.
  - 로그 파일은 Lobby Mutex와 별개인 로그 전용 Lock으로 한 줄씩 쓴다.

pick()

  PENDING이고 두 선수 모두 busy가 아닌 경기 중 무작위 하나를 고른다. 그래서 경기 순서는
  실행마다 다르지만, results는 mid 순서, standings는 순위 순서로 저장하므로 테이블 수와
  관계없이 바이트 단위로 같다(Run A = Run B).

Socket 소유권

  Player가 PLAYING인 동안 그 경기의 Table Thread만 그 소켓을 읽고 쓴다. TCP는 메시지
  경계를 보장하지 않으므로 수신 버퍼에 쌓은 뒤 LF 단위로 자른다. 이 버퍼는 Player 객체에
  붙어 있어 테이블이 바뀌어도 이어서 읽힌다. TCP_NODELAY를 켜서 작은 메시지가 지연되지
  않게 했다.

접속 단계

  HELLO는 select로 여러 연결을 함께 기다린다. 10초 안에 HELLO가 없거나, 형식이 틀리거나,
  번호가 중복이면 그 연결만 닫는다(G-7).

Table Thread 예외

  Table Thread에서 예상하지 못한 예외가 나면 error를 기록하고 lobby_cv · done_cv를 깨운다.
  Main은 리그를 중단하고 모든 Player에게 BYE를 보낸 뒤 TERMINATE | FAIL로 종료한다(G-6).


================================================================================

B. 경기 진행 - timeout · 몰수 · stale · 부전패
================================================================================

한 판의 흐름

  ROUND 송신 → COMMIT 2개 → COMMITS 송신 → REVEAL 2개 → 검사 → REVEALS 송신

  ROUND · COMMITS · MATCH_END를 보낼 때 deadline = now + 3초를 정한다. wait_for()는
  select로 남은 시간만큼 기다리고, 마감이 지나도 이미 도착한 줄은 읽는다(A를 먼저
  기다리느라 B의 줄을 놓치지 않는다).

검사 규칙

  COMMIT   마감 초과 TIMEOUT, 형식(토큰 4개, hash 64자 16진수) 오류 BAD_MSG,
           QUIT 수신 DISCONNECT(+DEAD)
  REVEAL   형식(토큰 5개, 정수 카드, nonce 16자 16진수) 오류 BAD_MSG,
           sha256("card:nonce") ≠ COMMIT hash면 BAD_HASH, 손에 없는 카드면 BAD_CARD
  CONFIRM  마감 안에 같은 점수면 OK, 다르면 DISPUTE, 안 오면 NO, DEAD · QUIT이면 -

몰수

  위반 선수 0 : 55. 두 선수 모두 위반이면 FORFEIT_BOTH 0 : 0, 사유는 사유A+사유B.
  match_log에 F mid r WHO REASON을 남기고 두 선수에게 FORFEIT → MATCH_END를 보낸다.

stale

  기다리는 종류 · mid · r과 다른 줄은 STALE 로그를 남기고 버린다. REJOIN은 기다리던 줄이
  아니므로 REJOIN 로그만 남기고 계속 기다린다.

QUIT과 부전패

  QUIT(가상 끊김)을 받으면 그 경기는 DISCONNECT 몰수, 선수는 DEAD가 된다. 이후 그 선수의
  경기는 살아 있는 상대에게 MATCH · ROUND mid 1 p를 보내 1판 COMMIT으로 출석을 확인한 뒤
  F mid 0 WHO DISCONNECT(부전패)로 처리한다.
    - 상대도 응답이 없으면(crash 중) F mid 0 BOTH TIMEOUT+DISCONNECT
    - 두 선수 모두 DEAD면 F mid 0 BOTH DISCONNECT
  DEAD 선수에게는 아무것도 보내지 않고 마지막에 BYE만 보낸다. 부전패를 처리하는 동안에도
  DEAD 선수를 busy로 두어 같은 선수의 경기가 겹치지 않게 했다(G-4).


================================================================================

C. Player - Thread 구성과 상태 관리
================================================================================

Thread 구성

  - main Thread: Server 소켓을 50ms 단위로 읽는다(줄이 없어도 주기적으로 mode 확인).
      MATCH       새 Bot 생성
      ROUND       think 18 ~ 22ms 후 COMMIT(sha256("card:nonce"), nonce = secrets 8바이트)
      COMMITS     REVEAL
      REVEALS     상대 hash · 판정 · 누적 점수를 직접 확인 (틀리면 VERIFY FAIL)
      MATCH_END   직접 계산한 점수(몰수면 기록 점수)로 CONFIRM
      LEAGUE_END · BYE → TERMINATE
  - 제어 Thread (Run D): Crasher 연결만 읽어 CRASH · QUIT · RESTART를 공유 mode에 반영

공유 상태

  mode ∈ {IDLE, PLAYING, CRASHED, RESTARTING, QUIT}, pending, mid, last_r, last_kind를
  Mutex st로 보호한다. Server로 보내는 모든 줄은 st 안에서 "mode == PLAYING이고 같은
  경기인지" 확인과 함께 보낸다. 그래서 think 중에 crash를 받아도 COMMIT이 새어 나가지
  않는다. CONFIRM 송신과 IDLE 전환도 같은 Lock 안에서 한다.

crash · restart · quit

  - CRASHED · QUIT 중에는 Server 줄을 계속 읽어서 버린다(BYE만 처리).
  - RESTART를 받으면 main loop가 쌓인 줄을 버리고 REJOIN Pk, STATE IDLE을 보낸 뒤 다음
    MATCH부터 새 Bot으로 참여한다. 이때 LEAGUE_END · BYE와 덜 받은 마지막 줄 조각은
    버리지 않는다(G-8).
  - IDLE에서 받은 CRASH · QUIT은 pending으로 기억(INFO)했다가 다음 MATCH를 받는 순간
    적용(WARN, r=0 last=-)한다.

수신

  수신 버퍼에 쌓은 뒤 LF 단위로 자른다. 빈 줄은 건너뛰고, 소켓 오류(RST 등)는 연결 끊김으로
  처리한다(G-9).

Run C 고장 (--fault kind@mid,r)

  slow      그 판 ROUND 뒤 (timeout + 1)초 잠든 뒤 정상 COMMIT
  badcard   카드 11을 COMMIT · REVEAL
  badhash   COMMIT한 카드와 다른 카드(c mod 10 + 1)를 REVEAL
  quit      COMMIT 대신 QUIT mid, 이후 BYE까지 모두 무시 (TCP는 유지)


================================================================================

D. Crasher (C1 ~ C8)
================================================================================

규칙

  C1  --port --run D --out [--seed]. seed는 PLAN 줄에 기록하며, 같은 seed면 같은 계획이다.
  C2  사건 수 F = 4 ~ 7, quit 수 Q = 1 ~ 2, 나머지 crash. 종류 순서는 shuffle.
  C3  발생 시점 = "끝난 경기 수" 2 ~ 30 중 F개
      (끝난 경기 수 ≈ STATE PLAYING → IDLE 횟수 ÷ 2)
  C4  대상 = 지금 PLAYING이고, 자신도 상대도 장애 중(crash 중 · quit · 명령 대기 ·
      복귀 후 첫 경기)이 아닌 선수 중 무작위
  C5  고른 뒤 0 ~ 0.3초 기다리고, Lock 안에서 조건을 다시 확인한 뒤 명령을 보낸다
      (바뀌었으면 다시 고른다).
  C6  STATE CRASHED를 받은 때부터 4.05 ~ 4.9초 뒤 RESTART (crash마다 타이머 Thread)
  C7  quit 선수는 끝까지 장애 목록에 남는다.
  C8  10명 모두 STATE END → SUMMARY · TERMINATE. Server와는 통신하지 않는다.

Thread 구성

  수신 Thread x 10 (STATE 읽기), 이벤트 Thread (main, 시점이 올 때까지 CV wait),
  crash마다 타이머 Thread. 공유 상태(state · mid_of · faulty · cooldown · ends)는
  Mutex 하나와 Condition Variable 하나로 보호한다.

접속 단계

  CTRL Pk 줄을 10초 안에 보내지 않거나, 형식 · 번호(1 ~ 10)가 틀리거나, 이미 접속한
  번호면 CONNECT | FAIL을 남기고 그 연결만 닫는다(G-10).


================================================================================

E. 통신 프로토콜
================================================================================

  모든 메시지는 공백으로 구분한 ASCII 한 줄이며 줄 끝은 LF이다. mid · r은 앞에 0을
  붙이지 않는다(MATCH 5 A P7). 로그 · match_log에서만 2자리(G05, 05)로 쓴다.

    P -> S   HELLO Pk STRATEGY | COMMIT mid r hash | REVEAL mid r card nonce |
             CONFIRM mid sA:sB | QUIT mid | REJOIN Pk
    S -> P   WELCOME Pk seed timeout_ms | START 45 | MATCH mid side Popp |
             ROUND mid r prize | COMMITS mid r hA hB |
             REVEALS mid r cA nA cB nB winner sA sB | FORFEIT mid who reason |
             MATCH_END mid outcome sA sB | LEAGUE_END rank pts | BYE
    P -> C   CTRL Pk | STATE Pk PLAYING mid | STATE Pk IDLE | STATE Pk CRASHED mid |
             STATE Pk QUIT | STATE Pk END
    C -> P   CRASH | RESTART | QUIT

결과 파일

  RunX_results.txt     45줄, mid 순서
  RunX_standings.txt   10줄, 승점 → 득실차 → 득점 → 번호
  RunX_match_log.txt   LEAGUE / MATCH / R / F / END
  RunX_League.txt      Server 로그
  RunX_P1 ~ P10.txt    Player 로그
  RunD_Crasher.txt     Crasher 로그
  모두 LF, hash는 SHA-256 앞 8자리.


================================================================================

F. 결정적 난수와 TEAM 전략
================================================================================

결정적 난수

  seed_of(text) = SHA-256(text)의 16진수 앞 8자리 mod 2^31
  LCG: x = (1103515245 x + 12345) mod 2^31, next() = x >> 16
  상금 순서: LCG("S:mid")로 Fisher-Yates (i = 9 down to 1)
  RANDOM: LCG("S:mid:k")로 매 판 next() 한 번
  TEAM: LCG("S:mid:k:TEAM") 하나만 사용
  Bot은 경기마다 새로 만든다. kit bot_test 전 항목 PASS.

TEAM 규칙 (P9 · P10)

  상대가 누구든 같은 하나의 규칙이다. choose()는 상대 번호 · 상대 전략 · A/B 자리 ·
  경기 번호를 받지 않는다. S · mid · k는 LCG 이름표에만 쓴다.

  1) 이번 경기에서 이미 공개된 상대 카드가 다음 세 반응 규칙 중 어느 것과 지금까지
     모두 맞는지 본다. 상대 손패는 공개된 카드로 정확히 안다.
       (가) 상금과 같은 카드
       (나) 상금보다 큰 카드 중 가장 작은 것
       (다) 상금 6 이상이면 가장 큰 카드, 아니면 가장 작은 카드
     1판(기록 없음)은 세 규칙을 모두 후보로 둔다.
  2) 맞는 규칙이 있으면 예측한 상대 카드마다 내 손패의 카드별로
     (이번 판 기대 득실) - (그 카드의 미래 가치)를 계산해 가장 큰 카드를 낸다.
     미래 가치 = 카드의 손패 내 순위에 대응하는 남은 상금 x 1.3
     동점이면 LCG("S:mid:k:TEAM")로 하나를 고른다.
  3) 맞는 규칙이 없으면 상금의 순위를 손패 순위로 옮긴 카드를 내고, 상금이 5 이상이면
     한 칸 높은 카드를 낸다.

  1.3은 strategy_arena로 0.3 ~ 1.3을 비교해 정했다
  (0.5일 때 BIGSMALL 상대 승률 57% → 1.3일 때 99%).

상성표 (strategy_arena.py, 1,000경기씩, 승/무/패 %, 행 = A, 열 = B)

  A \ B        RANDOM     MATCH      PLUS1      BIGSMALL   TEAM
  RANDOM       46/ 2/52   4/ 0/95   19/ 1/80   14/ 1/85   10/ 1/89
  MATCH        94/ 1/ 6   0/100/0    0/ 0/100  80/ 3/17    1/ 0/99
  PLUS1        78/ 2/20  100/ 0/0    0/100/0   78/ 4/18    0/ 0/100
  BIGSMALL     85/ 1/14   17/ 3/80   18/ 4/78   0/100/0    1/ 0/99
  TEAM         88/ 1/11   99/ 0/ 0  100/ 0/0   99/ 0/ 1    0/100/0

  TEAM은 결정적인 세 전략에 99 ~ 100% 이기고, 예측할 수 없는 RANDOM에 가장 약하다(88%).
  TEAM끼리는 같은 규칙이므로 항상 0 : 0으로 비긴다.


================================================================================

G. 개발 과정 - 1차 구현에서 발견한 문제와 수정 내용
================================================================================

  처음에는 Server · Player · Crasher를 각각 "정상적으로 돌아가는 경우"를 기준으로 만들고,
  로컬 test_all과 원격 실행을 반복하면서 문제를 하나씩 찾아 고쳤다. 앞의 다섯 개(G-1 ~
  G-5)는 원격 실행 중에 드러난 문제이고, 뒤의 것들(G-6 ~ G-13)은 정식 실행 뒤에 코드를
  다시 읽으며 "정상이 아닌 입력이 오면 어떻게 되는가"를 기준으로 점검해 찾은 문제이다.

G-1. 원격 Run D에서 crash 복귀 직후 QUIT이 겹친 문제 (Crasher)

  1차 구현: Crasher는 STATE IDLE(복귀)을 받자마자 그 선수를 장애 목록에서 뺐다.
  문제: 첫 정식 Run D에서 check_chaos가 FAIL이었다. P8이 G39의 CONFIRM 단계에서
        crash했고, 그사이 Server는 P8을 G32에 배정했다. P8의 REJOIN은 Server가 G32의
        1판 COMMIT을 기다리는 중에 도착했으므로 G32까지가 crash 구간이다. 그런데
        Crasher는 복귀를 보자마자 P8을 장애 목록에서 빼서 G32에서 다시 QUIT을 보냈다.
        같은 경기에 crash 구간과 quit이 겹쳤다.
  수정: 복귀한 선수는 "복귀 후 첫 경기를 끝낼 때까지" 장애 중(cooldown)으로 두어 그 선수와
        상대에게 새 명령을 보내지 않도록 했다.
  확인: 원격 Run D를 3번 연속 실행해 모두 CHAOS D -> PASS.

G-2. ssh로 원격 Server를 띄우면 스크립트가 멈춘 문제 (run_remote.py)

  1차 구현: "cd ~/hw5 && ... && nohup python3 server.py ... &"
  문제: && 목록 전체가 백그라운드 subshell이 되어 ssh 채널을 붙잡았다. 또 pkill -f
        'src/server.py'가 그 명령을 실행하는 bash 자신과도 일치해 ssh가 바로 끊겼다.
  수정: 서버 실행만 (setsid nohup ... < /dev/null &)로 분리하고 ssh -n을 썼다.
        pkill 패턴은 '^python3 src/server.py --port 9000'으로 고정했다.

G-3. 로컬에서만 Run D 사건이 모자란 문제 (Crasher)

  문제: 모두 로컬에서 실행하면 경기가 약 0.22초라, Crasher가 C5 규칙(0 ~ 0.3초 대기)
        동안 고른 경기가 끝나 다시 고르기를 반복했다. 늦은 시점(23 ~ 29경기)의 사건은
        리그가 끝날 때까지 다 나가지 못했다(로컬 12번 중 2번 FAIL).
  확인: 같은 Crasher seed를 원격 Server로 실행하면 경기가 약 6.7초라 모두 PASS였다.
  결정: 원격 환경에서는 문제가 없으므로 규칙(C5)은 바꾸지 않았다.

G-4. DEAD 선수의 부전패가 겹칠 수 있는 문제 (Server)

  1차 구현: 명세대로 DEAD 선수를 '경기 중 아님'으로만 보았다.
  문제: 테이블 4개가 같은 DEAD 선수의 부전패 경기를 동시에 처리해 verify의 overlap
        검사에 걸릴 수 있었다.
  수정: 부전패를 처리하는 동안 DEAD 선수에게도 busy 표시를 두어 한 번에 하나씩
        처리하도록 했다. (verify overlap 0)

G-5. Windows 콘솔에서 검증 도구 출력이 깨진 문제

  문제: make_compare · check_chaos가 하위 프로세스 출력을 cp949로 읽어
        UnicodeDecodeError가 났다.
  해결: kit 도구는 수정하지 않고 PYTHONUTF8=1(UTF-8 모드)로 실행했다(9항).

G-6. Table Thread에서 예외가 나면 Server가 끝나지 않는 문제 (Server)

  1차 구현: Table Thread 본체에 예외 처리가 없었고, Main은 done_cv.wait()로
            finished == 45를 timeout 없이 기다렸다.
  문제: play_match 안에서 예상하지 못한 예외가 하나라도 나면 그 Thread만 조용히 죽고,
        그 경기는 finished에 더해지지 않는다. Main은 45를 영원히 기다리고 Player들도
        BYE를 받지 못해 같이 멈춘다. 일부러 G20에서 예외를 내도록 해 보니 실제로
        그렇게 멈췄다.
  수정: Table Thread 본체를 try/except로 감싸 예외가 나면 TERMINATE | FAIL에 예외와
        위치를 남기고, 공유 error에 기록한 뒤 lobby_cv · done_cv를 깨운다.
        다른 Table은 진행 중인 경기만 끝내고 나오며, Main은 모든 Player에게 BYE를 보내고
        "league aborted ..., finished n/45"를 남긴 뒤 종료 코드 1로 끝난다.
        45경기가 아니므로 결과 파일은 저장하지 않는다.
  확인: 같은 예외를 다시 넣었을 때 Server는 1초 안에 종료 코드 1로 끝났고, Player
        10명도 BYE를 받고 종료했다.

G-7. HELLO를 보내지 않는 연결이 다른 Player 접속을 막는 문제 (Server)

  1차 구현: accept() 직후 그 연결에서 HELLO 한 줄을 최대 10초 동안 기다렸다.
  문제: Main Thread 하나가 연결을 차례로 처리하므로, HELLO를 보내지 않는 연결
        (포트 스캐너 등)이 하나 들어오면 그동안 다른 Player는 WELCOME을 받지 못한다.
        보안 그룹을 열어 둔 공인 포트라 실제로 생길 수 있는 상황이다.
  수정: 듣기 소켓과 HELLO를 기다리는 연결들을 select 하나로 함께 기다린다. 연결마다
        10초 마감을 따로 두고, 마감이 지나면 그 연결만 (no HELLO in 10s)로 닫는다.
        10명이 다 찬 뒤 남은 연결은 (league full)로 닫는다.
  확인: 아무것도 보내지 않는 연결과 "HELLO P99 X" 연결을 먼저 붙인 뒤 Player 10명을
        띄웠다. 두 연결은 CONNECT | FAIL로 닫혔고 리그는 기다림 없이 시작해 정상
        hash(7e735e61)로 끝났다.

G-8. 복귀할 때 LEAGUE_END · BYE까지 버리는 문제 (Player)

  1차 구현: RESTART 후 drain()이 버퍼와 소켓에 쌓인 줄을 전부 버렸다.
  문제: 리그 끝 무렵에 복귀하면 이미 도착한 LEAGUE_END · BYE도 같이 버려진다. 그러면
        Player는 BYE를 받지 못하고 Server가 소켓을 닫을 때 TERMINATE | FAIL
        (server closed connection)로 끝난다. 또 recv로 받은 마지막 덩어리가 줄 중간에서
        끊겨 있으면 그 앞부분을 버려, 다음 줄이 뒷부분만 남은 깨진 줄로 읽힐 수 있었다.
  수정: 버릴 때 LEAGUE_END · BYE 줄은 남기고, LF가 아직 오지 않은 마지막 조각도 버퍼에
        남긴다. 버린 줄 수(REJOIN 로그의 dropped N)에는 남긴 줄을 세지 않는다.
  확인: 버퍼에 "ROUND ... / COMMITS ... / LEAGUE_END / BYE / REVE(조각)"을 넣고 drain()을
        부르는 단위 시험에서 LEAGUE_END · BYE · 조각만 남는 것을 확인했다.

G-9. 수신 중 소켓 오류와 빈 줄 처리 (Player)

  1차 구현: read_line()이 select · recv의 예외를 처리하지 않았고, 빈 줄도 ''로 돌려줬다.
  문제: Windows에서 상대가 RST로 끊으면 recv가 ConnectionResetError를 내 traceback과
        함께 Player가 죽고 로그도 닫히지 않는다. 또 ''는 "연결 끊김"의 뜻으로 쓰고
        있었으므로 빈 줄 하나가 와도 연결이 끊긴 것으로 처리됐다. Server 쪽은 eof
        표시로 둘을 구분하고 있었는데 Player는 구분하지 않았다.
  수정: 빈 줄은 건너뛰고, select · recv의 OSError는 연결 끊김('')으로 처리한다.

G-10. Crasher의 CTRL 줄 검증 (Crasher)

  1차 구현: "CTRL P"로 시작하면 int(t[1][1:])로 번호를 꺼냈고, CTRL 줄을 기다리는 recv에
            시간 제한이 없었다.
  문제: "CTRL Pfoo"는 ValueError로, "CTRL P11"은 이후 KeyError로 Crasher 전체가 죽는다.
        같은 번호가 두 번 오면 앞 연결을 덮어썼다. CTRL을 보내지 않는 연결이 있으면
        다음 Player의 제어 연결을 받지 못했다.
  수정: P1 ~ P10 형식과 중복을 확인하고, 틀리면 CONNECT | FAIL을 남기고 그 연결만
        닫는다. CTRL 줄은 10초까지만 기다린다.
  확인: "CTRL Pfoo", "CTRL P11", 중복 "CTRL P1"을 보내도 세 연결만 닫히고 Crasher는
        계속 동작했다.

G-11. 보내지 않은 RESTART를 보낸 것처럼 남긴 로그 (Crasher)

  1차 구현: 타이머가 끝나면 상태가 CRASHED일 때만 RESTART를 보내면서, 로그는 항상
            "#n Pk after d.dds"로 남겼다.
  문제: 리그가 끝나 이미 END가 된 선수에게는 RESTART를 보내지 않았는데도 보낸 것처럼
        기록됐다. 로그만 보고 분석하면 잘못 해석할 수 있다.
  수정: 보내지 않았으면 뒤에 "(not sent: Pk is END, league already over for it)"을
        붙인다. check_chaos가 읽는 "after d.dds" 형식은 그대로 두었다.

G-12. 포트 기본값 불일치 (Player · 스크립트)

  문제: Server 기본 포트는 9000인데 player.py의 --port 기본값과 server.py · player.py ·
        run_remote.py의 사용법 주석은 개발 초기에 쓰던 9500으로 남아 있었다.
  수정: 모두 9000으로 맞췄다. mybots.py의 TEAM 주석도 실제 규칙(상금 5 이상일 때만
        한 칸 위)과 맞게 고쳤다.

G-13. 앞에 0을 붙인 카드 번호를 받아들인 문제 (Server)

  1차 구현: REVEAL의 카드 칸은 정규식 ^-?\d+$로 "정수 모양"인지만 확인하고, hash는 받은
            문자열 그대로 sha256("card:nonce")로 대조했다.
  문제: "05"처럼 앞에 0을 붙인 카드도 형식을 통과한다. COMMIT도 "05:nonce"로 만들었다면
        Server의 hash 검사도 통과한다. 그런데 REVEALS는 카드를 int로 바꿔 "5"로 다시
        보내므로, 상대 Player가 sha256("5:nonce")로 확인하면 hash가 맞지 않는다.
        Server는 정상 판으로 처리하는데 상대는 VERIFY FAIL을 낸다. match_log의 R 줄도
        같은 이유로 다시 계산한 hash와 어긋난다.
        카드를 "05"로 보내는 가짜 P3를 만들어 리그를 돌려 보니 몰수 없이 끝났고, 상대
        Player 로그에 VERIFY FAIL이 90건 남았다.
  수정: 카드 칸은 표준 10진 정수(0 또는 0으로 시작하지 않는 정수)만 받고, 나머지는
        BAD_MSG로 몰수한다. 카드 11처럼 형식은 맞지만 손에 없는 카드는 그대로 BAD_CARD이다.
  확인: 같은 가짜 P3로 다시 돌리면 P3의 경기가 모두 round=1 BAD_MSG로 몰수되고,
        상대 Player의 VERIFY FAIL은 0건이었다.

수정 후 재검증

  G-6 ~ G-13을 고친 뒤 로컬에서 다시 확인했다.
    - test_all: Run A · B · C · D 모두 verify -> PASS, CHAOS D -> PASS, ALL OK
    - Run A = Run B hash 7e735e61 / 4e31bede (수정 전과 같음)
    - 샘플 설정 hash cfde2bce / c8a0c732 (kit 정답과 같음)
  G-6 ~ G-13은 비정상 입력과 예외 상황만 바꾸므로 정상 경기의 결과는 달라지지 않는다.

남은 한계

  - 실제 TCP 끊김은 DEAD로 처리하지만 재접속은 지원하지 않는다(과제 범위 밖).
  - Run C 결과는 경기 순서에 따라 달라질 수 있다. P8의 고장은 quit@21,6이므로, G21보다
    먼저 치른 P8의 경기는 정상 결과로 남는다. 정식 실행에서는 G42를 먼저 치러
    6:40 WIN_B였고, 다른 순서로 실행하면 0:55 부전패가 된다.
  - Crasher가 PLAYING을 보고 명령을 보낸 순간 그 선수가 막 IDLE이 되면, 명령은
    Player에 pending으로 남아 다음 경기에서 적용된다. 이때 다음 경기의 상대가 장애
    중인지는 Crasher가 확인할 수 없다. 이미 보낸 명령을 취소하는 메시지가 프로토콜에
    없으므로 고치지 않았다(실행에서는 발생하지 않았다).
  - 로컬에서만 실행하면 경기가 너무 짧아 Crasher가 계획한 사건을 다 내지 못할 수 있다(G-3).


================================================================================

H. 성능 지표 및 원격 정식 실험 결과
================================================================================

실행 목록 (2026-11-21, 하나씩 순서대로 실행)

  Run A   원격 Server, 테이블 1개
  Run B   원격 Server, 테이블 4개
  Run C   원격 Server, 테이블 4개, players_fault.txt (고장 4건)
  Run D   원격 Server, 테이블 4개, 로컬 Crasher (seed 571607)

  정식 실행은 G-1 ~ G-5를 고친 뒤의 코드로 했다. G-6 ~ G-13은 그 뒤에 고쳤으며,
  정상 경기 결과에 영향이 없음을 로컬 재검증으로 확인했다(G항 끝).

compare_result.txt

  RUN  TABLES  RESULTS   STANDINGS  VERIFY
  A    1       7e735e61  4e31bede   PASS
  B    4       7e735e61  4e31bede   PASS
  C    4       680279a8  360fd52e   PASS
  D    4       0740d6bd  5eef8361   PASS
  A=B  SAME -> PASS
  CHAOS D  장애 사건 5 (crash 3, quit 2) = 11.1% | 영향 경기 6 + 부전패 4 |
           정상 경기 35 (= Run A) -> PASS

표 1. Run별 실측값 (Server 최종 STAT 로그)

  지표                                Run A    Run B    Run C    Run D
  총 실행시간 (START ~ 45번째 종료)   303.35s  79.84s   66.68s   81.75s
  경기 시간 평균                      6.741s   6.670s   5.608s   6.003s
  경기 시간 최대                      6.965s   6.864s   7.121s   9.411s
  경기 시간 최소                      6.386s   6.422s   0.619s   0.624s
  평균 동시 경기 수                   1.00     3.76     3.78     3.30
  판 응답 지연 평균 (ms)              331.7    328.4    333.8    330.6
  판 응답 지연 최대 (ms)              343.8    339.5    357.3    413.6
  CONFIRM OK / NO / DISPUTE / -       90/0/0/0 90/0/0/0 82/0/0/8 80/4/0/6
  STALE / REJOIN                      0 / 0    0 / 0    1 / 0    0 / 3

  몰수 (사유별)
    Run A · B   없음
    Run C       TIMEOUT 1, BAD_CARD 1, BAD_HASH 1, DISCONNECT 1, 부전패 7
    Run D       TIMEOUT 3, DISCONNECT 2, 부전패 4

표 2. 테이블별 (경기 수, 가동률 = 경기 시간 합 ÷ 총 실행시간, Lobby 대기 = lobby_cv 대기 합)

  Run A   Table1 45경기 100% 0.00s
  Run B   Table1 10경기 84% 6.33s  / Table2 11경기 92% 0.00s /
          Table3 12경기 100% 0.00s / Table4 12경기 100% 0.00s
  Run C   Table1 11경기 88% 1.24s  / Table2 11경기 100% 0.00s /
          Table3 10경기 93% 3.59s  / Table4 13경기 98% 1.09s
  Run D   Table1 13경기 100% 0.01s / Table2 11경기 77% 12.24s /
          Table3 10경기 77% 12.10s / Table4 11경기 76% 12.93s

표 3. 전략별 성적 (Run A = Run B, 승/무/패 합계와 경기당 평균 득점)

  RANDOM   (P1 · P2)    W3  D0 L15   평균 18.3
  MATCH    (P3 · P4)    W5  D2 L11   평균 17.6
  PLUS1    (P5 · P6)    W12 D2 L4    평균 28.4
  BIGSMALL (P7 · P8)    W5  D2 L11   평균 15.9
  TEAM     (P9 · P10)   W16 D2 L0    평균 32.9

  Run A 순위: 1 P9, 2 P10 (8승 1무 승점 25), 3 P5, 4 P6 (승점 19), 5 P3, 6 P8, 7 P4,
              8 P7, 9 P2, 10 P1

분석

  1) M = 1과 M = 4의 총 시간 비는 303.35 / 79.84 = 3.80배이다. 4배가 아닌 이유는
     끝부분(tail) 때문이다. 마지막에 남은 경기들의 선수가 겹치면 테이블이 놀 수밖에
     없다. 한 선수가 9경기를 연속으로 치러야 하므로 하한은 약 9 x 6.7s ≈ 60s이다.
  2) Run B의 Table1(84%, Lobby 대기 6.33s)은 리그 끝부분에서 남은 경기의 두 선수가 다른
     테이블에서 경기 중이라 고를 경기가 없어 기다렸다.
  3) 판 응답 지연(ROUND 송신 ~ COMMIT 두 개 도착)은 원격 평균 약 330ms, 로컬 평균
     21.3ms였다. think(약 20ms)를 빼면 원격의 송수신 시간은 약 310ms로 측정한 TCP RTT
     (300 ~ 325ms)와 같다. 한 판에 ROUND → COMMIT, COMMITS → REVEAL 두 번의 왕복이
     필요하므로 10판 경기 하나가 약 6.7초 걸린다.
  4) TEAM은 상금에만 반응하는 결정적 전략에 강하다(99 ~ 100%). 2 ~ 3판이면 상대 규칙이
     드러나 매 판 이기는 가장 작은 카드를 고르기 때문이다. RANDOM에는 상대적으로
     약하다(88%).

정합성 확인

  1) 네 Run 모두 verify_league: files 14/14 (D 15/15), matches 45/45, round-errors 0,
     overlap 0, results · standings MATCH -> PASS
  2) Run A와 Run B의 results · standings hash가 같다 → A=B SAME -> PASS
  3) Run A · B: 모든 RESULT confirm=OK/OK (90/90), Player 로그 VERIFY FAIL 0건
  4) Run C: 고장 4건이 정해진 판 · 사유로 처리되었다.
       G11 r4 P2 TIMEOUT (0:55, 늦게 온 COMMIT은 STALE)
       G21 r6 P8 DISCONNECT (55:0, P8 DEAD)
       G30 r7 P5 BAD_CARD (0:55)
       G40 r3 P7 BAD_HASH (0:55)
     P8의 나머지 경기 중 G42는 G21보다 먼저 치러 정상 결과(6:40)이고, 나머지 7경기는
     판 0 부전패이다. RunC_P8.txt 마지막 줄은 TERMINATE | WARN | left at G21.
  5) Run D: check_chaos.py run_A run_D → CHAOS D -> PASS (I항)
  6) 끝까지 치른 Player의 TERMINATE 줄(rank · pts · W · D · L) = standings의 그 줄
     (Run A · B 10명 모두 일치)


================================================================================

I. Run D 분석
================================================================================

  PLAN: seed=571607 events=5 (crash 3, quit 2), 시점(끝난 경기 수) = 8, 23, 25, 26, 30

표 4. 장애 사건

  #1 CRASH  P1 · G03   r=1 last=COMMIT
            G03 r1 TIMEOUT 0:55, confirm=NO/OK, 6.34s
            RESTART 4.48s → REJOIN (waiting CONFIRM 3)
  #2 CRASH  P2 · G11   r=2 last=REVEAL
            G11 r3 TIMEOUT 0:55, confirm=NO/OK, 7.30s
            RESTART 4.33s → REJOIN (waiting CONFIRM 11)
  #3 CRASH  P4 · G02   r=10 last=REVEAL (CONFIRM 단계)
            G02 결과 정상(= Run A), confirm=OK/NO, 9.41s
            crash가 다음 경기까지 이어져 G26 r1 TIMEOUT
            RESTART 4.29s → REJOIN (waiting COMMIT 26 1)
  #4 QUIT   P3 · G23   r=1 last=REVEAL
            G23 r2 DISCONNECT, P3 DEAD → G18 · G20 부전패 (판 0)
  #5 QUIT   P1 · G04   r=3 last=COMMIT
            G04 r3 DISCONNECT, P1 DEAD → G07 · G08 부전패 (판 0)

  check_chaos: 장애 사건 5건(crash 3, quit 2), crash마다 RESTART 3/3 (4.29 ~ 4.48s),
  영향 경기 6 + 부전패 4, 장애와 무관한 35경기 = Run A 결과, 설명되지 않는 몰수 0건,
  상대가 장애 중인 선수에게 보낸 명령 0건, crash 선수의 복귀 뒤 첫 경기 정상
  → CHAOS D -> PASS

crash당 추가 시간

  정상 경기는 약 6.7초다. 판 중간 crash(G03 · G11 · G26)는 3초 마감 → 몰수 → CONFIRM
  3초 마감으로 6.0 ~ 7.3초가 걸려, 남은 판을 치르지 않는 만큼 경기 하나로는 비슷하다.
  CONFIRM 단계 crash(G02)는 10판을 다 치른 뒤 CONFIRM 3초를 더 기다려 9.4초
  (+약 2.7초)였다.

  리그 전체로는 Run B 79.84초 → Run D 81.75초(+1.9초)였다. 부전패(약 0.6초)가 시간을
  줄였지만, 끝부분에서 테이블 3개가 각 12초 이상 Lobby에서 기다렸다. quit 선수의 남은
  경기가 처리된 뒤 남은 선수들의 경기가 몰리면서 tail이 길어졌기 때문이다.

================================================================================
