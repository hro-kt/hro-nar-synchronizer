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
    if st.is_broken():
        click.echo("  ✗ 1件も読めませんでした。ページの構造が変わった可能性があります")
        raise SystemExit(1)
    if st.silent_races:
        click.echo(f"  ⚠ 読めないまま終わったレース: {len(st.silent_races)} 件")


@cli.command("results")
@click.option("--date", "date_", default=None, help="YYYYMMDD(既定 当日 JST)")
@click.option("--force", is_flag=True, help="既に入っているレースも取り直す")
def results_cmd(date_, force) -> None:
    """着順と払戻を取り込む。

    ★オッズだけでは ROI を計算できない。結果は netkeiba に残るので後から
      埋められるが、取り込みが止まっていると検証も止まる。開催翌日に流す。
    """
    from .db import Store, connect
    from .race_list import Race
    from .result_page import fetch as fetch_result

    cfg = load_config()
    conn, drv = connect(cfg)
    store = Store(conn, drv)
    store.apply_schema(cfg.schema_path)
    d = date_ or _today()
    rows = store.races_for(d)
    if not rows:
        click.echo(f"{d} のレースが nar_race にありません(先に races を実行)")
        raise SystemExit(1)

    done = set() if force else store.races_with_results(d)
    ok = skipped = failed = 0
    for r in rows:
        rid = r[0]
        if rid in done:
            skipped += 1
            continue
        try:
            res = fetch_result(rid)
        except Exception as e:  # noqa: BLE001
            failed += 1
            click.echo(f"  ✗ {rid} 取得に失敗: {type(e).__name__}: {str(e)[:80]}")
            continue
        if not res.confirmed:
            click.echo(f"  … {rid} はまだ確定していません")
            continue
        store.save_result(res, d)
        ok += 1
        click.echo(f"  ○ {rid} 着順{len(res.finishes)}頭 / 払戻{len(res.payouts)}件")
    click.echo(f"\n  取込 {ok} / 既存 {skipped} / 失敗 {failed}")
    raise SystemExit(1 if failed else 0)


@cli.command("coverage")
@click.option("--date", "date_", default=None, help="YYYYMMDD(省略で直近7日)")
@click.option("--min-snapshots", type=int, default=5,
              help="締切前にこの数より少ないレースを問題として挙げる")
def coverage_cmd(date_, min_snapshots) -> None:
    """★録れているかを確認する。「録れているつもり」が一番危ない。

    markup が変われば収集は0件になるが、収集側は黙って待つだけなので、
    数ヶ月後に backtest しようとして初めて気づくことになる。
    """
    from .db import Store, connect

    cfg = load_config()
    conn, drv = connect(cfg)
    store = Store(conn, drv)
    rows = store.coverage(date_)
    if not rows:
        click.echo("対象がありません")
        raise SystemExit(1)

    bad = [r for r in rows if (r[7] or 0) < min_snapshots]
    nores = [r for r in rows if (r[12] or 0) == 0]
    click.echo(f"=== 被覆 {len(rows)} レース ===")
    for r in rows[:40]:
        mark = "✗" if (r[7] or 0) < min_snapshots else "○"
        lag = f"{r[11]:.0f}s" if r[11] is not None else "--"
        click.echo(f"  {mark} {r[1]} {r[2]}-{r[3]}R {r[4] or '--:--'}"
                   f"  断面 {r[6] or 0}(締切前 {r[7] or 0})  締切まで {lag}"
                   f"  結果 {r[12] or 0}行")
    if len(rows) > 40:
        click.echo(f"  … 他 {len(rows) - 40} レース")
    click.echo("")
    click.echo(f"  締切前の断面が {min_snapshots} 未満: {len(bad)} レース")
    click.echo(f"  結果が未取込            : {len(nores)} レース")
    if bad:
        click.echo("  ★0 が並ぶなら収集が止まっているか、ページの構造が変わっています")
    raise SystemExit(1 if bad else 0)


