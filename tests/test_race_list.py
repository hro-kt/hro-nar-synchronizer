"""開催一覧。★race_list.html は JS 描画で race_id が1件も入らない。実体は race_list_sub。"""

from hro_nar_synchronizer.race_list import LIST_URL, parse_list

HTML = '''
<li class="RaceList_DataItem ">
 <a href="../race/result.html?race_id=202630101501&rf=race_list">
 <div class="Race_Num"><span>1R</span></div>
 <div class="RaceList_ItemTitle"><span class="ItemTitle">夏いちごの町...(2歳)</span></div>
 <div class="RaceData"><span>14:25</span><span class="Dart">ダ1500m</span> 9頭</div>
 </a></li>
<li class="RaceList_DataItem ">
 <a href="../race/shutuba.html?race_id=202645101510&rf=race_list">
 <div class="Race_Num"><span>10R</span></div>
 <div class="RaceList_ItemTitle"><span class="ItemTitle">サルビアカップ</span></div>
 <div class="RaceData"><span>19:40</span><span class="Dart">ダ1600m</span> 11頭</div>
 </a></li>
<li class="RaceList_DataItem ">
 <a href="../race/shutuba.html?race_id=202605040811&rf=race_list">
 <div class="Race_Num"><span>11R</span></div>
 <div class="RaceData"><span>15:45</span> 18頭</div>
 </a></li>
'''


def test_parses_races_with_post_time_and_field_size():
    rs = parse_list(HTML, "20261015")
    assert [r.race_id for r in rs] == ["202630101501", "202645101510"]
    門別 = rs[0]
    assert 門別.post_time == "14:25" and 門別.tosu == 9
    assert 門別.jyo_cd == "30" and 門別.race_num == "01"
    assert "夏いちご" in 門別.title


def test_central_races_are_excluded():
    """★中央(場コード05)を混ぜない。混入で検証を汚染した前例がある。"""
    assert all(r.jyo_cd >= "30" for r in parse_list(HTML, "20261015"))
    assert "202605040811" not in [r.race_id for r in parse_list(HTML, "20261015")]


def test_kaisai_date_is_carried_because_race_id_has_none():
    """★race_id は 年+場+回+日+R で、開催日が入っていない。"""
    for r in parse_list(HTML, "20261015"):
        assert r.kaisai_date == "20261015"


def test_sorted_by_post_time():
    rs = parse_list(HTML, "20261015")
    assert [r.post_time for r in rs] == ["14:25", "19:40"]


def test_uses_the_sub_endpoint():
    """race_list.html は JS 描画で中身が無い。sub を使っていること。"""
    assert "race_list_sub.html" in LIST_URL
