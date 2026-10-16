"""flow_tan(地方版)。

★この計算が間違っていると、間違った数字で投資判断をすることになる。
  特に「締切後の情報を使っていないか」は、間違っても気づけない種類の誤り。
"""

from datetime import datetime, timedelta

import pytest

from hro_nar_synchronizer.flow import (
    FlowConfig, assign_ninki, deadline_at, flow_scores, logit, pick_snapshot, shares,
)

JST = __import__("datetime").timezone(timedelta(hours=9))


def _at(h, m, s=0):
    return datetime(2026, 10, 16, h, m, s, tzinfo=JST)


KAWASAKI = "202645101510"      # 南関東
SONODA = "202650101510"        # 南関東以外
POST = _at(19, 40)


# --------------------------------------------------------------------------- #
# share と logit
# --------------------------------------------------------------------------- #
def test_shares_normalise_to_one():
    """控除率は割り算で消える。合計は必ず1。"""
    s = shares({"1": 2.0, "2": 4.0, "3": 4.0})
    assert sum(s.values()) == pytest.approx(1.0)
    assert s["1"] == pytest.approx(0.5)


def test_shares_ignore_missing_or_zero_odds():
    s = shares({"1": 2.0, "2": 0.0, "3": None})
    assert set(s) == {"1"} and s["1"] == pytest.approx(1.0)


def test_logit_is_clamped():
    assert logit(0.0) < -10 and logit(1.0) > 10      # 発散しない


# --------------------------------------------------------------------------- #
# ★基準は発走ではなく締切
# --------------------------------------------------------------------------- #
def test_deadline_is_two_minutes_before_post():
    assert deadline_at(POST, KAWASAKI) == _at(19, 38)


def test_spat4_moves_the_deadline_for_nankan_only():
    assert deadline_at(POST, KAWASAKI, spat4=True) == _at(19, 39)
    assert deadline_at(POST, SONODA, spat4=True) == _at(19, 38)


def test_late_snapshot_is_taken_from_the_deadline_not_the_post():
    """★ここを発走基準にすると、締切後の確定オッズを掴む。

    締切19:38 の60秒前 = 19:37。発走基準だと 19:39 を狙い、
    締切後の 19:38:30 の断面を使ってしまう。
    """
    snaps = [(_at(19, 7), {"1": 2.0, "2": 5.0}),
             (_at(19, 36, 50), {"1": 2.2, "2": 4.8}),
             (_at(19, 38, 30), {"1": 9.9, "2": 1.1})]   # 締切後(確定オッズ)
    r = flow_scores(snaps, POST, KAWASAKI, FlowConfig(lead_sec=60, flow_min=29))
    assert r["late_at"] == _at(19, 36, 50), "締切後の断面を掴んでいる"
    assert r["scores"]["1"]["tan_odds"] == 2.2


def test_post_deadline_snapshots_are_never_used():
    """★締切後しか無いなら、算出しない。使えば未来を見たことになる。"""
    snaps = [(_at(19, 39), {"1": 2.0, "2": 5.0}),
             (_at(19, 41), {"1": 9.9, "2": 1.1})]
    r = flow_scores(snaps, POST, KAWASAKI, FlowConfig(lead_sec=60))
    assert r["scores"] == {} and r["skip"] == "late_なし"


def test_pick_snapshot_never_looks_into_the_future():
    snaps = [(_at(19, 30), {"1": 2.0}), (_at(19, 37, 5), {"1": 2.1})]
    # 19:37:00 時点で手に入っているのは 19:30 の方(19:37:05 はまだ無い)
    assert pick_snapshot(snaps, _at(19, 37))[0] == _at(19, 30)


# --------------------------------------------------------------------------- #
# ★算出できないときに 0 を返さない
# --------------------------------------------------------------------------- #
def test_identical_snapshots_do_not_produce_a_zero_score():
    """★late と early が同一断面なら flow は測れていない。

    0 を返すと「資金が動かなかった」と区別が付かず、閾値の分位点が
    構造的ゼロで汚れる(中央で実際に踏んだ)。
    flow_min=0 という設定ミスでここに入る。黙って 0 を並べない。
    """
    snaps = [(_at(19, 10), {"1": 2.0, "2": 5.0}),
             (_at(19, 36), {"1": 2.1, "2": 4.9})]
    r = flow_scores(snaps, POST, KAWASAKI, FlowConfig(lead_sec=60, flow_min=0))
    assert r["scores"] == {}
    assert r["skip"] == "late_と_early_が同一断面"


def test_only_one_snapshot_is_reported_not_zeroed():
    snaps = [(_at(19, 36), {"1": 2.0, "2": 5.0})]
    r = flow_scores(snaps, POST, KAWASAKI, FlowConfig(lead_sec=60, flow_min=30))
    assert r["scores"] == {} and r["skip"] == "early_なし"


def test_a_stale_late_snapshot_is_refused():
    """★31秒刻みなのでズレは出るが、古すぎる断面に『締切直前』を名乗らせない。"""
    snaps = [(_at(19, 5), {"1": 2.0, "2": 5.0}),
             (_at(19, 34), {"1": 2.1, "2": 4.9})]     # 狙い 19:37 に対し 180秒前
    r = flow_scores(snaps, POST, KAWASAKI, FlowConfig(lead_sec=60, max_lag_sec=90))
    assert r["scores"] == {} and "late_が古い" in r["skip"]


