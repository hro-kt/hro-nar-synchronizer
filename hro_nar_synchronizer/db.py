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
