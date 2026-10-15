"""レース結果と払戻。

★オッズだけ貯めても ROI は計算できない。着順と払戻が無いと検証が1行もできない。
  結果は netkeiba に残るので後から埋められるが、**パーサは今作る**。
  3ヶ月後にバグが見つかると3ヶ月分の検証が止まる。

★踏みやすい罠(2026-10-15 実ページで確認):
  - 枠番は <td class="Num Waku5">、馬番は <td class="Num Waku">。
    **数字の有無でしか区別できない**。class 名で引くと取り違える。
    td.Num の出現順(1つ目=枠、2つ目=馬番)で取る。
  - <span class="OddsPeople"> は**人気**、<span class="Odds_Ninki"> は**オッズ**。
    名前が逆。払戻の「単勝5番 540円 4人気」と突き合わせて確認した。
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field

RESULT_URL = "https://nar.netkeiba.com/race/result.html?race_id={race_id}"

# ★このページは空白が不規則。`<span  class="Odds_Ninki">` のように**空白が2個**
#   入る箇所がある(2026-10-15 実測)。`<span class="…"` と決め打ちすると静かに外れ、
#   オッズと払戻が丸ごと欠ける。タグと class の間は必ず \s+ で受ける。
_TR_RE = re.compile(r"<tr[^>]*>.*?</tr>", re.S)
_RANK_RE = re.compile(r'<div\s+class="Rank">\s*(\d+)\s*</div>')
_NUM_TD_RE = re.compile(r'<td\s+class="Num[^"]*">\s*<div>\s*(\d{1,2})\s*</div>', re.S)
_HORSE_RE = re.compile(r'id="umalink_(\d+)"[^>]*title="([^"]*)"')
# ★人気とオッズは**セルの位置**で取る。span の class は行によって付いたり付かなかったり
#   する(3着馬は <span >26.0</span> で class が無かった)。class を当てにすると
#   一部の馬だけ静かに欠ける。Txt_C が人気、Txt_R がオッズ。
# ★クラスは隣接しない。`<td class="Odds BgBlue02 Txt_C">` のように**間に別のクラスが
#   挟まる**(着色用の BgBlue02 等)。隣接を前提にすると、その馬だけ静かに欠ける。
_NINKI_TD_RE = re.compile(r'<td\s+class="[^"]*\bOdds\b[^"]*\bTxt_C\b[^"]*"\s*>(.*?)</td>', re.S)
_ODDS_TD_RE = re.compile(r'<td\s+class="[^"]*\bOdds\b[^"]*\bTxt_R\b[^"]*"\s*>(.*?)</td>', re.S)
_INT_RE = re.compile(r"(\d+)")
_FLOAT_RE = re.compile(r"([\d,]+\.\d)")
_TIME_RE = re.compile(r'<span\s+class="RaceTime">\s*([\d:.]+)\s*</span>')
_TAG_RE = re.compile(r"<[^>]+>")

# 払戻。<tr class="Tansho"><th>単勝</th><td class="Result">…<td class="Payout">540円
_PAY_TR_RE = re.compile(r'<tr\s+class="(\w+)"\s*>(.*?)</tr>', re.S)
_PAY_RESULT_RE = re.compile(r'<td\s+class="Result"\s*>(.*?)</td>', re.S)
_PAY_AMOUNT_RE = re.compile(r'<td\s+class="Payout"\s*>(.*?)</td>', re.S)
_PAY_NINKI_RE = re.compile(r'<td\s+class="Ninki"\s*>(.*?)</td>', re.S)
_YEN_RE = re.compile(r"([\d,]+)円")

BET_TYPES = {
    "Tansho": "単勝", "Fukusho": "複勝", "Wakuren": "枠連", "Umaren": "馬連",
    "Wide": "ワイド", "Wakutan": "枠単", "Umatan": "馬単",
    "Fuku3": "三連複", "Tan3": "三連単",
}


@dataclass
class Finish:
    umaban: str
    chakujun: int | None          # 着順。取消/除外は None
    waku: str | None = None
    horse_id: str = ""
    horse_name: str = ""
    ninki: int | None = None
    tan_odds: float | None = None   # 確定単勝オッズ
    time: str = ""


@dataclass
class Payout:
    bet_type: str                 # '単勝' 等
    kumi: str                     # 組番 '5' / '5-10' など
    yen: int                      # 100円あたりの払戻
    ninki: int | None = None


@dataclass
class RaceResult:
    race_id: str
    finishes: list[Finish] = field(default_factory=list)
    payouts: list[Payout] = field(default_factory=list)
    confirmed: bool = False       # 着順が出ているか


def result_url(race_id: str) -> str:
    return RESULT_URL.format(race_id=race_id)


def parse_finishes(html: str) -> list[Finish]:
    i = html.find("ResultTableWrap")
    if i < 0:
        return []
    out: list[Finish] = []
    for tr in _TR_RE.findall(html[i:]):
        nums = _NUM_TD_RE.findall(tr)
        if len(nums) < 2:
            continue              # ヘッダ行や別表
        mr = _RANK_RE.search(tr)
        mh = _HORSE_RE.search(tr)
        mn = _NINKI_TD_RE.search(tr)
        mo = _ODDS_TD_RE.search(tr)
        mn = _INT_RE.search(_TAG_RE.sub(" ", mn.group(1))) if mn else None
        mo = _FLOAT_RE.search(_TAG_RE.sub(" ", mo.group(1))) if mo else None
        mt = _TIME_RE.search(tr)
        out.append(Finish(
            waku=nums[0], umaban=nums[1],          # ★順序で取る。class 名は当てにしない
            chakujun=int(mr.group(1)) if mr else None,
            horse_id=mh.group(1) if mh else "",
            horse_name=mh.group(2) if mh else "",
            ninki=int(mn.group(1)) if mn else None,
            tan_odds=float(mo.group(1).replace(",", "")) if mo else None,
            time=mt.group(1) if mt else ""))
    return out


def parse_payouts(html: str) -> list[Payout]:
    i = html.find("Payout_Detail_Table")
    if i < 0:
        return []
    out: list[Payout] = []
    for cls, body in _PAY_TR_RE.findall(html[i:]):
        name = BET_TYPES.get(cls)
        if name is None:
            continue
        mres, mpay = _PAY_RESULT_RE.search(body), _PAY_AMOUNT_RE.search(body)
        if not (mres and mpay):
            continue
        groups = _groups(mres.group(1))
        yens = [int(y.replace(",", "")) for y in _YEN_RE.findall(mpay.group(1))]
        mnin = _PAY_NINKI_RE.search(body)
        ninkis = [int(n) for n in re.findall(r"(\d+)人気", mnin.group(1))] if mnin else []
        for k, (g, y) in enumerate(zip(groups, yens)):
            out.append(Payout(bet_type=name, kumi=g, yen=y,
                              ninki=ninkis[k] if k < len(ninkis) else None))
    return out


def _groups(result_html: str) -> list[str]:
    """払戻の組番を取り出す。

    ★賭式で markup が違う(2026-10-15 実測):
      単勝/複勝 … <div><span>5</span></div><div><span></span></div>… (空 span が区切り)
      ワイド等  … <ul><li><span>5</span></li><li><span>10</span></li></ul> (ul が1組)
      どちらか一方だけを想定すると、ワイドが '5-10-5-6-6-10' のように
      全部つながった1組になる(実際そうなった)。
    """
    uls = re.findall(r"<ul\b.*?</ul>", result_html, re.S)
    if uls:
        out = []
        for u in uls:
            nums = [t.strip() for t in re.findall(r"<span[^>]*>(.*?)</span>", u, re.S)]
            nums = [n for n in nums if n]
            if nums:
                out.append("-".join(nums))
        return out
    spans = [t.strip() for t in re.findall(r"<span[^>]*>(.*?)</span>", result_html, re.S)]
    groups: list[str] = []
    cur: list[str] = []
    for sp in spans:
        if sp:
            cur.append(sp)
        elif cur:
            groups.append("-".join(cur))
            cur = []
    if cur:
        groups.append("-".join(cur))
    return groups


def parse(html: str, race_id: str) -> RaceResult:
    fin = parse_finishes(html)
    return RaceResult(race_id=race_id, finishes=fin, payouts=parse_payouts(html),
                      confirmed=any(f.chakujun is not None for f in fin))


def fetch(race_id: str, *, timeout: float = 20.0, opener=None) -> RaceResult:
    req = urllib.request.Request(
        result_url(race_id),
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ja"})
    _open = opener or urllib.request.urlopen
    with _open(req, timeout=timeout) as r:
        raw = r.read()
    return parse(raw.decode("utf-8", errors="replace"), race_id)
