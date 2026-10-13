"""战争名可读化：英文专名 → 中文或「进攻方征服·目标」模板。"""

from __future__ import annotations

import re

from eu4_chronicle.names.catalog import COUNTRY_ZH, PLACE_EN_ZH, WAR_ADJECTIVE_ZH

_CONQUEST = re.compile(
    r"^(?P<adj>.+?)\s+(?P<kind>Reconquest|Conquest|Invasion|Aggression)\s+of\s+(?P<place>.+)$",
    re.IGNORECASE,
)
_SUCCESSION = re.compile(
    r"^(?P<adj>.+?)\s+Succession\s+War$",
    re.IGNORECASE,
)
_INDEPENDENCE = re.compile(
    r"^(?P<adj>.+?)\s+Independence(?:\s+War)?$",
    re.IGNORECASE,
)
_PAIR_WAR = re.compile(
    r"^(?P<a>[A-Za-zÀ-ÿ\- ]+?)\s*[-–—]\s*(?P<b>[A-Za-zÀ-ÿ\- ]+?)\s+(?P<kind>War|Feud|Conflict)$",
    re.IGNORECASE,
)
_PLAIN_WAR = re.compile(
    r"^(?P<adj>.+?)\s+(?P<kind>War|Campaign|Crusade)$",
    re.IGNORECASE,
)

_KIND_ZH = {
    "reconquest": "收复",
    "conquest": "征服",
    "invasion": "入侵",
    "aggression": "侵略",
    "war": "战争",
    "feud": "纷争",
    "conflict": "冲突",
    "campaign": "战役",
    "crusade": "十字军",
}


def _looks_mostly_latin(text: str) -> bool:
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    latin = sum(1 for ch in letters if ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ch in "ÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿüöäöß")
    return latin / len(letters) >= 0.6


def _place_zh(place: str) -> str:
    p = place.strip().strip("\"'")
    if p in PLACE_EN_ZH:
        return PLACE_EN_ZH[p]
    # 去变音后再试
    folded = (
        p.replace("ü", "u")
        .replace("ö", "o")
        .replace("ä", "a")
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )
    if folded in PLACE_EN_ZH:
        return PLACE_EN_ZH[folded]
    for en, zh in PLACE_EN_ZH.items():
        if en.lower() == p.lower() or en.lower() == folded.lower():
            return zh
    return p


def _adj_zh(adj: str) -> str | None:
    a = adj.strip()
    if a in WAR_ADJECTIVE_ZH:
        return WAR_ADJECTIVE_ZH[a]
    for en, zh in WAR_ADJECTIVE_ZH.items():
        if en.lower() == a.lower():
            return zh
    # 直接是 TAG
    upper = a.upper()
    if upper in COUNTRY_ZH:
        return COUNTRY_ZH[upper]
    return None


def _pair_side_zh(token: str) -> str:
    t = token.strip()
    zh = _adj_zh(t)
    if zh:
        return zh
    upper = t.upper()
    if upper in COUNTRY_ZH:
        return COUNTRY_ZH[upper]
    # Shimazu / Ito 等存档英文国名：尽量用 catalog 反向模糊
    for tag, name in COUNTRY_ZH.items():
        if name.lower() == t.lower():
            return name
    return t


def _is_garbled_war_name(name: str) -> bool:
    """私有字体 / 控制字符乱码（自定义国战名常见）→ 走攻守模板。"""
    raw = (name or "").strip()
    if not raw or raw in {"未名", "未命名战争"}:
        return True
    bad = 0
    for ch in raw:
        o = ord(ch)
        if o < 32 or ch == "\ufffd" or 0xE000 <= o <= 0xF8FF:
            bad += 1
    return bad >= max(2, (len(raw) + 2) // 3)


def translate_war_name(
    name: str | None,
    *,
    attackers: list[str] | None = None,
    defenders: list[str] | None = None,
    country_label=None,
) -> str:
    """把英文战争名译成中文；译不出则用「进攻方征服/战争·目标」模板。"""
    raw = (name or "").strip()
    if not raw or raw in {"未名", "未命名战争"} or _is_garbled_war_name(raw):
        return _template_fallback(attackers, defenders, country_label, place=None)

    if not _looks_mostly_latin(raw):
        return raw  # 已是中文等

    m = _CONQUEST.match(raw)
    if m:
        adj = _adj_zh(m.group("adj")) or _pair_side_zh(m.group("adj"))
        kind = _KIND_ZH.get(m.group("kind").lower(), "战争")
        place = _place_zh(m.group("place"))
        if kind in {"征服", "收复", "入侵", "侵略"}:
            return f"{adj}{kind}{place}"
        return f"{adj}{kind}·{place}"

    m = _SUCCESSION.match(raw)
    if m:
        adj = _adj_zh(m.group("adj")) or _pair_side_zh(m.group("adj"))
        return f"{adj}继承战争"

    m = _INDEPENDENCE.match(raw)
    if m:
        adj = _adj_zh(m.group("adj")) or _pair_side_zh(m.group("adj"))
        return f"{adj}独立战争"

    m = _PAIR_WAR.match(raw)
    if m:
        a = _pair_side_zh(m.group("a"))
        b = _pair_side_zh(m.group("b"))
        kind = _KIND_ZH.get(m.group("kind").lower(), "战争")
        return f"{a}—{b}{kind}"

    m = _PLAIN_WAR.match(raw)
    if m:
        adj = _adj_zh(m.group("adj")) or _pair_side_zh(m.group("adj"))
        kind = _KIND_ZH.get(m.group("kind").lower(), "战争")
        return f"{adj}{kind}"

    # 逐词替换形容词与地名后仍偏英文 → 模板兜底
    replaced = raw
    for en, zh in sorted(WAR_ADJECTIVE_ZH.items(), key=lambda x: -len(x[0])):
        replaced = re.sub(rf"\b{re.escape(en)}\b", zh, replaced, flags=re.IGNORECASE)
    for en, zh in sorted(PLACE_EN_ZH.items(), key=lambda x: -len(x[0])):
        replaced = re.sub(rf"\b{re.escape(en)}\b", zh, replaced, flags=re.IGNORECASE)

    if _looks_mostly_latin(replaced):
        place = None
        if " of " in raw.lower():
            place = _place_zh(raw.split(" of ", 1)[-1])
        return _template_fallback(attackers, defenders, country_label, place=place)
    return replaced


def _template_fallback(
    attackers: list[str] | None,
    defenders: list[str] | None,
    country_label,
    *,
    place: str | None,
) -> str:
    label = country_label or (lambda t: COUNTRY_ZH.get((t or "").upper(), t or "？"))
    att = attackers or []
    defe = defenders or []
    att_s = "、".join(label(x) for x in att[:2]) if att else "未知进攻方"
    if place:
        return f"{att_s}征服·{place}"
    if defe:
        def_s = "、".join(label(x) for x in defe[:2])
        return f"{att_s}战争·{def_s}"
    return f"{att_s}战争"
