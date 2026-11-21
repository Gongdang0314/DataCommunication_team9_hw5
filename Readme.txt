================================================================================
HW#5 - Card Duel League (League Server가 심판하는 10-Player 동시 대전 리그)
9조
================================================================================

1. 조원
================================================================================


   김대영 (20223087)
  - 역할: League Server 구현 (Main/Table Thread, Lobby 매칭 Mutex + Condition Variable,
          timeout · 몰수 · 부전패 · stale 처리), EC2 배포와 원격 실행 스크립트(run_remote.py)
   김민재 (20223089)
  - 역할: Player 구현 (Commit-Reveal, VERIFY, CONFIRM, Run C 고장 흉내, Crasher 제어 Thread),
          mybots(seed_of · LCG · 상금 순서 · 표준 전략 4종)와 TEAM 전략 설계, bot_test
   황태웅 (20223152)
  - 역할: Crasher 구현 (C1 ~ C8), 검증 도구 실행과 반복 테스트(test_all.py), 로그 명세
          (AllDefinedLogs.txt), Readme 정리, 시연 영상 제작

2. 프로그램 개요
================================================================================


  외부 서버(AWS EC2)의 League Server 하나가 로컬 PC의 Player 10개(P1~P10, 정해진 전략으로
  두는 bot)를 받아 Card Duel로 서로 한 번씩, 총 45경기를 치르게 한다. Server는 Table Thread
  M개(1~5)로 여러 경기를 동시에 진행하고, 매 판 두 선수의 카드를 Commit-Reveal(SHA-256)로
  동시에 공개시키며, 늦거나 속이거나 사라진 선수를 규칙대로 몰수·부전패 처리한다. Run D에서는
  로컬 Crasher가 경기 중인 Player를 무작위로 멈추고(crash) · 되살리고(restart) · 떠나게(quit)
  한다.

  - 경기 수: 45 (mid 0~44, pairs[mid] = (A, B), A = 번호가 작은 쪽)
  - 한 경기 = 10판, 상금 카드 1~10 (prize_order(S, mid), Fisher-Yates)
  - 판정: 큰 카드가 상금을 가져감, 같으면 아무도 못 가짐. 승 3 · 무 1 · 패 0
  - 응답 마감(timeout): 3,000ms, think: 18~22ms 균등 무작위
  - 리그 seed: 2026, Player 설정: kit 4_config 그대로 (P9 · P10 = TEAM)
  - Run A(테이블 1개, 기준) · Run B(테이블 4개, hash = Run A) · Run C(고장 Player 4명) ·
    Run D(Crasher 무작위 장애)

  프로그램 구성은 다음과 같다.

  src/server.py: League Server. Main 1 + Table Thread M, Lobby 매칭, 판정, 결과 저장
  src/player.py: Player. Server 연결(main Thread) + Crasher 제어 연결(제어 Thread, Run D)
  src/crasher.py: Crasher (Run D 장애 주입기). Player 10개의 제어 연결만 받는다
  src/mybots.py: seed_of, LCG, prize_order, 표준 전략 4종, TEAM 전략, Bot (통신과 독립)
  src/hw5log.py: 공통 로그 형식 [HH:MM:SS.mmm] NODE | EVENT | STATUS | message (KST)
  src/run_players.py: Player 설정 파일을 읽어 Player 10개를 독립 프로세스로 실행
  src/run_remote.py: EC2 Server 시작(ssh) → Crasher → Player 10개 → 결과 scp → run_X/ 생성
  src/run_local.py, src/test_all.py: 개발용. 모두 로컬에서 Run을 반복 실행하고 검증
  config/: kit 4_config 그대로 (players_std · players_fault · players_sample)
  tools/: kit 2_tools/python 그대로 (verify_league · check_chaos · make_compare)
  AllDefinedLogs.txt: 로그 명세 / download.txt: 시연 영상 주소

