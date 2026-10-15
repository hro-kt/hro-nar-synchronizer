"""netkeiba(地方)のオッズページ。HTTP のみ。

★実測で確定したこと(2026-10-15):
  - ホストが違う: 地方は nar.netkeiba.com(中央の race. では開けない)
  - type=b1 が単複。素の index.html?race_id=… は b0 へ 302 する
  - **オッズ表はサーバ側で描画済み**。GET 一発で読める。Playwright 不要
  - 文字コードは **UTF-8**。meta に charset の記載が無いので推測に頼らない
  - markup が中央と全く違う。中央の id^="odds-1_" は存在しない
  - ページに「○時○分現在」が無い。自称時刻は取れないので、
    **こちらが読んだ時刻**しか手掛かりが無い
"""

from __future__ import annotations

import re
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

ODDS_URL = "https://nar.netkeiba.com/odds/index.html?type=b1&race_id={race_id}"

USER_AGENT = "Mozilla/5.0"

# ★行の読み方。
#   単勝ブロックの行は <td class="Waku5">5</td><td class="W31">9</td> だが、
#   **複勝ブロックの行は馬番セルに class が無い**(<td>9</td>)。W31 を当てにすると
#   複勝が丸ごと0件になる(2026-10-15 に実際にそうなった)。
#   両方に必ずあるのは**チェックボックスの id**: 単勝 chk_b1_<馬番> / 複勝 chk_b2_<馬番>。
#   枠番(Waku*)と馬番は別物。取り違えると別の馬にオッズが付いたまま誰も気づかない。
_TR_RE = re.compile(r"<tr.*?</tr>", re.S)
_CHK_RE = re.compile(r'id="chk_(b\d)_(\d{1,2})"')
_ODDS_CELL_RE = re.compile(r'<td[^>]*class="Odds"[^>]*>(.*?)</td>', re.S)
_NUM_RE = re.compile(r"(\d[\d,]*\.\d)")
_POST_RE = re.compile(r"(\d{1,2}):(\d{2})\s*発走")


def _rows(html: str, block_id: str, kind: str):
    """(馬番, オッズセルの中身) を返す。block_id の区画だけを見る。"""
    end = "odds_fuku_block" if block_id == "odds_tan_block" else None
    body = _block(html, block_id, end)
    for tr in _TR_RE.findall(body):
        mk = _CHK_RE.search(tr)
        if not mk or mk.group(1) != kind:
            continue
        cell = _ODDS_CELL_RE.search(tr)
        if cell:
            yield str(int(mk.group(2))), cell.group(1)


def odds_url(race_id: str) -> str:
    return ODDS_URL.format(race_id=race_id)


def _num(text: str) -> float | None:
    m = _NUM_RE.search(text or "")
    return float(m.group(1).replace(",", "")) if m else None


def _block(html: str, start: str, end: str | None) -> str:
    i = html.find(start)
    if i < 0:
        return ""
    j = html.find(end, i) if end else -1
    return html[i:j] if j > i else html[i:]


def parse_tan(html: str) -> dict[str, float]:
    """単勝。{馬番: オッズ}。"""
    out: dict[str, float] = {}
    for umaban, cell in _rows(html, "odds_tan_block", "b1"):
        v = _num(cell)
        if v is not None:
            out[umaban] = v
    return out


def parse_fuku(html: str) -> dict[str, tuple[float | None, float | None]]:
    """複勝。{馬番: (下限, 上限)}。'1.1 - 1.4' のようにレンジで入る。"""
    out: dict[str, tuple[float | None, float | None]] = {}
    for umaban, cell in _rows(html, "odds_fuku_block", "b2"):
        nums = _NUM_RE.findall(cell)
        if not nums:
            continue
        lo = float(nums[0].replace(",", ""))
        hi = float(nums[1].replace(",", "")) if len(nums) > 1 else None
        out[umaban] = (lo, hi)
    return out


def parse_post_time(html: str) -> str | None:
    m = _POST_RE.search(html)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


@dataclass
class OddsPage:
    race_id: str
    tan: dict[str, float] = field(default_factory=dict)
    fuku: dict[str, tuple[float | None, float | None]] = field(default_factory=dict)
    post_time: str | None = None
    status: int = 0
    x_cache: str = ""
    latency_ms: int = 0
    logged_in: bool = False
    nbytes: int = 0

    def digest_source(self) -> str:
        """値が変わったかの判定に使う。★取得時刻は含めない。"""
        return repr(sorted(self.tan.items())) + repr(sorted(self.fuku.items()))


def fetch(race_id: str, *, cookies: str | None = None, timeout: float = 15.0,
          opener=None) -> OddsPage:
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ja",
               "Cache-Control": "no-cache", "Pragma": "no-cache"}
    if cookies:
        headers["Cookie"] = cookies
    req = urllib.request.Request(odds_url(race_id), headers=headers)
    t0 = time.monotonic()
    _open = opener or urllib.request.urlopen
    with _open(req, timeout=timeout) as r:
        raw = r.read()
        hdr = {k.lower(): v for k, v in dict(r.headers).items()}
        status = getattr(r, "status", 200)
    html = raw.decode("utf-8", errors="replace")
    return OddsPage(
        race_id=race_id, tan=parse_tan(html), fuku=parse_fuku(html),
        post_time=parse_post_time(html), status=status,
        x_cache=hdr.get("x-cache", ""),
        latency_ms=int((time.monotonic() - t0) * 1000),
        logged_in=bool(cookies), nbytes=len(raw))


def cookie_header(state_path: str | None = None) -> str | None:
    """保存済み netkeiba セッション(Playwright storage_state)を Cookie にする。

    ★非会員でも単勝オッズは同値だった(2026-10-15、発走13〜30分前、
      memberRank は NotLogin と Premium)。ただし**締切直前は未確認**。
      セッションがあるなら使わない理由がない。無ければ非会員として続ける。
    """
    import json
    import os

    path = os.path.expanduser(
        state_path or os.environ.get("NETKEIBA_STATE") or "~/.netkeiba_state.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:  # noqa: BLE001
        return None
    pairs = [f"{c['name']}={c['value']}" for c in st.get("cookies", [])
             if "netkeiba" in (c.get("domain") or "")]
    return "; ".join(pairs) or None
