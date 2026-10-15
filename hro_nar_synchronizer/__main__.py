"""CLI。"""

from __future__ import annotations

import click

from .config import load_config


def _today() -> str:
    from .collector import now_jst
    return now_jst().strftime("%Y%m%d")


@click.group()
def cli() -> None:
    """地方競馬(NAR)のオッズ収集。JV-Link もブラウザも使わない。"""


@cli.command("init-db")
def init_db() -> None:
    """nar_* テーブルを作る(正本は hro-db/schema/36_nar_odds.sql)。"""
    from .db import Store, connect

    cfg = load_config()
    conn, drv = connect(cfg)
    Store(conn, drv).apply_schema(cfg.schema_path)
    click.echo(f"○ {cfg.schema_path} を適用しました({drv})")


@cli.command("races")
@click.option("--date", "date_", default=None, help="YYYYMMDD(既定 当日 JST)")
@click.option("--save/--no-save", default=True, help="DB に保存するか")
def races(date_, save) -> None:
    """開催日のレース一覧を取る。"""
    from .db import Store, connect
    from .race_list import fetch_list

    d = date_ or _today()
    rs = fetch_list(d)
    click.echo(f"=== {d} の地方 {len(rs)} レース ===")
    for r in rs:
        click.echo(f"  {r.describe()}  {r.tosu or '-'}頭")
    if save and rs:
        cfg = load_config()
        conn, drv = connect(cfg)
        n = Store(conn, drv).upsert_races(rs)
        click.echo(f"  → nar_race に {n} 件保存しました")
    if not rs:
        click.echo("  (開催なし、または一覧の構造が変わった可能性があります)")
        raise SystemExit(1)


@cli.command("collect")
@click.option("--date", "date_", default=None, help="YYYYMMDD(既定 当日 JST)")
@click.option("--spat4", is_flag=True,
              help="SPAT4 で買う前提。南関東の締切が発走1分前になる")
@click.option("--window-min", type=int, default=None, help="発走この分前から収集")
@click.option("--interval", type=float, default=None, help="1周の間隔(秒)")
@click.option("--max-seconds", type=float, default=None, help="この秒数で打ち切る(試運転用)")
@click.option("--dry-run", is_flag=True, help="DB に書かず、取得と表示だけ行う")
def collect_cmd(date_, spat4, window_min, interval, max_seconds, dry_run) -> None:
    """締切前後のオッズを記録し続ける。

    ★時系列オッズは後から取り戻せない。今日録らなかった日は永久に埋まらない。
    """
    from .collector import collect
    from .db import Store, connect
    from .race_list import Race, fetch_list

    cfg = load_config()
    c = cfg.collect
    d = date_ or _today()

    store = None
    if not dry_run:
        conn, drv = connect(cfg)
        store = Store(conn, drv)
        store.apply_schema(cfg.schema_path)

    rows = store.races_for(d) if store else []
    if rows:
        rs = [Race(race_id=r[0], kaisai_date=r[1], jyo_cd=r[2], race_num=r[3],
                   post_time=r[4], title=r[5] or "", tosu=r[6]) for r in rows]
        click.echo(f"=== {d}: nar_race から {len(rs)} レース ===")
    else:
        rs = fetch_list(d)
        click.echo(f"=== {d}: 一覧を取得 {len(rs)} レース ===")
        if store and rs:
            store.upsert_races(rs)
    if not rs:
        click.echo("  対象レースがありません")
        raise SystemExit(1)

    click.echo(f"  締切: {'SPAT4 南関東は発走1分前' if spat4 or c.spat4 else '発走2分前'}"
               f" / 発走 {window_min or c.window_min} 分前から"
               f" / {interval or c.interval_sec} 秒ごと"
               + ("  ★DRY-RUN(保存しません)" if dry_run else ""))
    st = collect(rs, store, spat4=spat4 or c.spat4,
                 window_min=window_min or c.window_min, grace_min=c.grace_min,
                 interval_sec=interval or c.interval_sec,
                 state_path=cfg.collect.state_path or None,
                 max_seconds=max_seconds, log=click.echo)
    click.echo("")
    click.echo("  " + st.line())
    if st.cache_hits > st.polls * 0.3:
        click.echo("  ★キャッシュ Hit が多いです。見ている値が古い可能性があります")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
