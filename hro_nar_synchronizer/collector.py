"""収集ループ。

★時系列オッズは後から取り戻せない。落ちない・黙らない・取りこぼさないことを優先する。
  1レースの失敗で全体を止めない。何をしているかを常に出す。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .odds_page import OddsPage, cookie_header, fetch
from .race_list import Race
from .tracks import describe

JST = timezone(timedelta(hours=9))

# 同じレースをこの回数続けて読んで1頭も取れなければ警告する。
# ★発売前でも空になるので、1回で騒がない。ただし黙り続けもしない。
EMPTY_WARN_AT = 5


def now_jst() -> datetime:
    return datetime.now(JST)


def post_dt(race: Race) -> datetime | None:
    """発走時刻(JST)。開催日 + HH:MM。"""
    if not race.post_time:
        return None
    try:
        h, m = (int(x) for x in race.post_time.split(":"))
        d = race.kaisai_date
        return datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), h, m, tzinfo=JST)
    except (ValueError, IndexError):
        return None


def deadline_dt(race: Race, *, spat4: bool = False) -> datetime | None:
    p = post_dt(race)
    return None if p is None else p - timedelta(seconds=race.deadline_sec(spat4=spat4))


def is_active(race: Race, now: datetime, *, window_min: int, grace_min: int) -> bool:
    """いま収集すべきレースか。

    ★発走を過ぎても grace_min までは見る(確定オッズの取得)。
      ただしそれは**判断には使えない**。deadline_at で後から切り分ける。
    """
    p = post_dt(race)
    if p is None:
        return False
    return (p - timedelta(minutes=window_min)) <= now <= (p + timedelta(minutes=grace_min))


def rows_for(race: Race, page: OddsPage, observed_at: datetime, *,
             spat4: bool = False) -> list[tuple]:
    dl = deadline_dt(race, spat4=spat4)
    umabans = sorted(set(page.tan) | set(page.fuku), key=int)
    out = []
    for u in umabans:
        lo, hi = page.fuku.get(u, (None, None))
        out.append((race.race_id, u, observed_at, page.tan.get(u), lo, hi,
                    race.kaisai_date, race.jyo_cd, race.race_num, race.post_time,
                    dl, observed_at, page.latency_ms, page.x_cache, page.logged_in))
    return out


@dataclass
class Stats:
    polls: int = 0
    saved_rows: int = 0
    changes: int = 0
    errors: int = 0
    cache_hits: int = 0
    empty_polls: int = 0                  # 1頭も読めなかった取得
    silent_races: set = field(default_factory=set)
    per_race: dict[str, int] = field(default_factory=dict)

    def line(self) -> str:
        return (f"周回 {self.polls} / 変化 {self.changes} / 保存 {self.saved_rows}行"
                f" / 失敗 {self.errors} / 空 {self.empty_polls}"
                f" / キャッシュHit {self.cache_hits}")

    def is_broken(self) -> bool:
        """★「録れているつもり」を検出する。

        発走直前のレースを何度も叩いて**一度も読めていない**なら、発売前ではなく
        markup が変わったと考える方が自然。黙って0行のまま走り続けさせない。
        """
        return self.polls > 0 and self.changes == 0 and self.empty_polls >= self.polls


def collect(races: list[Race], store, *, spat4: bool = False,
            window_min: int = 25, grace_min: int = 3, interval_sec: float = 8.0,
            state_path: str | None = None, max_seconds: float | None = None,
            now_fn: Callable[[], datetime] = now_jst,
            fetch_fn: Callable[..., OddsPage] = fetch,
            sleep_fn: Callable[[float], None] = time.sleep,
            log: Callable[[str], None] = print) -> Stats:
    """締切前後の断面を取り続ける。"""
    cookies = cookie_header(state_path)
    log(f"  ログイン: {'あり(保存済みセッション)' if cookies else 'なし(非会員)'}")
    st = Stats()
    last: dict[str, str] = {}
    empty: dict[str, int] = {}
    started = time.monotonic()
    done: set[str] = set()

    while True:
        now = now_fn()
        active = [r for r in races
                  if r.race_id not in done
                  and is_active(r, now, window_min=window_min, grace_min=grace_min)]
        remaining = [r for r in races if r.race_id not in done
                     and (post_dt(r) is None
                          or now <= post_dt(r) + timedelta(minutes=grace_min))]
        if not remaining:
            log("  本日の対象レースは終わりました")
            break
        if max_seconds is not None and (time.monotonic() - started) >= max_seconds:
            log("  指定時間に達しました")
            break

        for r in active:
            try:
                page = fetch_fn(r.race_id, cookies=cookies)
            except Exception as e:  # noqa: BLE001
                st.errors += 1
                log(f"  ✗ {describe(r.race_id)} 取得に失敗: {type(e).__name__}: {str(e)[:90]}")
                continue
            st.polls += 1
            if "Hit" in (page.x_cache or ""):
                st.cache_hits += 1
            if not page.tan:
                # ★発売前なら空で正常。しかし markup 変更でも同じ見え方になる。
                #   区別が付かないまま黙らない。連続で読めなければ言う。
                st.empty_polls += 1
                empty[r.race_id] = empty.get(r.race_id, 0) + 1
                if empty[r.race_id] == EMPTY_WARN_AT:
                    st.silent_races.add(r.race_id)
                    log(f"  ⚠ {describe(r.race_id)} を {EMPTY_WARN_AT} 回読んで"
                        "1頭も取れていません。発売前か、ページの構造が変わった可能性があります")
                continue
            empty.pop(r.race_id, None)
            dg = page.digest_source()
            if last.get(r.race_id) == dg:
                continue                      # 同値は保存しない
            prev = last.get(r.race_id)
            last[r.race_id] = dg
            if prev is None and store is not None:
                # 再起動時に同じ値を二重に入れない
                if store.last_digest(r.race_id) is not None and _same(store, r, page):
                    continue
            rows = rows_for(r, page, now_fn(), spat4=spat4)
            if store is not None:
                st.saved_rows += store.insert_odds(rows)
            else:
                st.saved_rows += len(rows)
            st.changes += 1
            st.per_race[r.race_id] = st.per_race.get(r.race_id, 0) + 1
            dl = deadline_dt(r, spat4=spat4)
            to_dl = f"{(dl - now).total_seconds():+.0f}s" if dl else "--"
            log(f"  [{now:%H:%M:%S}] {describe(r.race_id)} 締切まで {to_dl}"
                f"  {len(page.tan)}頭  単勝 "
                + ", ".join(f"{k}:{v}" for k, v in
                            sorted(page.tan.items(), key=lambda kv: int(kv[0]))[:4]))

        # 締切+猶予を過ぎたものは以後見ない
        for r in races:
            p = post_dt(r)
            if p is not None and now > p + timedelta(minutes=grace_min):
                done.add(r.race_id)

        sleep_fn(interval_sec if active else min(30.0, max(interval_sec, 15.0)))
    return st


def _same(store, race: Race, page: OddsPage) -> bool:
    """DB の最終値と同じか(再起動直後の二重保存を避ける)。"""
    try:
        cur = store.last_digest(race.race_id)
    except Exception:  # noqa: BLE001
        return False
    if cur is None:
        return False
    rows = [(u, page.tan.get(u), *page.fuku.get(u, (None, None)))
            for u in sorted(set(page.tan) | set(page.fuku), key=int)]
    return repr(rows) == cur
