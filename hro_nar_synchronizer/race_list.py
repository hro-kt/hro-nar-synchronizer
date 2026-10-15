"""開催日のレース一覧。

★`top/race_list.html` は JS 描画で、GET しても race_id が1件も入っていない。
  実体は `top/race_list_sub.html?kaisai_date=YYYYMMDD`(2026-10-15 実測で48レース)。
★race_id(12桁)には**開催日が入っていない**(年+場+回+日+R)。日付はここで持ち回る。
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass

from .tracks import deadline_sec, describe, is_nar, jyo_code, race_num

LIST_URL = "https://nar.netkeiba.com/top/race_list_sub.html?kaisai_date={date}"

_ITEM_RE = re.compile(r'<li class="RaceList_DataItem.*?</li>', re.S)
_RID_RE = re.compile(r"race_id=(\d{12})")
_TIME_RE = re.compile(r"<span>(\d{1,2}:\d{2})</span>")
_TITLE_RE = re.compile(r'<span class="ItemTitle">(.*?)</span>', re.S)
_TOSU_RE = re.compile(r"(\d{1,2})頭")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Race:
    race_id: str
    kaisai_date: str          # YYYYMMDD
    jyo_cd: str
    race_num: str
    post_time: str | None     # HH:MM
    title: str = ""
    tosu: int | None = None

    def describe(self) -> str:
        return f"{describe(self.race_id)} {self.post_time or '--:--'} {self.title}"

    def deadline_sec(self, *, spat4: bool = False) -> int:
        return deadline_sec(self.race_id, spat4=spat4)


def parse_list(html: str, date: str) -> list[Race]:
    out: list[Race] = []
    seen: set[str] = set()
    for item in _ITEM_RE.findall(html):
        mid = _RID_RE.search(item)
        if not mid:
            continue
        rid = mid.group(1)
        if rid in seen or not is_nar(rid):
            continue          # ★中央を混ぜない。混入で検証を汚染した前例がある
        seen.add(rid)
        mt = _TIME_RE.search(item)
        mti = _TITLE_RE.search(item)
        mto = _TOSU_RE.search(_TAG_RE.sub(" ", item))
        out.append(Race(
            race_id=rid, kaisai_date=date, jyo_cd=jyo_code(rid),
            race_num=race_num(rid),
            post_time=mt.group(1) if mt else None,
            title=_TAG_RE.sub("", mti.group(1)).strip() if mti else "",
            tosu=int(mto.group(1)) if mto else None))
    return sorted(out, key=lambda r: (r.post_time or "99:99", r.jyo_cd))


def fetch_list(date: str, *, timeout: float = 20.0, opener=None) -> list[Race]:
    req = urllib.request.Request(
        LIST_URL.format(date=date),
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ja"})
    _open = opener or urllib.request.urlopen
    with _open(req, timeout=timeout) as r:
        raw = r.read()
    return parse_list(raw.decode("utf-8", errors="replace"), date)
