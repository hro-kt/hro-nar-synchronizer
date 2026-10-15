"""測定器。★差が出たときにはっきり言うことが仕事。黙って通さない。"""

from hro_nar_synchronizer.odds_page import OddsPage
from hro_nar_synchronizer.probe import compare_login


def _page(tan):
    return OddsPage(race_id="202645101510", tan=tan)


def test_difference_between_member_and_non_member_is_flagged(monkeypatch):
    from hro_nar_synchronizer import probe as pr

    monkeypatch.setattr(pr, "cookie_header", lambda p=None: "a=1")

    def _fetch(rid, cookies=None, **kw):
        return _page({"1": 2.0} if cookies else {"1": 2.4})

    r = compare_login("202645101510", rounds=2, gap=0.0, fetch_fn=_fetch)
    assert r["agree"] == 0
    assert "同じものを見ていません" in r["verdict"]
    assert r["rows"][0]["diff"] == {"1": (2.4, 2.0)}


def test_identical_values_are_reported_as_such(monkeypatch):
    from hro_nar_synchronizer import probe as pr

    monkeypatch.setattr(pr, "cookie_header", lambda p=None: "a=1")
    r = compare_login("202645101510", rounds=3, gap=0.0,
                      fetch_fn=lambda rid, cookies=None, **kw: _page({"1": 2.0}))
    assert r["agree"] == 3
    assert "変わりません" in r["verdict"]