3. 실행 환경 및 준비 사항
================================================================================


  Python 표준 라이브러리만 사용한다. 외부 패키지가 없고 컴파일 단계도 없다. Python 3.8
  이상이면 실행된다.

  원격 호스트: AWS EC2 t3.small, eu-north-1a (Stockholm), Ubuntu 26.04 LTS, Python 3.14.4
               (인스턴스 유형과 리전은 서버의 IMDSv2 조회로 확인)
  로컬 PC: Windows 11, Python 3.13. Player 10개와 Crasher를 같은 PC에서 프로세스로 실행
  EC2 공인 IP: 13.61.180.113
  SSH 접속 계정: ubuntu
  서버 작업 폴더: ~/hw5 (소스는 ~/hw5/src, 결과는 ~/hw5/run_X)
  League Server 연결: 13.61.180.113:9000 (TCP) / Crasher: 로컬 127.0.0.1:9700 (TCP)
  로그 시각: KST(UTC+9). EC2 OS 시계는 UTC이지만 세 프로그램 모두 KST로 변환해 기록한다.
  경과 시간 측정: time.monotonic() (Server의 같은 단조 시계)
  로컬 PC ↔ EC2 왕복 지연: TCP 연결 기준 약 300~325ms (한국 → 스톡홀름)

  실행 전에 다음 사항을 확인한다.

  - Python 실행 여부: python --version
  - EC2의 현재 공인 IP와 SSH 접속 가능 여부
  - EC2 보안 그룹에서 TCP 9000번 포트가 실행 PC에 열려 있는지 (HW#3 · #4와 같은 포트)
  - 이전 실행(HW#4 Assigner 포함)이 9000번 포트를 사용하고 있지 않은지

4. EC2 준비 및 소스 전송
================================================================================


  EC2 보안 그룹에는 SSH용 TCP 22번과 League Server용 TCP 9000번 포트를 연다. Player끼리는
  직접 연결하지 않고(Star 구조), Crasher는 로컬에서만 연결되므로 다른 포트는 열 필요가 없다.

  SSH 키 파일은 제출 ZIP에 넣지 않는다. 로컬 PowerShell에서 다음 값을 설정한다.

    $Ec2Key = "$env:USERPROFILE\.ssh\HaEeee.pem"
    $Ec2Ip = "13.61.180.113"

  Server 실행에 필요한 파일 3개를 EC2에 전송한다.

    ssh -i "$Ec2Key" "ubuntu@$Ec2Ip" "mkdir -p ~/hw5/src"
    scp -i "$Ec2Key" ./src/server.py ./src/mybots.py ./src/hw5log.py "ubuntu@${Ec2Ip}:~/hw5/src/"

  코드를 수정한 뒤에는 EC2에도 다시 전송한다. run_remote.py는 실행할 때마다 자동으로
  전송한다.

5. 명령행 인자
================================================================================


League Server (server.py)

  --port: 연결을 받을 TCP 포트. 기본값 9000
  --seed: 리그 seed. 기본값 2026
  --tables: Table Thread 수 M (1~5). Run A = 1, Run B · C · D = 4
  --timeout: COMMIT · REVEAL · CONFIRM 응답 마감(ms). 기본값 3000
  --run: Run 이름 (A · B · C · D). 출력 파일 접두어 RunX_
  --out: 결과 폴더. 기본값 ./run_X

Player (player.py)

  --host, --port: League Server 주소
  --id: Player 번호 1~10
  --strategy: RANDOM · MATCH · PLUS1 · BIGSMALL · TEAM
  --think: think 시간 범위(ms). 기본값 18,22
  --run: Run 이름 / --out: 로그 폴더. 기본값 ./logs
  --fault: (Run C) 고장 kind@mid,r (slow · badcard · badhash · quit)
  --crasher: (Run D) Crasher 주소 host:port

Crasher (crasher.py)

  --port: 제어 연결 포트. 기본값 9700
  --run: D / --out: 로그 폴더
  --seed: 장애 계획 seed. 생략하면 무작위 (PLAN 줄에 기록)

Player 실행 도우미 (run_players.py)

    python src/run_players.py <host> <port> <설정파일> <Run> [--crasher host:port] [--out 폴더]

  설정 파일 한 줄 "번호 전략 [고장]"을 읽어 Player를 하나씩 독립 프로세스로 띄우고, 고장이
  있으면 --fault를 붙인다.

6. 프로그램 실행 (EC2 + 로컬 PC)
================================================================================


6-1. 한 번에 실행 (권장)

  run_remote.py가 ssh로 EC2 Server를 시작하고, 로컬 Crasher(Run D)와 Player 10개를 띄운 뒤,
  Server가 끝나면 결과를 scp로 내려받아 Player · Crasher 로그와 합쳐 run_X/ 폴더를 만든다.
  원격 Run은 하나씩 순서대로 실행한다(동시에 실행하지 않는다).

    python src/run_remote.py A . --key "$Ec2Key" --host $Ec2Ip --port 9000
    python src/run_remote.py B . --key "$Ec2Key" --host $Ec2Ip --port 9000
    python src/run_remote.py C . --key "$Ec2Key" --host $Ec2Ip --port 9000
    python src/run_remote.py D . --key "$Ec2Key" --host $Ec2Ip --port 9000

6-2. 직접 실행 (시연 영상)

  EC2 터미널에서 Server를 실행한다 (Run B 예).

    cd ~/hw5
    python3 src/server.py --port 9000 --seed 2026 --tables 4 --timeout 3000 --run B --out ./run_B

  INIT 줄이 출력되면 접속을 기다리는 상태이다. 로컬 PowerShell에서 Player 10개를 띄운다.

    python src/run_players.py 13.61.180.113 9000 config/players_std.txt B --out logs

  Run A: --tables 1 --run A,  players_std.txt A
  Run C: --tables 4 --run C,  players_fault.txt C  (P2 · P5 · P7 · P8에 고장이 붙는다)
  Run D: 로컬에서 Crasher를 먼저 실행한 뒤 Server, Player 순서로 실행한다.

    python src/crasher.py --port 9700 --run D --out logs
    python3 src/server.py --port 9000 --seed 2026 --tables 4 --timeout 3000 --run D --out ./run_D   (EC2)
    python src/run_players.py 13.61.180.113 9000 config/players_std.txt D --crasher 127.0.0.1:9700 --out logs

6-3. 결과 모으기

    scp -i "$Ec2Key" "ubuntu@${Ec2Ip}:~/hw5/run_B/*" ./run_B/
    copy logs\RunB_P*.txt run_B\              (Run D는 logs\RunD_Crasher.txt도)

  run_A ~ run_C는 14개, run_D는 15개 파일이 된다.

6-4. 검증

  tools 폴더에서 실행한다 (check_chaos와 make_compare는 같은 폴더의 verify_league를 부른다).
  Windows에서는 한글 출력 때문에 UTF-8 모드로 실행한다.

    cd tools
    $env:PYTHONUTF8 = "1"
    python verify_league.py ../run_A
    python check_chaos.py ../run_A ../run_D
    python make_compare.py 9 ../run_A ../run_B ../run_C ../run_D

7. 로컬 실행 및 테스트
================================================================================


7-1. bot 단위 테스트

  kit 1_bot_test_kit/python 폴더의 mybots.py를 src/mybots.py로 바꾼 뒤 실행한다.

    python bot_test.py            → 마지막 줄 ALL PASS
    python strategy_arena.py      → 5 x 5 상성표 (TEAM 설계용)

7-2. 샘플 설정으로 정답 hash 확인

  P9 · P10 = RANDOM인 샘플 설정으로 돌리면 3_sample과 같은 hash가 나와야 한다.

    python src/run_local.py A out_sample --config config/players_sample.txt
    → results_hash=cfde2bce standings_hash=c8a0c732 -> PASS (일치 확인)

7-3. 로컬 전체 테스트

    python src/test_all.py out_test          (Run A · B · C · D + verify + check_chaos)

  모두 로컬에서 실행하면 경기 하나가 약 0.22초로 끝난다. 이 경우 Crasher가 C5 규칙(0~0.3초
  대기)으로 기다리는 사이에 경기가 끝나 버려 계획한 사건을 모두 내지 못하는 경우가 있었다
  (12번 중 2번). 원격에서는 경기 하나가 약 6.7초이므로 이 문제가 없다(11-3 참고).

8. 주요 구현 내용
================================================================================


8-1. 결정적 난수와 bot

  seed_of(text) = SHA-256(text)의 16진수 앞 8자리 mod 2^31, LCG는
  x = (1103515245 x + 12345) mod 2^31, next() = x >> 16. 상금 순서는 LCG("S:mid")로
  Fisher-Yates(i = 9 down to 1), RANDOM은 LCG("S:mid:k")로 매 판 next() 한 번, TEAM은
  LCG("S:mid:k:TEAM") 하나만 쓴다. Bot은 경기마다 새로 만든다. kit bot_test 전 항목
  PASS(SEED · LCG · PRIZE · BOT · MATCH · LEAGUE).

8-2. Server — Thread, Lock, Condition 설계

  Server에는 Main Thread 1개와 Table Thread M개가 있다. 경기마다, Player마다 Thread를
  만들지 않는다.

  - Main: listen → HELLO 10개 확인 → WELCOME → START 45 → Table M개 생성 →
    while finished < 45: done_cv.wait() → join → (Lock 밖) results · standings · match_log
    저장, SAVE(hash) → LEAGUE_END · BYE → 지표(STAT) → TERMINATE
  - Table: Lock → pick() (없으면 lobby_cv.wait()) → 두 선수 busy · PLAYING, assigned += 1
    → Unlock → play_match (Lock 밖에서 send · recv) → Lock → 결과 기록, 두 선수 IDLE
    (DEAD는 유지), finished += 1, lobby_cv.notify_all(), finished == 45면 done_cv.notify()
    → Unlock. assigned == 45가 되면 TABLE exit 로그를 남기고 끝난다.

  Mutex m 하나로 Player 상태(IDLE · PLAYING · DEAD, busy), 경기 상태(PENDING · PLAYING ·
  DONE), assigned · finished, result · match_log 줄, 지표 합계를 보호한다. Condition 두 개
  (lobby_cv: Table ↔ Table, done_cv: Table → Main)는 같은 m에 연결한다. wait()는 while
  조건으로 감싸 깨어난 뒤에도 조건을 다시 확인한다. busy-wait은 없다.

  pick()은 PENDING이고 두 선수 모두 경기 중이 아닌 경기 중 무작위 하나를 고른다. 그래서
  경기를 치르는 순서는 실행마다 다르지만, results는 mid 순서, standings는 순위 순서로
  저장하므로 테이블 수와 관계없이 바이트 단위로 같다(Run A = Run B).

  DEAD(QUIT한) 선수도 '경기 중 아님'으로 보아 남은 경기를 바로 배정하지만, 그 부전패를
  처리하는 동안에는 busy로 두어 같은 선수의 경기 시간이 겹치지 않게 했다(verify overlap 0).

  Socket 소유권: Player가 PLAYING인 동안 그 경기의 Table Thread만 그 소켓을 읽고 쓴다.
  TCP는 메시지 경계를 보장하지 않으므로 수신 버퍼에 쌓은 뒤 LF 단위로 자르며, 이 버퍼는
  Player 객체에 붙어 있어 테이블이 바뀌어도 이어서 읽힌다. Lock을 잡은 채 send · recv ·
  파일 저장을 하지 않는다. 로그 파일은 Lobby Mutex와 별개인 로그 전용 Lock으로 한 줄씩
  append한다. 작은 메시지가 지연되지 않도록 TCP_NODELAY를 켰다.

8-3. timeout · 몰수 · stale · 부전패

  ROUND · COMMITS · MATCH_END를 보낼 때 deadline = now + 3초를 정한다. wait_for()는
  select로 남은 시간만큼 기다리고, 마감이 지나도 이미 도착한 줄은 읽는다(A를 먼저
  기다리느라 B의 줄을 놓치지 않는다).

  - COMMIT: 마감 초과 TIMEOUT, 형식(토큰 4개, hash 64자 16진수) 오류 BAD_MSG,
    QUIT → DISCONNECT(+DEAD)
  - REVEAL: 형식(토큰 5개, 정수 카드, nonce 16자 16진수) 오류 BAD_MSG,
    sha256("card:nonce") ≠ COMMIT hash면 BAD_HASH, 손에 없는 카드면 BAD_CARD
  - 몰수: 위반 선수 0 : 55 (두 선수 모두면 FORFEIT_BOTH 0 : 0, 사유A+사유B).
    match_log에 F mid r WHO REASON, 두 선수에게 FORFEIT → MATCH_END
  - CONFIRM: 마감 안에 같은 점수면 OK, 다르면 DISPUTE, 안 오면 NO, DEAD · QUIT이면 -
  - stale: 기다리는 종류 · mid · r과 다른 줄은 STALE 로그 후 버린다. REJOIN은 기다리던
    줄이 아니므로 REJOIN 로그만 남기고 계속 기다린다.
  - QUIT(가상 끊김): 그 경기 DISCONNECT 몰수, 선수 DEAD. 이후 그 선수의 경기는 살아 있는
    상대에게 MATCH · ROUND mid 1 p를 보내 1판 COMMIT으로 출석을 확인한 뒤
    F mid 0 WHO DISCONNECT(부전패). 상대도 응답이 없으면(crash 중) F mid 0 BOTH
    TIMEOUT+DISCONNECT, 두 선수 모두 DEAD면 F mid 0 BOTH DISCONNECT. DEAD 선수에게는
    아무것도 보내지 않고 마지막에 BYE만 보낸다.

8-4. Player — Thread 구성

  - main Thread: Server 소켓을 50ms recv timeout으로 읽는다(줄이 없어도 주기적으로 mode
    확인). MATCH → 새 Bot, ROUND → think 18~22ms 후 COMMIT(sha256("card:nonce"),
    nonce = secrets 8바이트), COMMITS → REVEAL, REVEALS → 상대 hash · 판정 · 누적 점수를
    직접 확인(틀리면 VERIFY FAIL), MATCH_END → 자기가 계산한 점수(몰수면 기록 점수)로
    CONFIRM, LEAGUE_END · BYE → TERMINATE
  - 제어 Thread (Run D): Crasher 연결만 읽어 CRASH · QUIT · RESTART를 공유 mode에 반영
  - mode ∈ {IDLE, PLAYING, CRASHED, RESTARTING, QUIT}, pending, mid, last_r, last_kind를
    Mutex st로 보호한다. Server로 보내는 모든 줄은 st 안에서 "mode == PLAYING이고 같은
    경기인지" 확인과 함께 보낸다 → think 중에 crash를 받아도 COMMIT이 새어 나가지 않는다.
    CONFIRM 송신과 IDLE 전환도 같은 Lock 안에서 한다.
  - CRASHED · QUIT 중에는 Server 줄을 계속 읽어서 버린다(BYE만 처리). RESTART를 받으면
    main loop가 버퍼를 비우고 REJOIN Pk, STATE IDLE을 보낸 뒤 다음 MATCH부터 새 Bot으로
    참여한다. Bot이 없는 경기의 줄은 무시한다.
  - IDLE에서 받은 CRASH · QUIT은 pending으로 기억(INFO)했다가 다음 MATCH를 받는 순간
    적용(WARN, r=0 last=-)한다.
  - Run C 고장(--fault kind@mid,r): slow = 그 판 ROUND 뒤 (timeout+1)초 잠든 뒤 정상 COMMIT,
    badcard = 카드 11을 COMMIT · REVEAL, badhash = COMMIT한 카드와 다른 카드(c mod 10 + 1)를
    REVEAL, quit = COMMIT 대신 QUIT mid 후 BYE까지 모두 무시(TCP 유지).

8-5. Crasher (C1 ~ C8)

  C1 --port --run D --out [--seed]. seed는 PLAN 줄에 기록하며, 같은 seed면 같은 계획이다.
  C2 사건 수 F = 4~7, quit 수 Q = 1~2, 나머지 crash. 종류 순서는 shuffle.
  C3 발생 시점 = "끝난 경기 수" 2~30 중 F개 (끝난 경기 수 ≈ STATE PLAYING→IDLE 횟수 ÷ 2).
  C4 대상 = 지금 PLAYING이고, 자신도 상대(pairs[mid])도 장애 중(crash 중 · quit · 명령
     대기 · 복귀 후 첫 경기)이 아닌 선수 중 무작위.
  C5 고른 뒤 0~0.3초 기다리고, Lock 안에서 조건을 다시 확인한 뒤 명령을 보낸다
     (바뀌었으면 다시 고름).
  C6 STATE CRASHED를 받은 때부터 4.05~4.9초 뒤 RESTART (crash마다 타이머 Thread).
  C7 quit 선수는 끝까지 장애 목록에 남는다.
  C8 10명 모두 STATE END → SUMMARY · TERMINATE. Server와는 통신하지 않는다.

  Thread: 수신 Thread x 10(STATE 읽기), 이벤트 Thread(main, 시점이 올 때까지 CV wait),
  crash마다 타이머 Thread. 공유 상태(state · mid_of · faulty · cooldown · ends)는 Mutex 하나와
  Condition Variable 하나로 보호한다.

8-6. 통신 형식

  모든 메시지는 공백으로 구분한 ASCII 한 줄이며 줄 끝은 LF이다. mid · r은 앞에 0을 붙이지
  않는다(MATCH 5 A P7). 로그 · match_log에서만 2자리(G05, 05)로 쓴다.

    P->S  HELLO Pk STRATEGY | COMMIT mid r hash | REVEAL mid r card nonce |
          CONFIRM mid sA:sB | QUIT mid | REJOIN Pk
    S->P  WELCOME Pk seed timeout_ms | START 45 | MATCH mid side Popp | ROUND mid r prize |
          COMMITS mid r hA hB | REVEALS mid r cA nA cB nB winner sA sB |
          FORFEIT mid who reason | MATCH_END mid outcome sA sB | LEAGUE_END rank pts | BYE
    P->C  CTRL Pk | STATE Pk PLAYING mid | STATE Pk IDLE | STATE Pk CRASHED mid |
          STATE Pk QUIT | STATE Pk END
    C->P  CRASH | RESTART | QUIT

8-7. 결과 파일

  RunX_results.txt (45줄, mid 순서), RunX_standings.txt (10줄, 승점 → 득실차 → 득점 → 번호),
  RunX_match_log.txt (LEAGUE / MATCH / R / F / END), RunX_League.txt (Server 로그),
  RunX_P1~P10.txt (Player 로그), RunD_Crasher.txt. 모두 LF, hash는 SHA-256 앞 8자리.

9. TEAM 전략 (P9 · P10)
================================================================================


  규칙 (상대가 누구든 같은 하나의 규칙. choose()는 상대 번호 · 상대 전략 · A/B 자리 ·
  경기 번호를 받지 않는다. S · mid · k는 LCG 이름표에만 쓴다.)

  1) 이번 경기에서 이미 공개된 상대 카드가 다음 세 가지 단순 반응 규칙 중 어느 것과
     지금까지 모두 맞는지 확인한다. 상대 손패는 공개된 카드로 정확히 안다.
       (가) 상금과 같은 카드   (나) 상금보다 큰 카드 중 가장 작은 것
       (다) 상금 6 이상이면 가장 큰 카드, 아니면 가장 작은 카드
     1판(기록 없음)은 세 규칙을 모두 후보로 둔다.
  2) 맞는 규칙이 있으면, 그 규칙들이 예측한 상대 카드 각각에 대해 내 손패의 카드마다
     (이번 판 기대 득실) - (그 카드의 미래 가치)를 계산해 가장 큰 카드를 낸다.
     미래 가치 = 카드의 손패 내 순위에 대응하는 남은 상금 x 1.3 (큰 카드일수록 비쌈).
     동점이면 LCG("S:mid:k:TEAM")로 하나를 고른다.
  3) 맞는 규칙이 하나도 없으면(예측 불가), 상금의 순위를 손패 순위로 옮긴 카드를 내고,
     상금이 5 이상이면 한 칸 높은 카드를 낸다.

  의도: 상대가 이번 경기에서 보여 준 카드에만 반응한다. 예측이 맞으면 "이기는 가장 작은
  카드"나 "버리는 가장 작은 카드"를 고르게 되어 큰 카드를 아낀다. 1.3은 strategy_arena로
  0.3 ~ 1.3을 비교해 정했다(0.5일 때 BIGSMALL 상대 승률 57% → 1.3일 때 99%).

  상성표 (strategy_arena.py, 1,000경기씩, 승/무/패 %, 행 = A, 열 = B)

  A \ B        RANDOM     MATCH      PLUS1      BIGSMALL   TEAM
  RANDOM       46/ 2/52   4/ 0/95   19/ 1/80   14/ 1/85   10/ 1/89
  MATCH        94/ 1/ 6   0/100/0    0/ 0/100  80/ 3/17    1/ 0/99
  PLUS1        78/ 2/20  100/ 0/0    0/100/0   78/ 4/18    0/ 0/100
  BIGSMALL     85/ 1/14   17/ 3/80   18/ 4/78   0/100/0    1/ 0/99
  TEAM         88/ 1/11   99/ 0/ 0  100/ 0/0   99/ 0/ 1    0/100/0

  TEAM은 결정적인 세 전략(MATCH · PLUS1 · BIGSMALL)에 99~100% 이기고, 예측할 수 없는
  RANDOM에 가장 약하다(88%). TEAM끼리는 같은 규칙이므로 항상 비긴다(0 : 0).
  정식 리그(Run A · B)에서 P9 · P10은 16경기 모두 이기고 둘끼리 비겨 8승 1무 0패, 공동 1위다.