def test_missing_early_is_reported_not_zeroed():
    snaps = [(_at(19, 36), {"1": 2.0, "2": 5.0}),
             (_at(19, 37), {"1": 2.1, "2": 4.9})]
    r = flow_scores(snaps, POST, KAWASAKI, FlowConfig(lead_sec=60, flow_min=30))
    assert r["scores"] == {} and r["skip"] == "early_なし"


# --------------------------------------------------------------------------- #
# スコアの中身
# --------------------------------------------------------------------------- #
def _two_point(early_odds, late_odds, *, flow_min=30):
    snaps = [(_at(19, 6), early_odds), (_at(19, 36, 40), late_odds)]
    return flow_scores(snaps, POST, KAWASAKI,
                       FlowConfig(lead_sec=60, flow_min=flow_min))


def test_money_coming_in_gives_a_positive_score():
    """人気を集めた馬(オッズが下がった)は正のスコア。"""
    r = _two_point({"1": 10.0, "2": 2.0}, {"1": 5.0, "2": 2.5})
    assert r["scores"]["1"]["score"] > 0
    assert r["scores"]["2"]["score"] < 0


def test_score_is_the_logit_difference_of_shares():
    r = _two_point({"1": 10.0, "2": 2.0}, {"1": 5.0, "2": 2.5})
    d = r["scores"]["1"]
    assert d["score"] == pytest.approx(logit(d["share_late"]) - logit(d["share_early"]))


def test_proportional_drift_of_all_horses_scores_zero():
    """★全馬が同じ比率で動くのは、情報ではなく控除率/母数の変化。share は不変。"""
    r = _two_point({"1": 10.0, "2": 2.0}, {"1": 20.0, "2": 4.0})
    for d in r["scores"].values():
        assert d["score"] == pytest.approx(0.0, abs=1e-9)


def test_ninki_comes_from_late_odds_not_from_the_database():
    """★確定人気は締切後の情報。使えば未来を見たことになる。"""
    r = _two_point({"1": 10.0, "2": 2.0, "3": 3.0}, {"1": 1.5, "2": 4.0, "3": 3.0})
    got = {u: d["ninki"] for u, d in r["scores"].items()}
    assert got == {"1": 1, "3": 2, "2": 3}


def test_horses_absent_at_the_early_point_are_skipped():
    r = _two_point({"1": 10.0, "2": 2.0}, {"1": 5.0, "2": 2.5, "9": 50.0})
    assert "9" not in r["scores"]


def test_window_and_lag_are_carried():
    """★窓の長さが日で違うと絶対閾値が比較できない。必ず持ち回る。"""
    r = _two_point({"1": 10.0, "2": 2.0}, {"1": 5.0, "2": 2.5})
    assert r["window_sec"] == pytest.approx((_at(19, 36, 40) - _at(19, 6)).total_seconds())
    assert r["lag_sec"] == pytest.approx(20)     # 狙い 19:37:00 に対し 19:36:40
    assert r["window_ok"] is True


def test_a_window_stretched_by_sparse_early_data_is_flagged():
    """★窓は指定より**短くはならない**が、長くはなる。

    early 側が疎だと「30分前」を狙っても66分前の断面しか無く、窓が伸びる。
    窓が長いほどスコアは大きく出るので、同じ絶対閾値で比べると候補が増える。
    日によって窓が違うと閾値が比較できない(中央で実際に踏んだ)。
    """
    snaps = [(_at(18, 30), {"1": 10.0, "2": 2.0}),
             (_at(19, 36, 40), {"1": 5.0, "2": 2.5})]
    r = flow_scores(snaps, POST, KAWASAKI, FlowConfig(lead_sec=60, flow_min=30))
    assert r["scores"], "算出はできている"
    assert r["window_sec"] > 30 * 60
    assert r["window_ok"] is False


def test_the_window_can_never_be_shorter_than_asked():
    """early は『late の flow_min 前**以前**』から取るので、窓が縮むことはない。"""
    snaps = [(_at(19, 6), {"1": 10.0, "2": 2.0}),
             (_at(19, 20), {"1": 8.0, "2": 2.2}),
             (_at(19, 36, 40), {"1": 5.0, "2": 2.5})]
    r = flow_scores(snaps, POST, KAWASAKI, FlowConfig(lead_sec=60, flow_min=30))
    assert r["early_at"] == _at(19, 6)
    assert r["window_sec"] >= 30 * 60


def test_move_measures_total_share_change():
    r = _two_point({"1": 10.0, "2": 2.0}, {"1": 5.0, "2": 2.5})
    assert r["move"] > 0
    flat = _two_point({"1": 10.0, "2": 2.0}, {"1": 10.0, "2": 2.0})
    assert flat["move"] == pytest.approx(0.0, abs=1e-9)


