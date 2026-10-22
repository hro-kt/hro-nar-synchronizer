"""収集ループ。時系列は取り戻せないので、落ちない・取りこぼさないことを固める。"""

from datetime import datetime, timedelta

import pytest

from hro_nar_synchronizer.collector import (
    JST, Stats, collect, deadline_dt, is_active, post_dt, rows_for,
)
from hro_nar_synchronizer.odds_page import OddsPage
from hro_nar_synchronizer.race_list import Race


def _race(rid="202645101510", post="19:40"):
    return Race(race_id=rid, kaisai_date="20261015", jyo_cd=rid[4:6],
                race_num=rid[10:12], post_time=post, title="t", tosu=11)


def _at(h, m, s=0):
    return datetime(2026, 10, 15, h, m, s, tzinfo=JST)


def test_deadline_is_computed_from_post_and_venue():
    r = _race()
    assert post_dt(r) == _at(19, 40)
    assert deadline_dt(r) == _at(19, 38)                      # 一般 2分前
    assert deadline_dt(r, spat4=True) == _at(19, 39)          # SPAT4 南関東 1分前


def test_sonoda_is_unaffected_by_spat4():
    r = _race("202650101510")
    assert deadline_dt(r, spat4=True) == _at(19, 38)


def test_active_window_covers_before_post_and_a_little_after():
    r = _race()
    assert not is_active(r, _at(19, 10), window_min=25, grace_min=3)
    assert is_active(r, _at(19, 20), window_min=25, grace_min=3)
    assert is_active(r, _at(19, 40), window_min=25, grace_min=3)
    # ★発走後も少しは見る(確定オッズ)。ただし判断には使わない
    assert is_active(r, _at(19, 42), window_min=25, grace_min=3)
    assert not is_active(r, _at(19, 45), window_min=25, grace_min=3)


def test_rows_carry_the_deadline_so_it_can_be_separated_later():
    """★締切後のオッズは確定オッズ。判断に使えば未来を見たことになる。

    行に deadline_at を持たせておけば、後から SQL で切り分けられる。
    """
    r = _race()
    page = OddsPage(race_id=r.race_id, tan={"1": 2.0, "2": 5.0},
                    fuku={"1": (1.1, 1.3)}, latency_ms=12, x_cache="Miss")
    rows = rows_for(r, page, _at(19, 37, 39))
    assert len(rows) == 2
    by_umaban = {row[1]: row for row in rows}
    assert by_umaban["1"][3] == 2.0            # tan
    assert by_umaban["1"][4] == 1.1            # fuku low
    assert by_umaban["2"][4] is None           # 複勝が無い馬は None
    assert all(row[10] == _at(19, 38) for row in rows)   # deadline_at
    assert all(row[13] == "Miss" for row in rows)        # x_cache


def test_same_values_are_not_saved_twice():
    r = _race()
    clock = {"t": _at(19, 20)}
    pages = [
        OddsPage(race_id=r.race_id, tan={"1": 2.0}),
        OddsPage(race_id=r.race_id, tan={"1": 2.0}),   # 同値
        OddsPage(race_id=r.race_id, tan={"1": 2.1}),
    ]
    i = {"n": 0}

    def _fetch(rid, **kw):
        p = pages[min(i["n"], len(pages) - 1)]
        i["n"] += 1
        return p

    def _sleep(_):
        clock["t"] += timedelta(seconds=30)

    st = collect([r], None, fetch_fn=_fetch, sleep_fn=_sleep,
                 now_fn=lambda: clock["t"], log=lambda s: None, max_seconds=None)
    assert st.changes == 2, "同値を保存している"


def test_one_race_failing_does_not_stop_the_rest():
    """★1レースの失敗で全体を止めない。時系列は取り戻せない。"""
    good, bad = _race("202645101510"), _race("202630101510")
    clock = {"t": _at(19, 20)}

    def _fetch(rid, **kw):
        if rid == bad.race_id:
            raise ConnectionError("boom")
        return OddsPage(race_id=rid, tan={"1": 2.0 + clock["t"].second})

    def _sleep(_):
        clock["t"] += timedelta(seconds=25)

    st = collect([good, bad], None, fetch_fn=_fetch, sleep_fn=_sleep,
                 now_fn=lambda: clock["t"], log=lambda s: None)
    assert st.errors > 0
    assert st.changes > 0, "失敗したレースに引きずられて全部止まっている"


def test_empty_odds_are_not_saved():
    """発売前は空。保存せず、黙って待つ。"""
    r = _race()
    clock = {"t": _at(19, 20)}

    def _sleep(_):
        clock["t"] += timedelta(seconds=60)

    st = collect([r], None, fetch_fn=lambda rid, **kw: OddsPage(race_id=rid),
                 sleep_fn=_sleep, now_fn=lambda: clock["t"], log=lambda s: None)
    assert st.changes == 0 and st.saved_rows == 0


def test_loop_ends_after_the_last_race():
    r = _race()
    clock = {"t": _at(19, 20)}

    def _sleep(_):
        clock["t"] += timedelta(minutes=5)

    st = collect([r], None, fetch_fn=lambda rid, **kw: OddsPage(race_id=rid, tan={"1": 2.0}),
                 sleep_fn=_sleep, now_fn=lambda: clock["t"], log=lambda s: None)
    assert clock["t"] > _at(19, 43)
    assert st.polls > 0


