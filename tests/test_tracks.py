import pytest

from hro_nar_synchronizer.tracks import (
    NANKAN, deadline_sec, describe, is_nankan, is_nar, jyo_code, race_num,
)


def test_nar_and_central_are_separated():
    """★中央を地方に混ぜない。混入で検証を丸ごと汚染した前例がある。"""
    assert is_nar("202645101510")          # 川崎
    assert is_nar("202630101501")          # 門別(境界30)
    for jyo in ("01", "05", "06", "09", "10"):
        assert not is_nar(f"2026{jyo}101501"), jyo


def test_race_id_must_be_twelve_digits():
    with pytest.raises(ValueError):
        jyo_code("2026451015010000")       # JV の16桁は受け付けない
    with pytest.raises(ValueError):
        jyo_code("")


def test_deadline_is_two_minutes_by_default():
    assert deadline_sec("202645101510") == 120
    assert deadline_sec("202650101510") == 120                 # 園田
    assert deadline_sec("202650101510", spat4=True) == 120     # 南関東以外は変わらない


def test_spat4_gives_nankan_one_more_minute():
    assert NANKAN == {"42", "43", "44", "45"}   # 浦和/船橋/大井/川崎
    for jyo in NANKAN:
        rid = f"2026{jyo}101510"
        assert is_nankan(rid)
        assert deadline_sec(rid, spat4=True) == 60, rid


def test_describe_and_race_num():
    assert describe("202645101510") == "川崎(45) 10R"
    assert race_num("202645101510") == "10"