10. 로그 확인
================================================================================


  공통 형식: [HH:MM:SS.mmm] NODE | EVENT | STATUS | message (KST). 모든 메시지와 필수 줄은
  AllDefinedLogs.txt에 정리했다. 로그만으로 INIT → CONNECT → START → MATCH → RESULT →
  (FORFEIT · DISCONN · STALE · REJOIN) → TABLE → SAVE → STAT → TERMINATE 흐름을 추적할 수
  있다. 매 판은 로그가 아니라 match_log의 R 줄에 남긴다.

  예 (run_C/RunC_League.txt, slow 고장)
    [14:11:..] SERVER | FORFEIT   | WARN    | G11 P2 vs P5 round=4 forfeit=A reason=TIMEOUT
    [14:11:..] SERVER | STALE     | WARN    | P2 dropped 'COMMIT 11 4 ca1f...' (waiting CONFIRM 11)
    [14:11:..] SERVER | RESULT    | SUCCESS | G11 P2 0:55 P5 FORFEIT_A confirm=OK/OK 6357ms

11. 발견한 문제와 수정 내용
================================================================================


11-1. 원격 Run D에서 crash 복귀 직후 QUIT이 겹친 문제 (Crasher)

  첫 정식 Run D에서 check_chaos가 FAIL이었다. P8이 G39의 CONFIRM 단계에서 crash했고, 그사이
  Server는 P8을 G32에 배정했다. P8의 REJOIN은 Server가 G32의 1판 COMMIT을 기다리는 중에
  도착했으므로 G32까지가 crash 구간이 된다. 그런데 Crasher는 STATE IDLE(복귀)을 받자마자
  P8을 장애 목록에서 빼서 G32에서 다시 QUIT을 보냈다. 그래서 같은 경기에 crash 구간과 quit이
  겹쳤다. 복귀한 선수는 "복귀 후 첫 경기를 끝낼 때까지" 장애 중(cooldown)으로 두어 그 선수와
  상대에게 새 명령을 보내지 않도록 고쳤다. 수정 후 원격 Run D를 3번 연속 실행해 모두
  CHAOS D -> PASS였다.