def test_cache_hits_are_counted():
    """★CloudFront の Hit が続くなら、見ているのは古い値。"""
    r = _race()
    clock = {"t": _at(19, 20)}
    n = {"i": 0}

    def _fetch(rid, **kw):
        n["i"] += 1
        return OddsPage(race_id=rid, tan={"1": 2.0 + n["i"]},
                        x_cache="Hit from cloudfront")

    def _sleep(_):
        clock["t"] += timedelta(seconds=30)

    st = collect([r], None, fetch_fn=_fetch, sleep_fn=_sleep,
                 now_fn=lambda: clock["t"], log=lambda s: None)
    assert st.cache_hits == st.polls > 0


# --------------------------------------------------------------------------- #
# ★沈黙の検知。「録れているつもり」が一番危ない。
# --------------------------------------------------------------------------- #
def test_repeated_empty_reads_are_warned_not_swallowed():
    """markup が変われば0件になるが、発売前も0件。黙って同じ扱いにしない。"""
    r = _race()
    clock = {"t": _at(19, 20)}
    said: list[str] = []

    def _sleep(_):
        clock["t"] += timedelta(seconds=10)

    st = collect([r], None, fetch_fn=lambda rid, **kw: OddsPage(race_id=rid),
                 sleep_fn=_sleep, now_fn=lambda: clock["t"],
                 log=said.append)
    assert st.empty_polls > 0
    assert any("1頭も取れていません" in s for s in said), said
    assert r.race_id in st.silent_races


def test_a_single_empty_read_does_not_cry_wolf():
    """発売前の1回で騒がない。閾値まで待つ。"""
    r = _race()
    clock = {"t": _at(19, 20)}
    said: list[str] = []
    n = {"i": 0}

    def _fetch(rid, **kw):
        n["i"] += 1
        return OddsPage(race_id=rid) if n["i"] <= 2 else OddsPage(race_id=rid, tan={"1": 2.0})

    def _sleep(_):
        clock["t"] += timedelta(seconds=10)

    collect([r], None, fetch_fn=_fetch, sleep_fn=_sleep,
            now_fn=lambda: clock["t"], log=said.append)
    assert not any("1頭も取れていません" in s for s in said), said


def test_is_broken_detects_a_fully_silent_run():
    """★1レースも読めずに1日が終わったら、それは収集が壊れている。"""
    r = _race()
    clock = {"t": _at(19, 20)}

    def _sleep(_):
        clock["t"] += timedelta(seconds=20)

    st = collect([r], None, fetch_fn=lambda rid, **kw: OddsPage(race_id=rid),
                 sleep_fn=_sleep, now_fn=lambda: clock["t"], log=lambda s: None)
    assert st.is_broken()


def test_a_healthy_run_is_not_reported_as_broken():
    r = _race()
    clock = {"t": _at(19, 20)}
    n = {"i": 0}

    def _fetch(rid, **kw):
        n["i"] += 1
        return OddsPage(race_id=rid, tan={"1": 2.0 + n["i"]})

    def _sleep(_):
        clock["t"] += timedelta(seconds=20)

    st = collect([r], None, fetch_fn=_fetch, sleep_fn=_sleep,
                 now_fn=lambda: clock["t"], log=lambda s: None)
    assert not st.is_broken()


# --------------------------------------------------------------------------- #
# ★DB が落ちても収集を殺さない
# --------------------------------------------------------------------------- #
class _Store:
    """insert_odds が最初の n 回だけ落ちる偽 store。"""

    def __init__(self, fail_times=0):
        self.fail_times, self.saved = fail_times, []

    def last_digest(self, race_id):
        return None

    def insert_odds(self, rows):
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ConnectionError("the database system is shutting down")
        self.saved.append(rows)
        return len(rows)


def test_a_db_outage_does_not_kill_the_collector():
    """★2026-10-22 に PostgreSQL が再起動した。ここが素通りだと、
       その瞬間に地方の収集が丸ごと終わる(systemd は oneshot で翌朝まで戻らない)。
    """
    r = _race()
    clock = {"t": _at(19, 20)}
    n = {"i": 0}

    def _fetch(rid, **kw):
        n["i"] += 1
        return OddsPage(race_id=rid, tan={"1": 2.0 + n["i"], "2": 5.0})

    def _sleep(_):
        clock["t"] += timedelta(seconds=30)

    store = _Store(fail_times=2)
    st = collect([r], store, fetch_fn=_fetch, sleep_fn=_sleep,
                 now_fn=lambda: clock["t"], log=lambda s: None)
    assert st.db_errors == 2
    assert store.saved, "DB が戻ってからも保存できていない"
    assert st.changes > 0


def test_a_value_that_failed_to_save_is_retried():
    """★last を先に覚えると、書けなかった値が**永久に失われる**。"""
    r = _race()
    clock = {"t": _at(19, 20)}

    def _fetch(rid, **kw):
        return OddsPage(race_id=rid, tan={"1": 2.0, "2": 5.0})   # ずっと同じ値

    def _sleep(_):
        clock["t"] += timedelta(seconds=30)

    store = _Store(fail_times=1)
    st = collect([r], store, fetch_fn=_fetch, sleep_fn=_sleep,
                 now_fn=lambda: clock["t"], log=lambda s: None)
    assert st.db_errors == 1
    assert store.saved, "一度書けなかった値が再試行されていない"
    assert store.saved[0][0][3] == 2.0


def test_db_failures_are_counted_in_the_summary():
    st = Stats(polls=10, db_errors=3)
    assert "DB失敗 3" in st.line()