@cli.command("flow-backtest")
@click.option("--from", "d_from", required=True, help="YYYYMMDD")
@click.option("--to", "d_to", default=None, help="YYYYMMDD(既定 --from と同日)")
@click.option("--lead", type=int, default=60, help="締切の何秒前の断面を使うか")
@click.option("--flow-min", type=int, default=30, help="何分さかのぼった断面と比べるか")
@click.option("--min-score", type=float, default=0.25)
@click.option("--ninki-from", type=int, default=0)
@click.option("--ninki-to", type=int, default=99)
@click.option("--max-per-race", type=int, default=1)
@click.option("--spat4", is_flag=True, help="南関東の締切を発走1分前として扱う")
def flow_backtest(d_from, d_to, lead, flow_min, min_score, ninki_from, ninki_to,
                  max_per_race, spat4) -> None:
    """flow_tan(地方版)で単勝を買ったらどうだったかを出す。

    ★基準は発走ではなく**締切**(発走2分前 / SPAT4 の南関東は1分前)。
      締切後のオッズは確定オッズで、賭けられない価格。使えば未来を見たことになる。
    ★中央の数字とは**別に**見ること。同じ数式でも市場が違う。
    """
    from .db import Store, connect
    from .flow import FlowConfig, backtest

    cfg_app = load_config()
    conn, drv = connect(cfg_app)
    store = Store(conn, drv)
    cfg = FlowConfig(lead_sec=lead, flow_min=flow_min, spat4=spat4)
    out = backtest(store, d_from, d_to or d_from, cfg, min_score=min_score,
                   ninki_from=ninki_from, ninki_to=ninki_to,
                   max_per_race=max_per_race)

    click.echo(f"=== flow_tan 地方 {out['d_from']}〜{out['d_to']} ===")
    click.echo(f"  設定  締切-{lead}s と その{flow_min}分前 / しきい値 {min_score}"
               f" / 人気 {ninki_from}-{ninki_to} / 1レース{max_per_race}点"
               f"{' / SPAT4' if spat4 else ''}")
    click.echo(f"  対象レース      : {out['races']}")
    click.echo(f"  スコア算出できた: {out['races_scored']}")
    if out["skips"]:
        for k, v in sorted(out["skips"].items(), key=lambda kv: -kv[1]):
            click.echo(f"    算出できず({k}): {v}")
    if out["races_without_payout"]:
        click.echo(f"  払戻が未取込    : {out['races_without_payout']}"
                   "  ★ results を先に流してください")
    click.echo(f"  購入            : {out['bets']} 点 / {out['staked']:,} 円")
    click.echo(f"  払戻            : {out['returned']:,} 円")
    if out["roi"] is not None:
        click.echo(f"  ROI             : {out['roi']:.4f}"
                   f"  (的中 {out['hits']}/{out['bets']}"
                   f" = {out['hit_rate']:.1%})")
        click.echo(f"  平均の窓/ズレ   : {out['avg_window_sec']:.0f}秒"
                   f" / {out['avg_lag_sec']:.0f}秒")
    else:
        click.echo("  ROI             : 購入0点のため算出できません")
    # ★1本の数字で判断しない。2窓 OOS を取るまでは参考値。
    click.echo("")
    click.echo("  ※ 単一期間の数字です。採否は独立した2窓 OOS で決めること")
    raise SystemExit(0)


@cli.command("probe")
@click.option("--race-id", required=True, help="netkeiba の race_id 12桁(地方)")
@click.option("--date", "date_", default=None, help="YYYYMMDD(既定 当日 JST)")
@click.option("--compare-login", "compare", is_flag=True,
              help="同じ瞬間にログインあり/なしで取って突き合わせる。"
                   "★締切2分前に流して、非会員が遅れた値を見ていないか確かめる")
@click.option("--seconds", type=float, default=900.0)
@click.option("--interval", type=float, default=3.0)
@click.option("--spat4", is_flag=True, help="南関東の締切を発走1分前として判定する")
def probe_cmd(race_id, date_, compare, seconds, interval, spat4) -> None:
    """前提が変わっていないかを測る(収集とは別。DBに書かない)。"""
    from .probe import cadence, compare_login

    cfg = load_config()
    state = cfg.collect.state_path or None
    if compare:
        r = compare_login(race_id, state_path=state)
        for row in r["rows"]:
            click.echo(f"  {row['at'][11:19]}  非会員{row['n_anon']}頭 / "
                       f"会員{row['n_auth']}頭  差分: {row['diff'] or 'なし'}")
        click.echo("")
        click.echo(f"{r['rounds']}回中 一致 {r['agree']}回 → {r['verdict']}")
        raise SystemExit(0 if r["agree"] == r["rounds"] else 1)

    r = cadence(race_id, date_ or _today(), seconds=seconds, interval=interval,
                spat4=spat4, state_path=state, log=click.echo)
    click.echo("")
    click.echo(f"  変化 {r['changes']}回 / 更新間隔の中央値 {r['gap_median_sec']}秒"
               f" / 締切時点で {r['lag_to_deadline_sec']}秒前の情報"
               f" / キャッシュHit {r['cache_hits']}")
    click.echo(("○ flow_tan を作れる粒度です" if r["ok"]
                else "✗ この粒度では T-60s の断面を作れません"))
    raise SystemExit(0 if r["ok"] else 1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