11-2. ssh로 원격 Server를 띄우면 스크립트가 멈춘 문제

  "cd ~/hw5 && ... && nohup python3 server.py ... &"는 && 목록 전체가 백그라운드 subshell이
  되어 ssh 채널을 붙잡았다. 서버 실행만 (setsid nohup ... < /dev/null &)로 분리하고 ssh -n을
  썼다. 또 pkill -f 'src/server.py'가 그 명령을 실행하는 bash 자신과도 일치해 ssh가 바로 끊겼다.
  패턴을 '^python3 src/server.py'로 고정했다.

11-3. 로컬에서만 Run D 사건이 모자란 문제

  모두 로컬에서 실행하면 경기가 약 0.22초라, Crasher가 C5 규칙(0~0.3초 대기) 동안 고른 경기가
  끝나 다시 고르기를 반복했다. 늦은 시점(23~29경기)의 사건은 리그가 끝날 때까지 다 나가지
  못했다(로컬 12번 중 2번 FAIL). 같은 Crasher seed를 원격 Server로 실행하면 경기가 약 6.7초라
  모두 PASS였다. 규칙(C5)은 그대로 두었다.

11-4. DEAD 선수의 부전패가 겹칠 수 있는 문제

  명세대로 DEAD 선수를 '경기 중 아님'으로만 보면, 테이블 4개가 같은 DEAD 선수의 부전패 경기를
  동시에 처리해 verify의 overlap 검사에 걸릴 수 있다. 부전패를 처리하는 동안 busy 표시를 두어
  한 번에 하나씩 처리하도록 했다.

