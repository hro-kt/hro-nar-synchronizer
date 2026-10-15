"""結果・払戻。実ページ(2026-10-15 川崎10R)で踏んだ罠を全部固定する。

★このページは markup が不規則で、推測で書くと**一部だけ静かに欠ける**。
  3回別々の形で踏んだので、どれもテストで押さえる。
"""

from hro_nar_synchronizer.result_page import parse, parse_finishes, parse_payouts

# 罠1: <span  class="Odds_Ninki"> のように**空白が2個**入る
# 罠2: 3着馬のオッズは <span >26.0</span> で**class が無い**
# 罠3: <td class="Odds BgBlue02 Txt_C"> のように**クラスの間に別のクラスが挟まる**
# 罠4: 枠番は <td class="Num Waku5">、馬番は <td class="Num Waku">(数字の有無だけの差)
HTML = '''
<div class="ResultTableWrap">
<table>
<tr class="Header"><th class="Result_Num">着順</th></tr>
<tr >
 <td class="Result_Num"><div class="Rank">1</div></td>
 <td class="Num Waku5"><div>5</div></td>
 <td class="Num Waku"><div>5</div></td>
 <td class="Horse_Info"><span class="Horse_Name">
   <a href="/horse/2023103823/" id="umalink_2023103823" title="ワンモメンタム">ワンモメンタム</a></span></td>
 <td class="Time"><span class="RaceTime">1:43.1</span></td>
 <td class="Odds  Txt_C"><span class="OddsPeople">4</span></td>
 <td class="Odds Txt_R"><span  class="Odds_Ninki">5.4</span></td>
</tr>
<tr >
 <td class="Result_Num"><div class="Rank">2</div></td>
 <td class="Num Waku8"><div>8</div></td>
 <td class="Num Waku"><div>10</div></td>
 <td class="Horse_Info"><span class="Horse_Name">
   <a id="umalink_2022102572" title="ファリードゥーン">ファリードゥーン</a></span></td>
 <td class="Time"><span class="RaceTime">クビ</span></td>
 <td class="Odds BgBlue02 Txt_C"><span class="OddsPeople">2</span></td>
 <td class="Odds Txt_R"><span  class="Odds_Ninki">4.8</span></td>
</tr>
<tr >
 <td class="Result_Num"><div class="Rank">3</div></td>
 <td class="Num Waku6"><div>6</div></td>
 <td class="Num Waku"><div>6</div></td>
 <td class="Horse_Info"><span class="Horse_Name">
   <a id="umalink_2021100001" title="エレファントラン">エレファントラン</a></span></td>
 <td class="Odds Txt_C"><span class="OddsPeople">8</span></td>
 <td class="Odds Txt_R"><span >26.0</span></td>
</tr>
</table></div>
<table class="Payout_Detail_Table">
<tr class="Tansho"><th>単勝</th>
 <td class="Result"><div><span>5</span></div><div><span></span></div><div><span></span></div></td>
 <td class="Payout"><span>540円</span></td>
 <td class="Ninki"><span>4人気</span></td></tr>
<tr class="Fukusho"><th>複勝</th>
 <td class="Result"><div><span>5</span></div><div><span></span></div><div><span></span></div>
  <div><span>10</span></div><div><span></span></div><div><span></span></div>
  <div><span>6</span></div><div><span></span></div><div><span></span></div></td>
 <td class="Payout"><span>170円<br />170円<br />370円</span></td>
 <td class="Ninki"><span>2人気<br />3人気<br />6人気</span></td></tr>
<tr class="Wide"><th>ワイド</th>
 <td class="Result">
  <ul><li><span>5</span></li><li><span>10</span></li><li></li></ul>
  <ul><li><span>5</span></li><li><span>6</span></li><li></li></ul>
  <ul><li><span>6</span></li><li><span>10</span></li><li></li></ul></td>
 <td class="Payout"><span>510円<br />1,060円<br />980円</span></td>
 <td class="Ninki"><span>6人気<br />16人気<br />13人気</span></td></tr>
<tr class="Tan3"><th>三連単</th>
 <td class="Result"><ul><li><span>5</span></li><li><span>10</span></li><li><span>6</span></li></ul></td>
 <td class="Payout"><span>27,820円</span></td>
 <td class="Ninki"><span>110人気</span></td></tr>
</table>
'''


def test_umaban_is_not_the_waku():
    """★枠番は Num Waku5、馬番は Num Waku。数字の有無しか差が無い。

    2着馬は枠8・馬番10。取り違えると全頭ぶんオッズが別の馬に付く。
    """
    f = {x.chakujun: x for x in parse_finishes(HTML)}
    assert (f[1].waku, f[1].umaban) == ("5", "5")
    assert (f[2].waku, f[2].umaban) == ("8", "10")
    assert (f[3].waku, f[3].umaban) == ("6", "6")


def test_double_space_before_class_does_not_break_odds():
    """★<span  class="Odds_Ninki"> と空白が2個。決め打ちすると静かに外れる。"""
    f = {x.chakujun: x for x in parse_finishes(HTML)}
    assert f[1].tan_odds == 5.4
    assert f[2].tan_odds == 4.8


def test_odds_without_a_class_is_still_read():
    """★3着馬は <span >26.0</span> で class が無い。class を当てにしない。"""
    f = {x.chakujun: x for x in parse_finishes(HTML)}
    assert f[3].tan_odds == 26.0


def test_extra_class_between_odds_and_txt_c():
    """★<td class="Odds BgBlue02 Txt_C"> のように間に別のクラスが挟まる。"""
    f = {x.chakujun: x for x in parse_finishes(HTML)}
    assert f[2].ninki == 2, "着色用クラスが挟まった行だけ人気が欠けている"
    assert [x.ninki for x in parse_finishes(HTML)] == [4, 2, 8]


def test_nothing_is_silently_missing():
    """★一部だけ欠ける壊れ方をするので、欠損ゼロを明示的に確かめる。"""
    fs = parse_finishes(HTML)
    assert len(fs) == 3
    assert all(x.ninki is not None for x in fs)
    assert all(x.tan_odds is not None for x in fs)
    assert all(x.horse_name for x in fs)


def test_horse_id_and_name():
    f = parse_finishes(HTML)[0]
    assert f.horse_id == "2023103823" and f.horse_name == "ワンモメンタム"


def test_payouts_cover_every_bet_type():
    ps = parse_payouts(HTML)
    got = {(p.bet_type, p.kumi): (p.yen, p.ninki) for p in ps}
    assert got[("単勝", "5")] == (540, 4)
    assert got[("複勝", "10")] == (170, 3)
    assert got[("三連単", "5-10-6")] == (27820, 110)


def test_wide_is_three_separate_combinations():
    """★ワイドは <ul> が1組。単複の <div><span> 方式で読むと
       '5-10-5-6-6-10' のように全部つながった1組になる(実際そうなった)。"""
    w = sorted((p.kumi, p.yen, p.ninki) for p in parse_payouts(HTML)
               if p.bet_type == "ワイド")
    assert w == [("5-10", 510, 6), ("5-6", 1060, 16), ("6-10", 980, 13)]


def test_commas_in_payout_are_handled():
    p = [x for x in parse_payouts(HTML) if x.bet_type == "三連単"][0]
    assert p.yen == 27820


def test_unconfirmed_race_is_marked():
    r = parse("<html>まだ発走前</html>", "202645101510")
    assert not r.confirmed and r.finishes == [] and r.payouts == []
