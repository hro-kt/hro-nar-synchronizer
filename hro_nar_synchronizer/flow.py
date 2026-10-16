"""flow_tan(地方版)。

スコア: レース内の単勝プール占有率 share_i = (1/odds_i) / Σ_j (1/odds_j) の
        logit 差 = logit(share_i @ late) − logit(share_i @ early)

★中央と**同じ数式**だが、基準時刻を意図的に変えている。
  中央: 発走時刻が締切なので「発走の lead 秒前」
  地方: 締切は**発走2分前**(SPAT4 の南関東のみ1分前)。発走基準で切ると、
        締切後に公表される確定オッズを掴む。それは賭けられない価格であり、
        使えば未来を見たことになる。基準は必ず**締切**。

★地方は更新が中央値31秒(中央は秒単位)。狙った時刻ちょうどの断面は無く、
  「その時刻以前で最も新しい断面」を使うことになる。実際のズレ(lag)は
  0〜60秒ばらつくので、**使った断面の時刻を必ず持ち回る**。
  窓の長さが日によって違うと絶対閾値が比較できなくなる(中央で踏んだ)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .tracks import deadline_sec


@dataclass(frozen=True)
class FlowConfig:
    # 締切の何秒前の断面を late にするか。★発走ではなく締切からの秒数。
    lead_sec: int = 60
    # late から何分さかのぼった断面を early にするか
    flow_min: int = 30
    # SPAT4 で買う前提か(南関東の締切が1分前になる)
    spat4: bool = False
    # late 断面がこれより古ければ使わない。★31秒刻みなので 0 にはできないが、
    #   古すぎる断面で「締切直前の情報」を名乗らせない。
    max_lag_sec: int = 90
    # 実際の窓がこの秒数以上ずれたら、同じ閾値で比較しない
    window_tolerance_sec: int = 120


def logit(x: float, lo: float = 1e-6) -> float:
    x = min(max(x, lo), 1.0 - lo)
    return math.log(x / (1.0 - x))


def shares(odds: dict[str, float]) -> dict[str, float]:
    """単勝オッズ → レース内の占有率。控除率は割るので消える。"""
    inv = {u: 1.0 / o for u, o in odds.items() if o and o > 0}
    tot = sum(inv.values())
    if tot <= 0:
        return {}
    return {u: v / tot for u, v in inv.items()}


def deadline_at(post_at: datetime, race_id: str, *, spat4: bool = False) -> datetime:
    return post_at - timedelta(seconds=deadline_sec(race_id, spat4=spat4))


def pick_snapshot(snapshots: list[tuple[datetime, dict[str, float]]],
                  at_or_before: datetime):
    """その時刻までに**実際に手に入っていた**最後の断面。

    ★「一番近い断面」ではない。未来の断面を掴んだら、それは手に入っていない情報。
    """
    usable = [s for s in snapshots if s[0] <= at_or_before]
    return usable[-1] if usable else None


def flow_scores(snapshots: list[tuple[datetime, dict[str, float]]],
                post_at: datetime, race_id: str,
                cfg: FlowConfig = FlowConfig()) -> dict:
    """{'scores': {馬番: {...}}, 'late_at','early_at','window_sec','lag_sec','skip'}。

    算出できないときは scores を空にし、**理由を skip に入れる**。
    ★0 を返してはいけない。「資金が動かなかった」と区別が付かなくなり、
      閾値の分位点が構造的ゼロで汚れる(中央で踏んだ)。
    """
    def _no(reason: str) -> dict:
        return {"scores": {}, "skip": reason, "late_at": None, "early_at": None,
                "window_sec": None, "lag_sec": None}

    snaps = sorted(snapshots, key=lambda s: s[0])
    dl = deadline_at(post_at, race_id, spat4=cfg.spat4)
    t_late_target = dl - timedelta(seconds=cfg.lead_sec)
    late = pick_snapshot(snaps, t_late_target)
    if late is None:
        return _no("late_なし")
    lag = (t_late_target - late[0]).total_seconds()
    if lag > cfg.max_lag_sec:
        return _no(f"late_が古い({lag:.0f}秒)")
    early = pick_snapshot(snaps, late[0] - timedelta(minutes=cfg.flow_min))
    if early is None:
        return _no("early_なし")
    if early[0] == late[0]:
        # ★同じ断面を指したら flow は測れていない。
        return _no("late_と_early_が同一断面")

    s_late, s_early = shares(late[1]), shares(early[1])
    if not s_late or not s_early:
        return _no("オッズなし")

    out: dict[str, dict] = {}
    for um, sl in s_late.items():
        se = s_early.get(um)
        if se is None:
            continue           # 途中から出走表に現れた馬は比較できない
        out[um] = {"score": logit(sl) - logit(se),
                   "share_late": sl, "share_early": se,
                   "tan_odds": late[1][um]}
    if not out:
        return _no("共通の馬がいない")

    assign_ninki(out)
    window = (late[0] - early[0]).total_seconds()
    return {"scores": out, "skip": None,
            "late_at": late[0], "early_at": early[0],
            "deadline_at": dl, "window_sec": window, "lag_sec": lag,
            # ★レース全体の値動き総量。雑音の水準。
            "move": sum(abs(d["share_late"] - d["share_early"]) for d in out.values()),
            "window_ok": abs(window - cfg.flow_min * 60) <= cfg.window_tolerance_sec}


def assign_ninki(scores: dict[str, dict]) -> None:
    """人気を**late の単勝オッズ順**から導出する。

    ★DB の人気欄を使わない。確定人気は締切後の情報で、使えば未来を見たことになる。
      定義を1つにしておかないと、backtest と実運用で別物になる。
    """
    order = sorted(scores.items(), key=lambda kv: kv[1]["tan_odds"])
    for i, (um, d) in enumerate(order, start=1):
        d["ninki"] = i


# --------------------------------------------------------------------------- #
# バックテスト。★数字を出すのは簡単だが、信じてよい数字を出すのは難しい。
#   ここで守るのは2つだけ: 締切後の情報を使わないこと、母数を誤魔化さないこと。
# --------------------------------------------------------------------------- #
@dataclass
class Bet:
    race_id: str
    kaisai_date: str
    umaban: str
    score: float
    ninki: int
    tan_odds: float          # 判断時点のオッズ(確定ではない)
    payout: int              # 100円あたり。外れは 0
    window_sec: float
    lag_sec: float


def summarize(bets: list[Bet], *, races: int, races_scored: int) -> dict:
    """ROI と内訳。★母数を必ず一緒に出す。点数だけ見ると判断を誤る。"""
    n = len(bets)
    staked = n * 100
    ret = sum(b.payout for b in bets)
    hits = sum(1 for b in bets if b.payout > 0)
    return {
        "races": races,                 # 対象レース数
        "races_scored": races_scored,   # スコアを算出できたレース数
        "bets": n,
        "staked": staked,
        "returned": ret,
        "roi": (ret / staked) if staked else None,
        "hit_rate": (hits / n) if n else None,
        "hits": hits,
        "avg_window_sec": (sum(b.window_sec for b in bets) / n) if n else None,
        "avg_lag_sec": (sum(b.lag_sec for b in bets) / n) if n else None,
    }


def select(scored: dict, *, min_score: float, ninki_from: int = 0,
           ninki_to: int = 99, max_per_race: int = 1) -> list[tuple[str, dict]]:
    """買う馬を選ぶ。スコア降順。"""
    cand = [(u, d) for u, d in scored.items()
            if d["score"] >= min_score and ninki_from <= d["ninki"] <= ninki_to]
    cand.sort(key=lambda kv: kv[1]["score"], reverse=True)
    return cand[:max_per_race] if max_per_race > 0 else cand


def group_snapshots(rows) -> list[tuple[datetime, dict[str, float]]]:
    """(observed_at, umaban, tan_odds) の並び → 時刻ごとの {馬番: オッズ}。"""
    by_t: dict[datetime, dict[str, float]] = {}
    for at, um, odds in rows:
        if odds is None:
            continue
        by_t.setdefault(at, {})[str(um)] = float(odds)
    return sorted(by_t.items(), key=lambda kv: kv[0])


def post_datetime(kaisai_date: str, post_time: str, tz) -> datetime | None:
    try:
        h, m = (int(x) for x in post_time.split(":"))
        d = kaisai_date
        return datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), h, m, tzinfo=tz)
    except (ValueError, IndexError, TypeError):
        return None


def backtest(store, d_from: str, d_to: str, cfg: FlowConfig, *,
             min_score: float, ninki_from: int = 0, ninki_to: int = 99,
             max_per_race: int = 1, tz=None, log=None) -> dict:
    """期間を通して単勝を買ったとしたらどうだったか。

    ★母数を誤魔化さない。スコアを出せなかったレース、払戻が未取込のレースを
      別々に数えて返す。ROI だけ見せると、取れた日だけで判断してしまう。
    """
    from datetime import timezone as _tz
    tz = tz or _tz(timedelta(hours=9))
    races = store.races_between(d_from, d_to)
    payouts = store.tansho_payouts(d_from, d_to)
    have_payout = store.races_with_payout(d_from, d_to)

    bets: list[Bet] = []
    scored = 0
    skips: dict[str, int] = {}
    no_payout = 0
    for rid, kdate, _jyo, _rno, ptime in races:
        post = post_datetime(kdate, ptime, tz)
        if post is None:
            skips["発走時刻が不正"] = skips.get("発走時刻が不正", 0) + 1
            continue
        snaps = group_snapshots(store.snapshots_for(rid))
        r = flow_scores(snaps, post, rid, cfg)
        if not r["scores"]:
            skips[r["skip"]] = skips.get(r["skip"], 0) + 1
            continue
        scored += 1
        if rid not in have_payout:
            # ★結果が未取込のレースで賭けたことにしない。全部外れ扱いになる。
            no_payout += 1
            continue
        pay = payouts.get(rid, {})
        for um, d in select(r["scores"], min_score=min_score, ninki_from=ninki_from,
                            ninki_to=ninki_to, max_per_race=max_per_race):
            bets.append(Bet(race_id=rid, kaisai_date=kdate, umaban=um,
                            score=d["score"], ninki=d["ninki"],
                            tan_odds=d["tan_odds"], payout=pay.get(um, 0),
                            window_sec=r["window_sec"], lag_sec=r["lag_sec"]))
        if log:
            log(rid)

    out = summarize(bets, races=len(races), races_scored=scored)
    out.update({"skips": skips, "races_without_payout": no_payout,
                "d_from": d_from, "d_to": d_to,
                "config": {"lead_sec": cfg.lead_sec, "flow_min": cfg.flow_min,
                           "spat4": cfg.spat4, "min_score": min_score,
                           "ninki": [ninki_from, ninki_to],
                           "max_per_race": max_per_race}})
    out["bets_detail"] = bets
    return out