11-5. Windows 콘솔에서 검증 도구 출력이 깨진 문제

  make_compare · check_chaos가 하위 프로세스 출력을 cp949로 읽어 UnicodeDecodeError가 났다.
  PYTHONUTF8=1(UTF-8 모드)로 실행하면 해결된다(6-4).

12. 실행 중 문제가 생긴 경우
================================================================================


League Server에 연결되지 않을 때

  Server가 먼저 실행되었는지, IP와 포트(9000)가 맞는지 확인한다. EC2를 다시 시작했다면
  공인 IP가 바뀌었을 수 있다. 보안 그룹의 TCP 9000번 규칙도 확인한다.

Address already in use가 나올 때

  이전 Server(또는 HW#4 Assigner)가 아직 9000번 포트를 쓰고 있는지 확인한다.
    ssh -i "$Ec2Key" "ubuntu@$Ec2Ip" "pkill -f '^python3 src/server.py'"

Player가 접속 후 끝나지 않을 때

  10명이 모두 접속해야 START가 나간다. 설정 파일이 10줄인지 확인한다. Run D는 Crasher를
  먼저 실행해야 Player가 CTRL 연결을 할 수 있다.

hash가 Run A와 다를 때

  서버와 로컬의 mybots.py가 같은 버전인지 확인한다. TEAM 전략을 고쳤다면 Run A부터 다시
  실행한다.

13. 제출 파일과 원격 실행 결과
================================================================================

13-1. 제출 파일 (G9HW5.zip)

  src/: server · player · crasher 소스와 실행 스크립트
  config/, tools/: kit 설정 파일과 검증 도구 (수정 없음)
  run_A/ ~ run_C/ (14개씩), run_D/ (15개): 원격 구성의 정식 실행 결과
  compare_result.txt, AllDefinedLogs.txt, download.txt, Readme.txt

  SSH 키 파일은 제출 ZIP에 넣지 않는다.

13-2. 실행 목록 (2026-11-21, 하나씩 순서대로 실행)

  Run A: 원격 Server, 테이블 1개
  Run B: 원격 Server, 테이블 4개
  Run C: 원격 Server, 테이블 4개, players_fault.txt (고장 4건)
  Run D: 원격 Server, 테이블 4개, 로컬 Crasher (seed 571607)

13-3. compare_result.txt

  RUN  TABLES  RESULTS   STANDINGS  VERIFY
  A    1       7e735e61  4e31bede   PASS
  B    4       7e735e61  4e31bede   PASS
  C    4       680279a8  360fd52e   PASS
  D    4       0740d6bd  5eef8361   PASS
  A=B  SAME -> PASS
  CHAOS D  장애 사건 5 (crash 3, quit 2) = 11.1% | 영향 경기 6 + 부전패 4 | 정상 경기 35 (= Run A) -> PASS

13-4. 성능 지표 (Server 최종 STAT 로그)

  표 1. Run별 실측값
  지표                               | Run A   | Run B   | Run C   | Run D
  총 실행시간 (START ~ 45번째 종료, 초)|  303.35 |   79.84 |   66.68 |   81.75
  경기 시간 평균 (초)                 |   6.741 |   6.670 |   5.608 |   6.003
  경기 시간 최대 / 최소 (초)          | 6.965 / 6.386 | 6.864 / 6.422 | 7.121 / 0.619 | 9.411 / 0.624
  평균 동시 경기 수                   |    1.00 |    3.76 |    3.78 |    3.30
  판 응답 지연 평균 / 최대 (ms)       | 331.7 / 343.8 | 328.4 / 339.5 | 333.8 / 357.3 | 330.6 / 413.6
  CONFIRM OK / NO / DISPUTE / -       | 90/0/0/0 | 90/0/0/0 | 82/0/0/8 | 80/4/0/6
  몰수 (사유별)                       | 없음    | 없음    | TIMEOUT 1, BAD_CARD 1, BAD_HASH 1, DISCONNECT 1, 부전패 7 | TIMEOUT 3, DISCONNECT 2, 부전패 4
  STALE / REJOIN                      | 0 / 0   | 0 / 0   | 1 / 0   | 0 / 3

  표 2. 테이블별 (경기 수, 가동률 = 경기 시간 합 ÷ 총 실행시간, Lobby 대기 = lobby_cv 대기 합)
  Run A: Table1 45경기 100%, 대기 0.00s
  Run B: Table1 10경기 84% 6.33s / Table2 11경기 92% 0.00s / Table3 12경기 100% 0.00s /
         Table4 12경기 100% 0.00s
  Run C: Table1 11경기 88% 1.24s / Table2 11경기 100% 0.00s / Table3 10경기 93% 3.59s /
         Table4 13경기 98% 1.09s
  Run D: Table1 13경기 100% 0.01s / Table2 11경기 77% 12.24s / Table3 10경기 77% 12.10s /
         Table4 11경기 76% 12.93s

  표 3. 전략별 성적 (Run A = Run B, 승/무/패 합계와 경기당 평균 득점)
  RANDOM(P1 · P2) W3 D0 L15 평균 18.3 / MATCH(P3 · P4) W5 D2 L11 평균 17.6 /
  PLUS1(P5 · P6) W12 D2 L4 평균 28.4 / BIGSMALL(P7 · P8) W5 D2 L11 평균 15.9 /
  TEAM(P9 · P10) W16 D2 L0 평균 32.9

  Run A 순위: 1 P9, 2 P10 (8승 1무 승점 25), 3 P5, 4 P6 (승점 19), 5 P3, 6 P8, 7 P4, 8 P7,
  9 P2, 10 P1

13-5. 분석

  ① M = 1과 M = 4의 총 시간 비: 303.35 / 79.84 = 3.80배. 4배가 아닌 이유는 끝부분(tail)
     때문이다. 마지막에 남은 경기들의 선수가 겹치면 테이블이 놀 수밖에 없다. 한 선수가
     9경기를 연속으로 치러야 하므로 하한은 약 9 x 6.7s ≈ 60s이다. 평균 동시 경기 수는
     3.76이었다.
  ② 가동률이 낮은 테이블: Run B의 Table1(84%, Lobby 대기 6.33s)은 리그 끝부분에서 남은
     경기의 두 선수가 다른 테이블에서 경기 중이라 고를 경기가 없어 기다렸다.
  ③ 판 응답 지연(ROUND 송신 ~ COMMIT 두 개 도착): 원격 평균 약 330ms, 로컬(같은 PC) 평균
     21.3ms. think(약 20ms)를 빼면 원격의 송수신 시간은 약 310ms이다. 이는 측정한 TCP RTT
     (300~325ms)와 같다. 로컬의 송수신 시간은 약 1ms이다. 경기 하나(10판)는 판마다 ROUND →
     COMMIT, COMMITS → REVEAL 두 번의 왕복이 필요하므로 약 6.7초가 걸린다.
  ④ TEAM은 MATCH · PLUS1 · BIGSMALL처럼 상금에만 반응하는 결정적 전략에 강하다(99~100%).
     2~3판이면 상대 규칙이 드러나 매 판 이기는 가장 작은 카드를 고르기 때문이다. RANDOM에는
     상대적으로 약하다(88%). TEAM끼리는 항상 0 : 0 무승부이다.
  ⑤ Run D 분석은 14항.

  정합성 확인 (9-4)
  1) 네 Run 모두 verify_league: files 14/14(D 15/15), matches 45/45, round-errors 0,
     overlap 0, results · standings MATCH -> PASS
  2) Run A와 Run B의 results(7e735e61) · standings(4e31bede) hash가 같다 → A=B SAME -> PASS.
     같은 코드의 로컬 실행에서도 같은 hash였다. 샘플 설정(P9 · P10 = RANDOM)으로는
     정답 cfde2bce · c8a0c732와 일치했다.
  3) Run A · B: 모든 RESULT confirm=OK/OK (90/90), Player 로그 VERIFY FAIL 0건
  4) Run C: 고장 4건이 정해진 판 · 사유로 처리되었다 — G11 r4 P2 TIMEOUT(0:55, 늦은 COMMIT은
     STALE), G21 r6 P8 DISCONNECT(55:0, P8 DEAD), G30 r7 P5 BAD_CARD(0:55),
     G40 r3 P7 BAD_HASH(0:55). P8의 나머지 경기 7개는 판 0 부전패, P8은 0승 9패 득점 6,
     실점 480. 고장을 낸 P2 · P5 · P7은 그 경기 하나만 몰수패했다. RunC_P8.txt 마지막 줄은
     TERMINATE | WARN | left at G21.
  5) Run D: check_chaos.py run_A run_D → CHAOS D -> PASS (14항)
  6) 끝까지 치른 Player의 TERMINATE 줄(rank · pts · W · D · L) = standings의 그 줄
     (Run A · B 10명 모두 일치 확인)

