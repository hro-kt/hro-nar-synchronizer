"""測定用。収集とは別に、前提が変わっていないかを確かめる。

★hro-synchronizer から引き上げたもの。地方のコードを中央側に残さない。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from .collector import JST, deadline_dt
from .odds_page import cookie_header, fetch
from .race_list import Race, fetch_list
from .tracks import describe


def _race(race_id: str, date: str) -> Race:
    for r in fetch_list(date):
        if r.race_id == race_id:
            return r
    raise SystemExit(f"{date} の一覧に {race_id} がありません")


def compare_login(race_id: str, *, state_path: str | None = None,
                  rounds: int = 3, gap: float = 2.0, fetch_fn=fetch) -> dict[str, Any]:
    """同じ瞬間に『ログインあり』『なし』で取って突き合わせる。

    ★非会員が**遅れた値**を見せられていないかを確かめる唯一の方法。
      遅延は時間軸のずれなので、更新間隔を測るだけでは絶対に分からない。
      実測(2026-10-15、発走13〜30分前)では一致したが、中央でプレミアムが
      効いていたのは**締切直前の更新頻度**。そこは締切2分前に流して確かめる。
    """
    cookies = cookie_header(state_path)
    if not cookies:
        raise SystemExit("保存済み netkeiba セッションがありません(比較できません)")
    rows = []
    for _ in range(max(1, rounds)):
        anon = fetch_fn(race_id)
        auth = fetch_fn(race_id, cookies=cookies)
        keys = sorted(set(anon.tan) | set(auth.tan), key=int)
        diff = {k: (anon.tan.get(k), auth.tan.get(k))
                for k in keys if anon.tan.get(k) != auth.tan.get(k)}
        rows.append({"at": datetime.now(JST).isoformat(),
                     "n_anon": len(anon.tan), "n_auth": len(auth.tan),
                     "same": not diff, "diff": diff})
        time.sleep(max(0.0, gap))
    agree = sum(1 for r in rows if r["same"])
    return {"race_id": race_id, "race": describe(race_id), "rounds": len(rows),
            "agree": agree, "rows": rows,
            "verdict": ("ログインの有無で値が変わりません" if agree == len(rows)
                        else "★ログインの有無で値が違います。非会員は同じものを見ていません")}


def cadence(race_id: str, date: str, *, seconds: float = 900, interval: float = 3.0,
            spat4: bool = False, state_path: str | None = None,
            fetch_fn=fetch, log=print) -> dict[str, Any]:
    """更新粒度を測る。判定は**締切基準**(発走基準では確定オッズを拾ってしまう)。"""
    race = _race(race_id, date)
    cookies = cookie_header(state_path)
    dl = deadline_dt(race, spat4=spat4)
    log(f"=== {describe(race_id)} 発走 {race.post_time} / 締切 "
        f"{dl:%H:%M:%S}" + (" (SPAT4 南関東 1分前)" if spat4 else " (一般 2分前)") + " ===")
    changes: list[tuple[datetime, dict[str, float]]] = []
    last = None
    cache_hit = 0
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        try:
            p = fetch_fn(race_id, cookies=cookies)
        except Exception as e:  # noqa: BLE001
            log(f"  ✗ 取得に失敗: {type(e).__name__}"); time.sleep(interval); continue
        if "Hit" in (p.x_cache or ""):
            cache_hit += 1
        if p.tan and p.tan != last:
            now = datetime.now(JST)
            gap = (f"+{(now - changes[-1][0]).total_seconds():.0f}s" if changes else "  -  ")
            log(f"  [{now:%H:%M:%S}] {gap:>6} {len(p.tan)}頭  "
                + ", ".join(f"{k}:{v}" for k, v in sorted(p.tan.items(), key=lambda kv: int(kv[0]))[:4]))
            changes.append((now, dict(p.tan)))
            last = p.tan
        time.sleep(interval)
    gaps = [(b[0] - a[0]).total_seconds() for a, b in zip(changes, changes[1:])]
    usable = [c for c in changes if dl is not None and c[0] <= dl]
    lag = (dl - usable[-1][0]).total_seconds() if usable and dl else None
    med = sorted(gaps)[len(gaps) // 2] if gaps else None
    return {"race_id": race_id, "changes": len(changes), "cache_hits": cache_hit,
            "gap_median_sec": med, "lag_to_deadline_sec": lag,
            "deadline": dl.isoformat() if dl else None,
            "ok": bool(med is not None and med <= 60 and lag is not None and lag <= 180)}
