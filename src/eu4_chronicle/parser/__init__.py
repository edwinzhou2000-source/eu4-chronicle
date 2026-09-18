"""非铁人 .eu4 存档加载与 GameState 抽取。"""

from __future__ import annotations

import zipfile
from pathlib import Path

from eu4_chronicle.models import CountryState, GameState, Monarch, WarParticipant, WarState
from eu4_chronicle.parser.clausewitz import ObjectNode, parse_clausewitz_v2


class IronmanSaveError(ValueError):
    """铁人加密档第一期不支持。"""


class SaveParseError(ValueError):
    """存档无法解析。"""


def load_save_text(path: Path | str) -> str:
    """读取明文或 zip 压缩的非铁人存档文本。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"存档不存在: {path}")

    raw = path.read_bytes()
    # ZIP 魔数
    if raw[:2] == b"PK":
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            preferred = None
            for candidate in ("gamestate", "meta", "ai"):
                if candidate in names:
                    preferred = candidate
                    break
            if preferred is None:
                # 有些工具会打成单个同名文件
                preferred = names[0] if names else None
            if preferred is None:
                raise SaveParseError(f"压缩存档为空: {path}")
            # EU4 zip 通常有 gamestate；合并 meta 头部日期等
            parts: list[str] = []
            if "meta" in names and preferred != "meta":
                parts.append(zf.read("meta").decode("utf-8", errors="replace"))
            parts.append(zf.read(preferred).decode("utf-8", errors="replace"))
            if "gamestate" in names and preferred != "gamestate":
                parts.append(zf.read("gamestate").decode("utf-8", errors="replace"))
            text = "\n".join(parts)
    else:
        # 明文；也可能是铁人二进制
        if _looks_ironman_binary(raw):
            raise IronmanSaveError(
                "检测到铁人/加密存档。第一期仅支持非铁人明文或 zip 压缩的 .eu4。"
            )
        text = raw.decode("utf-8", errors="replace")

    if "ironman=yes" in text[:4000] and "player=" not in text[:8000]:
        # 部分铁人仍有标记但内容加密后不可读
        if "countries={" not in text and "country={" not in text:
            raise IronmanSaveError(
                "检测到铁人存档且无法读取国家块。第一期不支持铁人加密档。"
            )
    return text


def _looks_ironman_binary(raw: bytes) -> bool:
    if raw.startswith(b"EU4bin"):
        return True
    # 高比例不可打印字符
    sample = raw[:4096]
    if not sample:
        return False
    printable = sum(1 for b in sample if 9 <= b <= 13 or 32 <= b <= 126)
    return printable / len(sample) < 0.6 and raw[:2] != b"PK"


def parse_save(path: Path | str) -> GameState:
    path = Path(path)
    text = load_save_text(path)
    root = parse_clausewitz_v2(text)
    state = extract_game_state(root)
    state.source_path = str(path)
    return state


def parse_save_text(text: str, *, source_path: str | None = None) -> GameState:
    root = parse_clausewitz_v2(text)
    state = extract_game_state(root)
    state.source_path = source_path
    return state


def extract_game_state(root: ObjectNode) -> GameState:
    date = root.get_str("date")
    player = root.get_str("player")
    ironman = bool(root.get("ironman", False))

    countries: dict[str, CountryState] = {}
    countries_node = root.get_object("countries")
    if countries_node is not None:
        for tag, node in countries_node.values.items():
            if not isinstance(node, ObjectNode):
                continue
            if len(tag) != 3 or not tag.isalnum():
                # 跳过非 tag 键
                continue
            countries[tag] = _extract_country(tag, node)

    wars = _extract_wars(root)
    province_names = _extract_province_names(root)

    return GameState(
        date=date,
        player=player,
        ironman=ironman,
        countries=countries,
        wars=wars,
        province_names=province_names,
        raw_meta={
            "country_count": len(countries),
            "war_count": len(wars),
            "province_name_count": len(province_names),
        },
    )


def _extract_country(tag: str, node: ObjectNode) -> CountryState:
    name = node.get_str("name") or tag
    technology = {}
    tech_node = node.get_object("technology")
    if tech_node is not None:
        for k in ("adm_tech", "dip_tech", "mil_tech"):
            if tech_node.get(k) is not None:
                technology[k] = tech_node.get_int(k)

    monarch = None
    mon_node = node.get_object("monarch")
    if mon_node is not None:
        monarch = Monarch(
            name=mon_node.get_str("name") or mon_node.get_str("dynasty") or "未知君主",
            adm=mon_node.get_int("adm"),
            dip=mon_node.get_int("dip"),
            mil=mon_node.get_int("mil"),
        )

    allies = [str(x).strip('"') for x in node.get_list("allies") if x is not None]
    # 有些版本同盟在 diplomacy / active_relations 中；样例用简化字段
    rivals = []
    rival_node = node.get_object("rival")
    if rival_node is not None:
        # rival={ country="FRA" ... } 或列表
        c = rival_node.get_str("country")
        if c:
            rivals.append(c)
    for item in node.get_list("rivals"):
        if isinstance(item, ObjectNode):
            c = item.get_str("country")
            if c:
                rivals.append(c)
        elif item:
            rivals.append(str(item).strip('"'))

    subjects = [str(x).strip('"') for x in node.get_list("subjects") if x is not None]

    cores = []
    for x in node.get_list("core_provinces") + node.get_list("core"):
        try:
            cores.append(int(x))
        except (TypeError, ValueError):
            continue

    owned = []
    for x in node.get_list("owned_provinces"):
        try:
            owned.append(int(x))
        except (TypeError, ValueError):
            continue

    opinion_of: dict[str, float] = {}
    ae_map: dict[str, float] = {}
    opinion_node = node.get_object("opinion_cache") or node.get_object("opinions")
    if opinion_node is not None:
        for other, val in opinion_node.values.items():
            if isinstance(val, (int, float)):
                opinion_of[other] = float(val)
            elif isinstance(val, ObjectNode):
                opinion_of[other] = val.get_float("value", val.get_float("current_opinion"))

    ae_node = node.get_object("aggressive_expansion") or node.get_object("ae")
    if ae_node is not None:
        for other, val in ae_node.values.items():
            if isinstance(val, (int, float)):
                ae_map[other] = float(val)
            elif isinstance(val, ObjectNode):
                ae_map[other] = val.get_float("value")

    # 样例里也可能用扁平字段 ae_FRA=12
    for key, val in node.values.items():
        if key.startswith("ae_") and isinstance(val, (int, float)):
            ae_map[key[3:]] = float(val)
        if key.startswith("opinion_") and isinstance(val, (int, float)):
            opinion_of[key[8:]] = float(val)

    return CountryState(
        tag=tag,
        name=name,
        development=node.get_float("development")
        or node.get_float("raw_development")
        or float(len(owned) * 10),
        technology=technology,
        religion=node.get_str("religion"),
        government_rank=node.get_int("government_rank", 1),
        manpower=node.get_float("manpower"),
        max_manpower=node.get_float("max_manpower"),
        army_size=node.get_float("army_size") or _count_units(node, "army"),
        navy_size=node.get_float("navy_size") or _count_units(node, "navy"),
        prestige=node.get_float("prestige"),
        stability=node.get_int("stability"),
        monarch=monarch,
        allies=sorted(set(allies)),
        rivals=sorted(set(rivals)),
        subjects=sorted(set(subjects)),
        cores=sorted(set(cores)),
        owned_provinces=sorted(set(owned)),
        opinion_of=opinion_of,
        aggressive_expansion=ae_map,
    )


def _count_units(node: ObjectNode, key: str) -> float:
    total = 0.0
    for army in node.all_objects(key) + [
        x for x in node.get_list(key) if isinstance(x, ObjectNode)
    ]:
        if not isinstance(army, ObjectNode):
            continue
        for unit_key in ("infantry", "cavalry", "artillery", "heavy_ship", "light_ship", "galley", "transport"):
            total += army.get_float(unit_key)
        reg = army.get_object("regiment") or army.get_object("ship")
        if reg is not None:
            total += 1
        # 多个 regiment
        for _ in army.all_objects("regiment") + army.all_objects("ship"):
            total += 1
    return total


def _extract_province_names(root: ObjectNode) -> dict[int, str]:
    """从 provinces 块抽取 id → 名称（若存档带 name 字段）。"""
    names: dict[int, str] = {}
    provinces = root.get_object("provinces")
    if provinces is None:
        return names
    for key, node in provinces.values.items():
        try:
            pid = int(key)
        except (TypeError, ValueError):
            continue
        if not isinstance(node, ObjectNode):
            continue
        pname = node.get_str("name") or node.get_str("province_name")
        if pname:
            names[pid] = pname
    return names


def _extract_wars(root: ObjectNode) -> list[WarState]:
    wars: list[WarState] = []
    active = root.get_object("active_war")
    # active_war 可能重复键
    war_nodes: list[ObjectNode] = []
    if active is not None:
        war_nodes.append(active)
    war_nodes.extend(root.all_objects("active_war"))

    # 也支持 active_wars={ war={...} war={...} }
    container = root.get_object("active_wars")
    if container is not None:
        war_nodes.extend(container.all_objects("war"))
        for key, val in container.values.items():
            if isinstance(val, ObjectNode) and key != "war":
                war_nodes.append(val)

    seen: set[str] = set()
    for war in war_nodes:
        name = war.get_str("name") or war.get_str("war_name") or "未命名战争"
        if name in seen:
            continue
        seen.add(name)
        attackers = [str(x).strip('"') for x in war.get_list("attackers") if x]
        defenders = [str(x).strip('"') for x in war.get_list("defenders") if x]
        # participants 块
        participants: list[WarParticipant] = []
        part_node = war.get_object("participants")
        if part_node is not None:
            for tag, p in part_node.values.items():
                if not isinstance(p, ObjectNode):
                    continue
                side = "attackers" if tag in attackers else "defenders"
                if p.get_str("side") in {"attackers", "defenders"}:
                    side = p.get_str("side")  # type: ignore[assignment]
                participants.append(
                    WarParticipant(
                        tag=tag,
                        side=side,  # type: ignore[arg-type]
                        warscore=p.get_float("warscore") or p.get_float("value"),
                    )
                )
        wars.append(
            WarState(
                name=name,
                attackers=attackers,
                defenders=defenders,
                participants=participants,
            )
        )
    return wars