14. Run D 분석
================================================================================


  PLAN: seed=571607 events=5 (crash 3, quit 2), 시점(끝난 경기 수) = 8, 23, 25, 26, 30

  표 4. 장애 사건
  #  종류   대상 · 경기       Player 로그 (적용 시점)     Server 결과
  1  CRASH  P1 · G03          r=1 last=COMMIT            G03 r1 TIMEOUT 0:55, confirm=NO/OK, 6.34s
                                                         RESTART 4.48s → REJOIN (waiting CONFIRM 3)
  2  CRASH  P2 · G11          r=2 last=REVEAL            G11 r3 TIMEOUT 0:55, confirm=NO/OK, 7.30s
                                                         RESTART 4.33s → REJOIN (waiting CONFIRM 11)
  3  CRASH  P4 · G02          r=10 last=REVEAL           G02 결과 정상(=Run A), confirm=OK/NO, 9.41s
     (CONFIRM 단계)                                      crash가 다음 경기까지 이어져 G26 r1 TIMEOUT,
                                                         RESTART 4.29s → REJOIN (waiting COMMIT 26 1)
  4  QUIT   P3 · G23          r=1 last=REVEAL            G23 r2 DISCONNECT, P3 DEAD →
                                                         G18 · G20 부전패 (판 0)
  5  QUIT   P1 · G04          r=3 last=COMMIT            G04 r3 DISCONNECT, P1 DEAD →
                                                         G07 · G08 부전패 (판 0)

  check_chaos: 장애 사건 5건(crash 3, quit 2), crash마다 RESTART 3/3(4.29~4.48s), 영향 경기 6 +
  부전패 4, 장애와 무관한 35경기 = Run A 결과, 설명되지 않는 몰수 0건, 상대가 장애 중인
  선수에게 보낸 명령 0건, crash 선수의 복귀 뒤 첫 경기 정상 → CHAOS D -> PASS.

  crash당 추가 시간: 정상 경기는 약 6.7초다. 판 중간 crash(G03 · G11 · G26)는 3초 마감 →
  몰수 → CONFIRM 3초 마감으로 6.0~7.3초가 걸려, 남은 판을 치르지 않는 만큼 경기 하나로는
  비슷하다. CONFIRM 단계 crash(G02)는 10판을 다 치른 뒤 CONFIRM 3초를 더 기다려 9.4초
  (+약 2.7초)였다. 리그 전체로는 Run B 79.84초 → Run D 81.75초(+1.9초)였다. 부전패(약
  0.6초)가 시간을 줄였지만 끝부분에서 테이블 3개가 각 12초 이상 Lobby에서 기다렸다.
  quit 선수의 남은 경기가 남은 선수들에게 몰리면서 tail이 길어졌기 때문이다.

  Player 제어 Thread 설계는 8-4, Crasher는 8-5 참고.

