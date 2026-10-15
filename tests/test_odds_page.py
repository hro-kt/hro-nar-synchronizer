"""実ページの markup を固定する(2026-10-15 川崎10Rで取得)。"""

from hro_nar_synchronizer.odds_page import (
    OddsPage, parse_fuku, parse_post_time, parse_tan,
)

# ★単勝の行は <td class="W31">馬番</td> だが、**複勝の行は class が無い**。
#   W31 を当てにすると複勝が丸ごと0件になる(実際そうなった)。
#   両方に必ずあるのは chk_b1_<馬番> / chk_b2_<馬番>。
HTML = '''
<div class="RaceOdds_HorseList Tanfuku" id = "odds_tan_block">
<table class="RaceOdds_HorseList_Table">
<tr><th class="Waku">枠</th><th class="W31">馬番</th><th>オッズ</th></tr>
<tr><td class="Waku1">1</td><td class="W31">1</td>
 <td class="Horse_Select"><input id="chk_b1_1" name="tan[]" value="a5-45-10_b1_c0_1"/></td>
 <td class="Horse_Name">マインドユアミモザ</td>
 <td class="Odds"><span class="Odds ">110.2</span></td></tr>
<tr><td class="Waku5">5</td><td class="W31">9</td>
 <td class="Horse_Select"><input id="chk_b1_9" name="tan[]" value="a5-45-10_b1_c0_9"/></td>
 <td class="Horse_Name">テスト</td>
 <td class="Odds"><span class="Odds ">1,073.6</span></td></tr>
</table></div>
<div class="RaceOdds_HorseList Tanfuku" id = "odds_fuku_block">
<table class="RaceOdds_HorseList_Table">
<tr><th class="Waku">枠</th><th class="W31">馬番</th><th>オッズ</th></tr>
<tr><td class="Waku1">1</td><td>1</td>
 <td class="Horse_Select"><input id="chk_b2_1" name="fuku[]" value="a5-45-10_b2_c0_1"/></td>
 <td class="Horse_Name">マインドユアミモザ</td>
 <td class="Odds"><span class="Odds ">16.5 - 27.9</span></td></tr>
<tr><td class="Waku5">5</td><td>9</td>
 <td class="Horse_Select"><input id="chk_b2_9" name="fuku[]" value="a5-45-10_b2_c0_9"/></td>
 <td class="Horse_Name">テスト</td>
 <td class="Odds"><span class="Odds ">2.1 - 3.4</span></td></tr>
</table></div>
<div>19:40 発走</div>
'''


def test_parses_win_odds_with_commas():
    assert parse_tan(HTML) == {"1": 110.2, "9": 1073.6}


def test_place_odds_are_parsed_although_the_cell_has_no_class():
    """★複勝の馬番セルには class が無い。ここを落とすと複勝が丸ごと消える。"""
    assert parse_fuku(HTML) == {"1": (16.5, 27.9), "9": (2.1, 3.4)}


def test_umaban_is_not_the_waku():
    """★枠5 の馬番は 9。取り違えると別の馬にオッズが付いたまま誰も気づかない。"""
    tan = parse_tan(HTML)
    assert "9" in tan and tan["9"] == 1073.6
    assert "5" not in tan


def test_place_block_does_not_leak_into_win():
    assert parse_tan(HTML)["1"] == 110.2       # 複勝の 16.5 で上書きされない


def test_post_time():
    assert parse_post_time(HTML) == "19:40"
    assert parse_post_time("発走は未定") is None


def test_digest_ignores_time_but_follows_values():
    a = OddsPage(race_id="r", tan={"1": 2.0}, fuku={"1": (1.1, 1.3)}, latency_ms=10)
    b = OddsPage(race_id="r", tan={"1": 2.0}, fuku={"1": (1.1, 1.3)}, latency_ms=999)
    c = OddsPage(race_id="r", tan={"1": 2.1}, fuku={"1": (1.1, 1.3)})
    assert a.digest_source() == b.digest_source()
    assert a.digest_source() != c.digest_source()
