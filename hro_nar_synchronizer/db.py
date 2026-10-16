"""DB。psycopg が使えなければ pg8000(純 Python)に落ちる。"""

from __future__ import annotations

import logging
from typing import Any, Iterable

from .config import Config

log = logging.getLogger(__name__)


def connect(cfg: Config):
    pg = cfg.postgres
    try:
        import psycopg
        dsn = (f"host={pg.host} port={pg.port} dbname={pg.dbname} "
               f"user={pg.user} password={pg.password}")
        if pg.sslmode:
            dsn += f" sslmode={pg.sslmode}"
        return psycopg.connect(dsn, autocommit=True), "psycopg"
    except ModuleNotFoundError:
        pass
    import pg8000.dbapi
    kw: dict[str, Any] = dict(host=pg.host, port=pg.port, database=pg.dbname,
                              user=pg.user, password=pg.password)
    if pg.sslmode:
        import ssl
        kw["ssl_context"] = ssl.create_default_context()
    conn = pg8000.dbapi.connect(**kw)
    conn.autocommit = True
    return conn, "pg8000"


class Store:
    def __init__(self, conn, driver: str) -> None:
        self.conn, self.driver = conn, driver

    # ★pg8000 は %s ではなく %s を使えるが paramstyle が format。両方で動く書き方にする。
    def _exec(self, sql: str, params: Iterable[Any] | None = None) -> None:
        cur = self.conn.cursor()
        try:
            cur.execute(sql, tuple(params) if params else None)
        finally:
            cur.close()

    def apply_schema(self, path) -> None:
        with open(path, encoding="utf-8") as f:
            self._exec(f.read())

    def upsert_races(self, races) -> int:
        n = 0
        for r in races:
            self._exec(
                "INSERT INTO nar_race"
                " (race_id, kaisai_date, jyo_cd, race_num, post_time, title, tosu,"
                "  updated_at)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s, now())"
                " ON CONFLICT (race_id) DO UPDATE SET"
                "  kaisai_date=EXCLUDED.kaisai_date, post_time=EXCLUDED.post_time,"
                "  title=EXCLUDED.title, tosu=EXCLUDED.tosu, updated_at=now()",
                (r.race_id, r.kaisai_date, r.jyo_cd, r.race_num,
                 r.post_time, r.title, r.tosu))
            n += 1
        return n

    def races_for(self, date: str) -> list[tuple]:
        cur = self.conn.cursor()
        try:
            cur.execute(
                "SELECT race_id, kaisai_date, jyo_cd, race_num, post_time, title, tosu"
                " FROM nar_race WHERE kaisai_date = %s ORDER BY post_time, jyo_cd",
                (date,))
            return list(cur.fetchall())
        finally:
            cur.close()

    def insert_odds(self, rows: list[tuple]) -> int:
        """値が変わった観測だけを入れる。同一 (race_id, 馬番, 時刻) は捨てる。"""
        for row in rows:
            self._exec(
                "INSERT INTO nar_o1"
                " (race_id, umaban, observed_at, tan_odds, fuku_odds_low,"
                "  fuku_odds_high, kaisai_date, jyo_cd, race_num, post_time,"
                "  deadline_at, fetched_at, latency_ms, x_cache, logged_in)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (race_id, umaban, observed_at) DO NOTHING", row)
        return len(rows)

    def last_digest(self, race_id: str) -> str | None:
        """直近に保存した値の指紋。再起動しても同値を二重に入れないため。"""
        cur = self.conn.cursor()
        try:
            cur.execute(
                "SELECT umaban, tan_odds, fuku_odds_low, fuku_odds_high FROM nar_o1"
                " WHERE race_id = %s AND observed_at ="
                "   (SELECT max(observed_at) FROM nar_o1 WHERE race_id = %s)"
                " ORDER BY umaban", (race_id, race_id))
            rows = cur.fetchall()
        finally:
            cur.close()
        return repr([tuple(r) for r in rows]) if rows else None

    # ---- 結果・払戻 ---------------------------------------------------------
    def races_with_results(self, date: str) -> set[str]:
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT DISTINCT race_id FROM nar_result WHERE kaisai_date = %s",
                        (date,))
            return {r[0] for r in cur.fetchall()}
        finally:
            cur.close()

    def save_result(self, res, date: str) -> None:
        for f in res.finishes:
            self._exec(
                "INSERT INTO nar_result"
                " (race_id, umaban, chakujun, waku, horse_id, horse_name, ninki,"
                "  tan_odds, time, kaisai_date)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (race_id, umaban) DO UPDATE SET"
                "  chakujun=EXCLUDED.chakujun, ninki=EXCLUDED.ninki,"
                "  tan_odds=EXCLUDED.tan_odds, time=EXCLUDED.time,"
                "  fetched_at=now()",
                (res.race_id, f.umaban, f.chakujun, f.waku, f.horse_id,
                 f.horse_name, f.ninki, f.tan_odds, f.time, date))
        for p in res.payouts:
            self._exec(
                "INSERT INTO nar_payout (race_id, bet_type, kumi, yen, ninki, kaisai_date)"
                " VALUES (%s,%s,%s,%s,%s,%s)"
                " ON CONFLICT (race_id, bet_type, kumi) DO UPDATE SET"
                "  yen=EXCLUDED.yen, ninki=EXCLUDED.ninki, fetched_at=now()",
                (res.race_id, p.bet_type, p.kumi, p.yen, p.ninki, date))

    # ---- 被覆 ---------------------------------------------------------------
    def coverage(self, date: str | None) -> list[tuple]:
        cur = self.conn.cursor()
        try:
            if date:
                cur.execute("SELECT * FROM v_nar_coverage WHERE kaisai_date = %s"
                            " ORDER BY post_time, jyo_cd", (date,))
            else:
                cur.execute("SELECT * FROM v_nar_coverage"
                            " WHERE kaisai_date >= to_char(now() - interval '7 days',"
                            "                              'YYYYMMDD')"
                            " ORDER BY kaisai_date DESC, post_time, jyo_cd")
            return list(cur.fetchall())
        finally:
            cur.close()

    # ---- flow 用の読み出し --------------------------------------------------
    def races_between(self, d_from: str, d_to: str) -> list[tuple]:
        cur = self.conn.cursor()
        try:
            cur.execute(
                "SELECT race_id, kaisai_date, jyo_cd, race_num, post_time"
                " FROM nar_race WHERE kaisai_date BETWEEN %s AND %s"
                "   AND post_time ~ '^[0-9]{1,2}:[0-9]{2}$'"
                " ORDER BY kaisai_date, post_time, jyo_cd", (d_from, d_to))
            return list(cur.fetchall())
        finally:
            cur.close()

    def snapshots_for(self, race_id: str) -> list[tuple]:
        """(observed_at, umaban, tan_odds) を時刻順に。★締切で切らずに全部返す。

        切り分けは flow 側で行う。ここで落とすと、何を見て何を捨てたのかが
        呼び出し側から見えなくなる。
        """
        cur = self.conn.cursor()
        try:
            cur.execute(
                "SELECT observed_at, umaban, tan_odds FROM nar_o1"
                " WHERE race_id = %s AND tan_odds IS NOT NULL"
                " ORDER BY observed_at, umaban", (race_id,))
            return list(cur.fetchall())
        finally:
            cur.close()

    def tansho_payouts(self, d_from: str, d_to: str) -> dict[str, dict[str, int]]:
        """{race_id: {馬番: 払戻円}}。単勝のみ。"""
        cur = self.conn.cursor()
        try:
            cur.execute(
                "SELECT race_id, kumi, yen FROM nar_payout"
                " WHERE bet_type = '単勝' AND kaisai_date BETWEEN %s AND %s",
                (d_from, d_to))
            out: dict[str, dict[str, int]] = {}
            for rid, kumi, yen in cur.fetchall():
                out.setdefault(rid, {})[str(kumi)] = int(yen)
            return out
        finally:
            cur.close()

    def races_with_payout(self, d_from: str, d_to: str) -> set[str]:
        cur = self.conn.cursor()
        try:
            cur.execute(
                "SELECT DISTINCT race_id FROM nar_payout"
                " WHERE kaisai_date BETWEEN %s AND %s", (d_from, d_to))
            return {r[0] for r in cur.fetchall()}
        finally:
            cur.close()