15. 구현 한계 · 추가 구현 · 느낀 점
================================================================================


  구현 한계
  - 실제 TCP 끊김은 DEAD로 처리하지만 재접속은 지원하지 않는다(과제 범위 밖).
  - 로컬에서만 실행하면 경기가 너무 짧아 Crasher가 계획한 사건을 다 내지 못할 수 있다(11-3).
  - Crasher가 IDLE 직전에 보낸 명령이 그 선수의 마지막 경기 뒤라면 적용되지 못할 수 있다
    (실행에서는 발생하지 않았다).

  추가 구현
  - run_remote.py로 원격 Run 하나를 명령 한 줄로 실행 · 수집한다.
  - Server 종료 직전 9-5 지표(테이블별 가동률, 판 응답 지연, 전략별 성적 등)를 STAT 로그로
    남긴다.
  - test_all.py로 네 Run과 verify · check_chaos · confirm · VERIFY FAIL 검사를 한 번에 한다.

  느낀 점
  - 테이블 수와 관계없이 hash가 같으려면 경기 순서에 의존하는 상태가 없어야 한다. 난수를
    "S:mid:k" 이름표로 경기마다 새로 만드는 이유를 직접 확인했다.
  - 원격 실행에서 판 응답 지연 약 330ms 중 think는 20ms뿐이고 나머지는 네트워크 왕복이었다. 테이블을
    늘리는 동시 처리가 실제 시간을 3.8배 줄였다.
  - crash · REJOIN · 다음 경기 배정이 겹치는 경합은 로컬 테스트에서는 드러나지 않고 원격
    지연 환경에서만 나타났다. 여러 번 반복 실행하는 검증이 꼭 필요하다는 것을 배웠다.
