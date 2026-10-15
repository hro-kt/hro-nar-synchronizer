"""場コードと締切。中央とは体系が違う。"""

from __future__ import annotations

# netkeiba の race_id は 12桁 YYYY + 場コード2 + 回2 + 日2 + R2。
# 中央は場コード 01-10、地方は 30 以上。
NAR_JYO_MIN = 30

JYO_NAMES = {
    "30": "門別", "31": "北見", "32": "岩見沢", "33": "帯広", "34": "旭川",
    "35": "盛岡", "36": "水沢", "37": "上山", "38": "三条", "39": "足利",
    "40": "宇都宮", "41": "高崎", "42": "浦和", "43": "船橋", "44": "大井",
    "45": "川崎", "46": "金沢", "47": "笠松", "48": "名古屋", "49": "紀三井寺",
    "50": "園田", "51": "姫路", "52": "益田", "53": "福山", "54": "高知",
    "55": "佐賀", "56": "荒尾", "57": "中津", "58": "札幌(地)", "59": "函館(地)",
    "60": "新潟(地)", "61": "中京(地)",
}

# ★南関東(浦和/船橋/大井/川崎)。プールが最も厚く、SPAT4 なら締切が1分前。
NANKAN = {"42", "43", "44", "45"}

# 投票締切。一般に**発走2分前**。SPAT4 の南関東だけ**1分前**。
# ★締切が情報の集中を生む。締切後に動くオッズは確定オッズで、賭けられない。
#   それを判断に使うと未来を見たことになる。
DEADLINE_SEC_DEFAULT = 120
DEADLINE_SEC_SPAT4_NANKAN = 60


def jyo_code(race_id: str) -> str:
    rid = (race_id or "").strip()
    if not (len(rid) == 12 and rid.isdigit()):
        raise ValueError(f"netkeiba の race_id は12桁です: {race_id!r}")
    return rid[4:6]


def race_num(race_id: str) -> str:
    return race_id[10:12] if len(race_id or "") == 12 else ""


def kaisai_date(race_id: str) -> str:
    """★race_id に開催日は入っていない(年+場+回+日+R)。日付は一覧から持ち回る。"""
    raise NotImplementedError("race_id から開催日は取れません。race_list から渡すこと")


def is_nar(race_id: str) -> bool:
    return int(jyo_code(race_id)) >= NAR_JYO_MIN


def is_nankan(race_id: str) -> bool:
    return jyo_code(race_id) in NANKAN


def jyo_name(race_id: str) -> str:
    return JYO_NAMES.get(jyo_code(race_id), "不明")


def deadline_sec(race_id: str, *, spat4: bool = False) -> int:
    """発走の何秒前が締切か。"""
    if spat4 and is_nankan(race_id):
        return DEADLINE_SEC_SPAT4_NANKAN
    return DEADLINE_SEC_DEFAULT


def describe(race_id: str) -> str:
    return f"{jyo_name(race_id)}({jyo_code(race_id)}) {race_num(race_id)}R"