# --------------------------------------------------------------------------- #
# バックテスト。★信じてよい数字を出すのが仕事。母数を誤魔化さない。
# --------------------------------------------------------------------------- #
from hro_nar_synchronizer.flow import (  # noqa: E402
    Bet, backtest, group_snapshots, post_datetime, select, summarize,
)


class _Store:
    def __init__(self, races, snaps, payouts, with_payout=None):
        self._races, self._snaps, self._pay = races, snaps, payouts
        self._have = with_payout if with_payout is not None else set(payouts)

    def races_between(self, a, b):
        return self._races

    def snapshots_for(self, rid):
        return self._snaps.get(rid, [])

    def tansho_payouts(self, a, b):
        return self._pay

    def races_with_payout(self, a, b):
        return self._have


def _snaps(rid, early, late):
    return [(_at(19, 6), u, o) for u, o in early.items()] + \
           [(_at(19, 36, 40), u, o) for u, o in late.items()]


def test_group_snapshots_builds_cross_sections():
    rows = [(_at(19, 6), "1", 10.0), (_at(19, 6), "2", 2.0),
            (_at(19, 36), "1", 5.0), (_at(19, 36), "2", 2.5)]
    g = group_snapshots(rows)
    assert [t for t, _ in g] == [_at(19, 6), _at(19, 36)]
    assert g[1][1] == {"1": 5.0, "2": 2.5}


def test_post_datetime():
    assert post_datetime("20261016", "19:40", JST) == _at(19, 40)
    assert post_datetime("20261016", "なし", JST) is None


def test_select_takes_the_top_score_within_the_popularity_band():
    scored = {"1": {"score": 0.9, "ninki": 1}, "2": {"score": 0.5, "ninki": 8},
              "3": {"score": 0.7, "ninki": 9}}
    got = select(scored, min_score=0.4, ninki_from=7, ninki_to=99, max_per_race=1)
    assert [u for u, _ in got] == ["3"]


def test_summarize_reports_the_denominator():
    """★ROI だけ出さない。母数が無いと判断を誤る。"""
    bets = [Bet("r", "d", "1", 1.0, 1, 5.0, 540, 1800, 20),
            Bet("r2", "d", "2", 1.0, 2, 3.0, 0, 1800, 20)]
    s = summarize(bets, races=10, races_scored=4)
    assert s["bets"] == 2 and s["staked"] == 200 and s["returned"] == 540
    assert s["roi"] == pytest.approx(2.7)
    assert s["hit_rate"] == pytest.approx(0.5)
    assert s["races"] == 10 and s["races_scored"] == 4


def test_backtest_counts_bets_and_roi():
    races = [("R1", "20261016", "45", "10", "19:40")]
    store = _Store(races,
                   {"R1": _snaps("R1", {"1": 10.0, "2": 2.0}, {"1": 5.0, "2": 2.5})},
                   {"R1": {"1": 540}})
    out = backtest(store, "20261016", "20261016",
                   FlowConfig(lead_sec=60, flow_min=30), min_score=0.1)
    assert out["races"] == 1 and out["races_scored"] == 1
    assert out["bets"] == 1 and out["returned"] == 540
    assert out["roi"] == pytest.approx(5.4)


def test_races_without_payout_are_not_counted_as_losses():
    """★結果が未取込のレースで賭けたことにしない。全部外れ扱いになる。"""
    races = [("R1", "20261016", "45", "10", "19:40")]
    store = _Store(races,
                   {"R1": _snaps("R1", {"1": 10.0, "2": 2.0}, {"1": 5.0, "2": 2.5})},
                   {}, with_payout=set())
    out = backtest(store, "20261016", "20261016",
                   FlowConfig(lead_sec=60, flow_min=30), min_score=0.1)
    assert out["bets"] == 0
    assert out["races_without_payout"] == 1
    assert out["races_scored"] == 1, "スコアは出せていたことは残す"


def test_skip_reasons_are_tallied():
    """★なぜ買えなかったかを数える。『候補0』で終わらせない。"""
    races = [("R1", "20261016", "45", "10", "19:40"),
             ("R2", "20261016", "45", "11", "20:15")]
    store = _Store(races,
                   {"R1": _snaps("R1", {"1": 10.0, "2": 2.0}, {"1": 5.0, "2": 2.5}),
                    "R2": [(_at(20, 14), "1", 3.0)]},     # 締切後しか無い
                   {"R1": {"1": 540}})
    out = backtest(store, "20261016", "20261016",
                   FlowConfig(lead_sec=60, flow_min=30), min_score=0.1)
    assert out["races"] == 2 and out["races_scored"] == 1
    assert sum(out["skips"].values()) == 1


def test_config_is_recorded_with_the_result():
    """★どの設定で出した数字かが分からなくなると、比較できない。"""
    store = _Store([], {}, {})
    out = backtest(store, "20261016", "20261016",
                   FlowConfig(lead_sec=60, flow_min=30, spat4=True), min_score=0.25,
                   ninki_from=7)
    c = out["config"]
    assert c["lead_sec"] == 60 and c["flow_min"] == 30 and c["spat4"] is True
    assert c["min_score"] == 0.25 and c["ninki"] == [7, 99]
