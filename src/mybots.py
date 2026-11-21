# mybots.py — 결정적 난수(seed_of · LCG · prize_order)와 bot 전략 (HW5 §3 · §4)
# Server · Player · bot_test · strategy_arena 가 모두 이 파일을 쓴다.
import hashlib

M31 = 2 ** 31
PAIRS = [(a, b) for a in range(1, 11) for b in range(a + 1, 11)]      # PAIRS[mid] = (A, B)
STRATEGIES = ("RANDOM", "MATCH", "PLUS1", "BIGSMALL", "TEAM")


def seed_of(text):
    """SHA-256(text) 16진수 앞 8자리 → 정수 mod 2^31"""
    return int(hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:8], 16) % M31


class LCG:
    """x <- (1103515245·x + 12345) mod 2^31, next() = x >> 16 (0 ~ 32767). 문자열이면 seed_of를 거친다."""
    def __init__(self, seed):
        self.x = (seed_of(seed) if isinstance(seed, str) else int(seed)) % M31

    def next(self):
        self.x = (1103515245 * self.x + 12345) % M31
        return self.x >> 16


def prize_order(S, mid):
    """경기 mid의 상금 순서 (Fisher–Yates, i = 9 down to 1)"""
    g = LCG(seed_of(f"{S}:{mid}"))
    a = list(range(1, 11))
    for i in range(9, 0, -1):
        j = g.next() % (i + 1)
        a[i], a[j] = a[j], a[i]
    return a


# ---------------------------------------------------------------------------------------------
# 표준 전략 (모든 조 동일) — hand는 항상 오름차순
def _plus1(p, hand):
    for c in hand:
        if c > p:
            return c
    return hand[0]


def _bigsmall(p, hand):
    return hand[-1] if p >= 6 else hand[0]


def _match(p, hand):
    return p          # MATCH는 손에 상금과 같은 카드가 항상 있다 (상금 1~10이 한 번씩)


# ---------------------------------------------------------------------------------------------
# TEAM 전략 — 상대를 구별하지 않는 하나의 규칙 (Readme 참고)
#  받는 것: 이번 상금 p, 판 r, 내 손패 hand, 이번 경기 기록 history[(r, p, 내 카드, 상대 카드)],
#          남은 상금 prizes_left(이번 판 제외), rng = LCG("S:mid:k:TEAM")
#  규칙:
#   1) 이번 경기에서 공개된 상대 카드가 "상금과 같은 카드", "상금보다 큰 가장 작은 카드",
#      "큰 상금엔 최대·작은 상금엔 최소" 중 어느 단순 반응 규칙과 지금까지 모두 맞는지 본다
#      (상대 손패는 공개된 카드로 정확히 안다). 맞는 규칙이 하나도 없으면 '예측 불가'.
#   2) 1판(기록 없음)은 세 반응 규칙을 모두 후보로 둔다.
#   3) 후보 규칙들이 예측한 상대 카드 집합 Q에 대해, 손패에서 카드를 하나씩 놓고
#      (상금 획득 기대값) − (그 카드를 써서 잃는 미래 가치)를 계산해 가장 좋은 카드를 낸다.
#      미래 가치 = 카드의 손패 내 순위에 대응하는 남은 상금 × 1.3 (큰 카드일수록 비쌈, arena로 1.3 선택).
#   4) 예측 불가이면 상금의 순위를 손패 순위로 옮긴 카드를 내고, 상금이 5 이상이면 한 칸 높은 카드를 낸다.
#  rng는 동점인 후보 카드 중 하나를 고를 때만 쓴다.
def _opp_hand(history):
    used = {h[3] for h in history}
    return [c for c in range(1, 11) if c not in used]


def _consistent_models(history):
    """이번 경기 기록과 모순 없는 상대 반응 규칙 목록"""
    models = []
    for name, f in (("MATCH", _match), ("PLUS1", _plus1), ("BIGSMALL", _bigsmall)):
        oh = list(range(1, 11))
        ok = True
        for (_, p, _, oc) in history:
            if oc == 0 or f(p, oh) != oc:
                ok = False
                break
            oh.remove(oc)
        if ok:
            models.append(f)
    return models


def _future_value(card, hand, prizes_left):
    """card를 지금 쓰면 잃는 미래 가치: 손패에서의 순위를 남은 상금 순위로 옮긴 값 × 1.3"""
    if not prizes_left:
        return 0.0
    i = hand.index(card)
    pl = sorted(prizes_left)
    j = round(i * (len(pl) - 1) / max(1, len(hand) - 1))
    return pl[j] * 1.3


def team_choose(p, r, hand, history, prizes_left, rng):
    oh = _opp_hand(history)
    models = _consistent_models(history)
    if models:
        preds = [f(p, oh) for f in models]
        best, best_v = [], None
        for c in hand:
            gain = sum((p if c > q else (-p if c < q else 0)) for q in preds) / len(preds)
            v = gain - _future_value(c, hand, prizes_left)
            if best_v is None or v > best_v + 1e-9:
                best, best_v = [c], v
            elif abs(v - best_v) <= 1e-9:
                best.append(c)
        return best[rng.next() % len(best)] if len(best) > 1 else best[0]
    # 예측 불가: 상금 순위 → 손패 순위 + 1
    allp = sorted(list(prizes_left) + [p])
    k = allp.index(p)
    idx = round(k * (len(hand) - 1) / max(1, len(allp) - 1))
    if p >= 5:
        idx = min(len(hand) - 1, idx + 1)
    return hand[idx]


class Bot:
    """경기마다 새로 만든다. strategy = RANDOM · MATCH · PLUS1 · BIGSMALL · TEAM"""
    def __init__(self, strategy, S, mid, k):
        self.strategy, self.S, self.mid, self.k = strategy, S, mid, k
        self.hand = list(range(1, 11))
        self.history = []                  # (판, 상금, 내 카드, 상대 카드)
        self.g = LCG(seed_of(f"{S}:{mid}:{k}")) if strategy == "RANDOM" else None
        self.mix = LCG(seed_of(f"{S}:{mid}:{k}:TEAM")) if strategy == "TEAM" else None

    def choose(self, prize, r):
        s, h = self.strategy, self.hand
        if s == "RANDOM":
            return h[self.g.next() % len(h)]
        if s == "MATCH":
            return prize
        if s == "PLUS1":
            return _plus1(prize, h)
        if s == "BIGSMALL":
            return _bigsmall(prize, h)
        if s == "TEAM":
            seen = {x[1] for x in self.history} | {prize}
            left = [q for q in range(1, 11) if q not in seen]
            return team_choose(prize, r, list(h), list(self.history), left, self.mix)
        raise ValueError(s)

    def play(self, prize, r, my_card, opp_card):
        self.hand.remove(my_card)
        self.history.append((r, prize, my_card, opp_card))
