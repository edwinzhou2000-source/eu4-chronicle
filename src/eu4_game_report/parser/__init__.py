"""非铁人 .eu4 存档加载与 GameState 抽取。"""

from __future__ import annotations

import zipfile
from pathlib import Path

from eu4_game_report.models import (
    CountryRelation,
    CountryState,
    GameState,
    Monarch,
    WarBattle,
    WarParticipant,
    WarState,
)
from eu4_game_report.parser.clausewitz import ObjectNode, parse_clausewitz_v2

# 真档战争目标块名（Osallek WarGoalType + take_claim 等别名）
_WAR_GOAL_KEYS = (
    "take_colony",
    "take_core",
    "take_border",
    "take_province",
    "take_claim",
    "take_capital",
    "defend_capital",
    "defend_country",
    "naval_superiority",
    "superiority",
    "take_region",
    "blockade_ports",
)


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
                parts.append(_decode_eu4_bytes(zf.read("meta")))
            parts.append(_decode_eu4_bytes(zf.read(preferred)))
            if "gamestate" in names and preferred != "gamestate":
                parts.append(_decode_eu4_bytes(zf.read("gamestate")))
            text = "\n".join(parts)
    else:
        # 明文；也可能是铁人二进制
        if _looks_ironman_binary(raw):
            raise IronmanSaveError(
                "检测到铁人/加密存档。第一期仅支持非铁人明文或 zip 压缩的 .eu4。"
            )
        text = _decode_eu4_bytes(raw)

    if "ironman=yes" in text[:4000] and "player=" not in text[:8000]:
        # 部分铁人仍有标记但内容加密后不可读
        if "countries={" not in text and "country={" not in text:
            raise IronmanSaveError(
                "检测到铁人存档且无法读取国家块。第一期不支持铁人加密档。"
            )
    return text


def _decode_eu4_bytes(raw: bytes) -> str:
    """EU4 文本多为 UTF-8，地名偶发 Windows-1252（如 Rügen）；避免 � 乱码。"""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")
    if "\ufffd" not in text:
        return text
    # utf-8 带替换符：整段按 cp1252 重试，若 � 更少则采用
    alt = raw.decode("cp1252", errors="replace")
    if alt.count("\ufffd") < text.count("\ufffd"):
        return alt
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
    # countries={} 键序（含 --- 空槽）= opinion_cache 下标
    country_tag_order: list[str] = []
    countries_node = root.get_object("countries")
    if countries_node is not None:
        for tag, node in countries_node.values.items():
            country_tag_order.append(str(tag))
            if not isinstance(node, ObjectNode):
                continue
            if len(tag) != 3 or not tag.isalnum():
                # 跳过非 tag 键（如 ---）
                continue
            countries[tag] = _extract_country(tag, node)

    _fill_ae_maps_from_relations(countries)
    _apply_opinion_cache(countries, countries_node, country_tag_order)
    _apply_subject_types(countries, root)

    wars = _extract_wars(root)
    previous_wars = _extract_previous_wars(root)
    province_names = _extract_province_names(root)

    state = GameState(
        date=date,
        player=player,
        ironman=ironman,
        countries=countries,
        wars=wars,
        previous_wars=previous_wars,
        province_names=province_names,
        raw_meta={
            "country_count": len(countries),
            "war_count": len(wars),
            "previous_war_count": len(previous_wars),
            "province_name_count": len(province_names),
        },
    )
    return prune_ghost_active_wars(state)


def _country_is_living(state: GameState, tag: str) -> bool:
    """存活：在 countries 中且仍有省份（事件和谈后敌方常成无地残留）。"""
    c = state.countries.get(tag)
    return bool(c and c.owned_provinces)


def is_ghost_active_war(w: WarState, state: GameState, *, player: str | None = None) -> bool:
    """对侧 TAG 非空但无一存活 → 幽灵 active_war（事件和谈脏数据）。

    若玩家本国也无地（合成测未写 owned_provinces），不剪除，避免误伤夹具。
    """
    player = player if player is not None else state.player
    if player and player in w.attackers:
        foes = list(w.defenders)
        if not _country_is_living(state, player):
            return False
    elif player and player in w.defenders:
        foes = list(w.attackers)
        if not _country_is_living(state, player):
            return False
    else:
        # 无玩家视角：一侧全灭、另一侧仍有存活 → 幽灵
        att_live = any(_country_is_living(state, t) for t in w.attackers)
        def_live = any(_country_is_living(state, t) for t in w.defenders)
        if w.attackers and w.defenders and ((att_live and not def_live) or (def_live and not att_live)):
            return True
        return False
    if not foes:
        return False
    return not any(_country_is_living(state, t) for t in foes)


def prune_ghost_active_wars(state: GameState) -> GameState:
    """从 GameState.wars 去掉事件和谈残留的幽灵战争；不动 previous_wars。"""
    kept = [w for w in state.wars if not is_ghost_active_war(w, state)]
    if len(kept) == len(state.wars):
        return state
    meta = dict(state.raw_meta or {})
    meta["war_count"] = len(kept)
    meta["ghost_wars_pruned"] = len(state.wars) - len(kept)
    return state.model_copy(update={"wars": kept, "raw_meta": meta})


def _extract_economy(node: ObjectNode) -> tuple[float, float, float, float]:
    """国库 / 月收入 / 月支出 / 净收入。

    - 国库：``treasury``
    - 月收入：``estimated_monthly_income``，否则 ledger 经常性/上月收入
    - 月支出：优先 ``ledger.last_months_recurring_expenses``（经常性），否则上月总支出
    - 净收入：收入 − 支出（与 UI「余额」同向；大额一次性军费会反映在上月总支出路径）
    """
    treasury = node.get_float("treasury")
    income = node.get_float_optional("estimated_monthly_income")
    expenses: float | None = None
    ledger = node.get_object("ledger")
    if ledger is not None:
        if income is None:
            income = ledger.get_float_optional("last_months_recurring_income")
            if income is None:
                income = ledger.get_float_optional("lastmonthincome")
        expenses = ledger.get_float_optional("last_months_recurring_expenses")
        if expenses is None:
            expenses = ledger.get_float_optional("lastmonthexpense")
    income_v = float(income or 0.0)
    expenses_v = float(expenses or 0.0)
    return treasury, income_v, expenses_v, income_v - expenses_v


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

    completed_missions = _extract_completed_missions(node)
    relations = _extract_active_relations(node)

    gov_name = (node.get_str("government_name") or "").strip().strip('"')
    changed_from = (node.get_str("changed_tag_from") or "").strip().strip('"').upper()
    # 真档 previous_country_tags 常为标量 "HOL"，偶发列表
    prev_tags: list[str] = []
    prev_scalar = (node.get_str("previous_country_tags") or "").strip().strip('"').upper()
    if prev_scalar:
        prev_tags.append(prev_scalar)
    for x in node.get_list("previous_country_tags"):
        if x is None:
            continue
        pt = str(x).strip().strip('"').upper()
        if pt and pt not in prev_tags:
            prev_tags.append(pt)
    if not changed_from:
        # 换皮记录常在 history 日期块内
        hist = node.get_object("history")
        if hist is not None:
            for _k, sub in hist.values.items():
                if isinstance(sub, ObjectNode):
                    cf = (sub.get_str("changed_tag_from") or "").strip().strip('"').upper()
                    if cf:
                        changed_from = cf
                        break
    if changed_from and changed_from not in prev_tags:
        prev_tags.insert(0, changed_from)

    treasury, income, expenses, net_income = _extract_economy(node)

    return CountryState(
        tag=tag,
        name=name,
        # UI 总发展度多对应 raw_development；development 常为本土子集，勿优先
        development=node.get_float("raw_development")
        or node.get_float("development")
        or float(len(owned) * 10),
        technology=technology,
        religion=node.get_str("religion"),
        government_rank=node.get_int("government_rank", 1),
        manpower=node.get_float("manpower"),
        max_manpower=node.get_float("max_manpower"),
        treasury=treasury,
        income=income,
        expenses=expenses,
        net_income=net_income,
        army_size=node.get_float("army_size") or _count_units(node, "army"),
        navy_size=node.get_float("navy_size") or _count_units(node, "navy"),
        discipline=_resolve_discipline(node),
        **_resolve_morale_fields(node),
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
        relations=relations,
        completed_missions=completed_missions,
        government_name=gov_name,
        changed_tag_from=changed_from,
        previous_country_tags=prev_tags,
    )


def _is_relation_tag(key: str) -> bool:
    """active_relations 下的 TAG 键（含 NE8 / EN1 等三位字母数字）。"""
    return len(key) == 3 and key.isalnum() and key[0].isalpha()


def _extract_active_relations(node: ObjectNode) -> dict[str, CountryRelation]:
    """从 active_relations 抽取对各国的 AE（侵略扩张好感修正）、总好感、停战。"""
    rel_root = node.get_object("active_relations")
    if rel_root is None:
        return {}
    out: dict[str, CountryRelation] = {}
    for other, rel_node in rel_root.values.items():
        if not isinstance(rel_node, ObjectNode) or not _is_relation_tag(str(other)):
            continue
        ae = 0.0
        opinion_sum = 0.0
        has_opinion_mod = False
        for op in rel_node.all_objects("opinion"):
            has_opinion_mod = True
            cur = op.get_float("current_opinion")
            opinion_sum += cur
            if (op.get_str("modifier") or "").strip('"') == "aggressive_expansion":
                # AE 好感修正为负；AE 分数 = |current_opinion|
                ae = max(ae, abs(cur))
        cached = rel_node.get_float_optional("cached_sum")
        # cached_sum 常滞后于 UI；有 opinion_cache 时由 _apply_opinion_cache 覆盖
        opinion = float(cached) if cached is not None else (opinion_sum if has_opinion_mod else 0.0)
        truce_raw = rel_node.get("truce")
        truce = False
        if isinstance(truce_raw, bool):
            truce = truce_raw
        elif truce_raw is not None:
            truce = str(truce_raw).strip('"').lower() in {"yes", "true", "1"}
        attitude = (rel_node.get_str("attitude") or "").strip().strip('"')
        if ae <= 0 and cached is None and not has_opinion_mod and not truce:
            # 仅 attitude / recalc 的空壳关系可跳过
            if not attitude and rel_node.get("recalc_attitude") is None:
                continue
        out[str(other).upper()] = CountryRelation(
            tag=str(other).upper(),
            ae=ae,
            opinion=opinion,
            truce=truce,
            attitude=attitude,
        )
    return out


def _parse_opinion_cache_list(node: ObjectNode) -> list[float] | None:
    """opinion_cache={ 0 25 -10 ... } → 与 countries 键序对齐的好感数组。"""
    raw = node.get_list("opinion_cache")
    if not raw:
        return None
    out: list[float] = []
    for x in raw:
        try:
            out.append(float(x))
        except (TypeError, ValueError):
            out.append(0.0)
    return out if out else None


def _apply_opinion_cache(
    countries: dict[str, CountryState],
    countries_node: ObjectNode | None,
    tag_order: list[str],
) -> None:
    """用 opinion_cache 覆盖关系好感（与游戏外交界面一致；cached_sum 常过时）。"""
    if countries_node is None or not tag_order:
        return
    tag_index = {str(t): i for i, t in enumerate(tag_order)}
    for tag, c in countries.items():
        node = countries_node.values.get(tag)
        if not isinstance(node, ObjectNode):
            continue
        cache = _parse_opinion_cache_list(node)
        if cache is None:
            continue
        for other, idx in tag_index.items():
            if other == tag or idx >= len(cache):
                continue
            if not (len(other) == 3 and other.isalnum()):
                continue
            if other not in countries and other not in (c.relations or {}):
                continue
            val = float(cache[idx])
            c.opinion_of[other] = val
            rel = (c.relations or {}).get(other)
            if rel is not None:
                rel.opinion = val


def _apply_subject_types(
    countries: dict[str, CountryState], root: ObjectNode
) -> None:
    """从 diplomacy.dependency 填充各国 subject_types（以 subjects 列表为准）。"""
    diplo = root.get_object("diplomacy")
    if diplo is None:
        return
    # overlord → {subject: type_id}
    mapping: dict[str, dict[str, str]] = {}
    for dep in diplo.all_objects("dependency"):
        first = (dep.get_str("first") or "").strip().strip('"').upper()
        second = (dep.get_str("second") or "").strip().strip('"').upper()
        stype = (dep.get_str("subject_type") or "").strip().strip('"')
        if not first or not second or not stype:
            continue
        # 已结束依赖（有 end_date 且早于当前）仍可能留在档内；仍以 subjects 列表裁剪
        mapping.setdefault(first, {})[second] = stype
    for tag, c in countries.items():
        types = mapping.get(tag) or {}
        if not c.subjects and not types:
            continue
        # 只保留仍在 subjects 中的类型；subjects 有而 dependency 无则留空类型
        c.subject_types = {
            s: types[s] for s in c.subjects if s in types
        }


def _fill_ae_maps_from_relations(countries: dict[str, CountryState]) -> None:
    """他国 active_relations[player].ae → player.aggressive_expansion[他国]。"""
    for owner, c in countries.items():
        for target, rel in (c.relations or {}).items():
            if rel.ae <= 0:
                continue
            victim = countries.get(target)
            if victim is None:
                continue
            prev = float(victim.aggressive_expansion.get(owner, 0.0) or 0.0)
            if rel.ae > prev:
                victim.aggressive_expansion[owner] = float(rel.ae)


def _extract_completed_missions(node: ObjectNode) -> list[str]:
    """``completed_missions={ "id1" "id2" }`` → 去重保序 ID 列表。"""
    raw = node.get_list("completed_missions")
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, ObjectNode):
            continue
        mid = str(item).strip().strip('"')
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append(mid)
    return out


# 国块内可能出现的质量相关数值键（真档常无顶层裸字段，需扫嵌套 / modifier）
_QUALITY_NUMERIC_KEYS = ("discipline", "land_morale", "land_morale_constant")
# dump-military 候选键子串（大小写不敏感）
_MILITARY_KEY_HINTS = (
    "discipline",
    "morale",
    "tradition",
    "professional",
    "drill",
    "forcelimit",
    "force_limit",
)


def _walk_object_nodes(
    node: ObjectNode, *, path: str = ""
) -> list[tuple[str, ObjectNode]]:
    """深度优先遍历对象节点（含 multi 重复键）。"""
    out: list[tuple[str, ObjectNode]] = [(path or ".", node)]
    for key, val in node.values.items():
        child_path = f"{path}.{key}" if path else key
        if isinstance(val, ObjectNode):
            out.extend(_walk_object_nodes(val, path=child_path))
    for key, items in node.multi.items():
        for idx, val in enumerate(items):
            if isinstance(val, ObjectNode):
                child_path = f"{path}.{key}[{idx}]" if path else f"{key}[{idx}]"
                out.extend(_walk_object_nodes(val, path=child_path))
    return out


def _collect_key_floats(node: ObjectNode, key: str) -> list[tuple[str, float]]:
    """在国块树内收集 key=数值（含嵌套 modifier/history）。"""
    found: list[tuple[str, float]] = []
    for path, obj in _walk_object_nodes(node):
        if key not in obj.values:
            continue
        val = obj.values[key]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        loc = key if path in {"", "."} else f"{path}.{key}"
        found.append((loc, float(val)))
    return found


def _resolve_discipline(node: ObjectNode) -> float | None:
    """纪律：优先国块顶层；否则扫嵌套数值。

    - 绝对值（≥0.8，如 1.05）直接采用；
    - 仅有小幅 bonus（如 modifier 内 0.05）则按 1.0+sum 聚合。
    """
    top = node.get_float_optional("discipline")
    if top is not None:
        return top
    found = _collect_key_floats(node, "discipline")
    if not found:
        return None
    vals = [v for _, v in found]
    abs_like = [v for v in vals if v >= 0.8]
    if abs_like:
        return abs_like[0]
    return round(1.0 + sum(vals), 4)


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    ordered = sorted(vals)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _unit_morale_values(node: ObjectNode, force_key: str, unit_key: str) -> list[float]:
    """收集 army.regiment.morale 或 navy.ship.morale（仅部队节点，不扫其它 morale）。"""
    out: list[float] = []
    seen_force: set[int] = set()
    forces: list[ObjectNode] = []
    for force in node.all_objects(force_key):
        fid = id(force)
        if fid not in seen_force:
            seen_force.add(fid)
            forces.append(force)
    for item in node.get_list(force_key):
        if isinstance(item, ObjectNode) and id(item) not in seen_force:
            seen_force.add(id(item))
            forces.append(item)
    for force in forces:
        seen_unit: set[int] = set()
        units: list[ObjectNode] = []
        for unit in force.all_objects(unit_key):
            uid = id(unit)
            if uid not in seen_unit:
                seen_unit.add(uid)
                units.append(unit)
        for item in force.get_list(unit_key):
            if isinstance(item, ObjectNode) and id(item) not in seen_unit:
                seen_unit.add(id(item))
                units.append(item)
        for unit in units:
            m = unit.get_float_optional("morale")
            if m is not None:
                out.append(m)
    return out


def _resolve_land_morale_absolute(node: ObjectNode) -> float | None:
    """绝对士气：顶层 / 嵌套 land_morale（≥1.5）+ land_morale_constant。

    仅有乘法 bonus（<1.5）无法还原 UI 士气 → None（再回退团级代理）。
    """
    constants = _collect_key_floats(node, "land_morale_constant")
    const_sum = sum(v for _, v in constants)
    top = node.get_float_optional("land_morale")
    if top is not None:
        return round(top + const_sum, 4) if const_sum else top
    found = _collect_key_floats(node, "land_morale")
    if not found and not constants:
        return None
    vals = [v for _, v in found]
    abs_like = [v for v in vals if v >= 1.5]
    if abs_like:
        return round(abs_like[0] + const_sum, 4)
    return None


def _resolve_morale_fields(node: ObjectNode) -> dict[str, float | bool | None]:
    """解析陆/海士气。

    - land_morale：优先绝对字段；否则 army[*].regiment[*].morale 中位数代理
    - naval_morale：navy[*].ship[*].morale 中位数（可选对比维）
    - discipline 仍由 _resolve_discipline 负责；无数值保持 None，禁止臆造
    """
    absolute = _resolve_land_morale_absolute(node)
    if absolute is not None:
        land: float | None = absolute
        proxy = False
    else:
        reg_vals = _unit_morale_values(node, "army", "regiment")
        med = _median(reg_vals)
        if med is not None:
            land = round(med, 4)
            proxy = True
        else:
            land = None
            proxy = False
    ship_vals = _unit_morale_values(node, "navy", "ship")
    naval_med = _median(ship_vals)
    naval = round(naval_med, 4) if naval_med is not None else None
    return {
        "land_morale": land,
        "land_morale_proxy": proxy,
        "naval_morale": naval,
    }


def _named_modifiers(node: ObjectNode) -> list[str]:
    """收集国块顶层 modifier={ modifier="name" ... } 名称（不含外交 opinion）。"""
    names: list[str] = []
    blocks: list[ObjectNode] = []
    blocks.extend(node.all_objects("modifier"))
    blocks.extend(node.all_objects("modifiers"))
    for item in node.get_list("modifier") + node.get_list("modifiers"):
        if isinstance(item, ObjectNode):
            blocks.append(item)
        elif isinstance(item, str):
            names.append(item.strip('"'))
    for obj in blocks:
        raw = obj.values.get("modifier") if "modifier" in obj.values else None
        if isinstance(raw, str):
            names.append(raw.strip('"'))
        else:
            n = obj.get_str("modifier")
            if n:
                names.append(n)
    return list(dict.fromkeys(n for n in names if n))


def _candidate_military_keys(node: ObjectNode) -> list[tuple[str, str]]:
    """返回 (路径, 值摘要) 候选军事相关键，供 dump-military。"""
    hits: list[tuple[str, str]] = []
    for path, obj in _walk_object_nodes(node):
        for key, val in obj.values.items():
            key_l = key.lower()
            if not any(h in key_l for h in _MILITARY_KEY_HINTS):
                continue
            # 跳过外交 opinion 块里的 modifier 名字段
            if key_l == "modifier" and isinstance(val, str):
                if ".opinion" in f".{path}." or path.endswith("opinion") or "opinion_" in path:
                    continue
            loc = key if path in {"", "."} else f"{path}.{key}"
            if isinstance(val, ObjectNode):
                summary = "{…}"
            elif isinstance(val, list):
                summary = f"[{len(val)}]"
            else:
                summary = str(val)
            hits.append((loc, summary))
    return hits


def _count_units(node: ObjectNode, key: str) -> float:
    """统计 army/navy 下的团/舰数量。

    真档多为重复键 army=/navy= 块，内含多个 regiment=/ship=。
    切勿把 all_objects 与 get_list 叠加，也切勿 get_object + all_objects 双计。
    """
    total = 0.0
    for army in node.all_objects(key):
        if not isinstance(army, ObjectNode):
            continue
        flat = 0.0
        for unit_key in (
            "infantry",
            "cavalry",
            "artillery",
            "heavy_ship",
            "light_ship",
            "galley",
            "transport",
        ):
            flat += army.get_float(unit_key)
        if flat > 0:
            total += flat
            continue
        total += float(len(army.all_objects("regiment")) + len(army.all_objects("ship")))
    return total


def _extract_province_names(root: ObjectNode) -> dict[int, str]:
    """从 provinces 块抽取 id → 名称（若存档带 name 字段）。

    Clausewitz 真档省份键常为负数（``-54``）；统一存为正 id。
    中文私有字体编码的 name 视为乱码，跳过（留给 localisation PROV{{id}}）。
    """
    from eu4_game_report.localisation import looks_mojibake

    names: dict[int, str] = {}
    provinces = root.get_object("provinces")
    if provinces is None:
        return names
    for key, node in provinces.values.items():
        try:
            pid = abs(int(key))
        except (TypeError, ValueError):
            continue
        if not isinstance(node, ObjectNode):
            continue
        pname = node.get_str("name") or node.get_str("province_name")
        if pname and not looks_mojibake(pname):
            names[pid] = pname
    return names


def _extract_wars(root: ObjectNode) -> list[WarState]:
    """抽取进行中战争。

    真档形态（Clausewitz；TEU Naklo 档钉死）：
      active_war={ ... }          # 根级重复键
      attackers={ TEU ... }
      defenders={ POL ... }
      participants={ value=.. tag="TEU" war_score=0 ... }  # value=贡献度；war_score≈0 勿当总战分
      last_warscore_quarter=      # **总战分**（季度快照；可能与 UI 实时略差）
      last_warscore_year=         # 年快照；quarter 缺失时回退
      attacker_score=             # **ticking**（攻方）；禁止当总战分
      defender_score=             # 相应侧；无 quarter 时可读作总战分（Osallek）
      history={ DATE={ add_attacker=... } battle={...} war_goal={...} }

    合成样例仍支持 active_wars={ war={ participants={ TAG={ warscore= } } } }。
    """
    war_nodes: list[ObjectNode] = []
    war_nodes.extend(root.all_objects("active_war"))

    container = root.get_object("active_wars")
    if container is not None:
        war_nodes.extend(container.all_objects("war"))
        for key, val in container.values.items():
            if isinstance(val, ObjectNode) and key != "war":
                war_nodes.append(val)
        for item in container.get_list("war"):
            if isinstance(item, ObjectNode):
                war_nodes.append(item)

    seen: set[str] = set()
    wars: list[WarState] = []
    for war in war_nodes:
        name = war.get_str("name") or war.get_str("war_name") or "未命名战争"
        if name in seen:
            continue
        seen.add(name)
        wars.append(_parse_one_war(war, root, finished=False))
    return wars


def _extract_previous_wars(root: ObjectNode) -> list[WarState]:
    """抽取已结束战争（根级重复键 previous_war）。

    真档在两份存档之间开打又打完的战争只出现在这里，不在 active_war。
    结构与 active_war 类似，常以 history 记载攻守与会战，未必有实时总战分。
    """
    war_nodes: list[ObjectNode] = []
    war_nodes.extend(root.all_objects("previous_war"))
    seen: set[str] = set()
    wars: list[WarState] = []
    for war in war_nodes:
        name = war.get_str("name") or war.get_str("war_name") or "未命名战争"
        if name in seen:
            continue
        seen.add(name)
        wars.append(_parse_one_war(war, root, finished=True))
    return wars


_SCORE_KEY_HINTS = ("score", "warscore", "ticking")


def _key_looks_score_related(key: str) -> bool:
    low = key.lower()
    return any(h in low for h in _SCORE_KEY_HINTS)


def _collect_raw_score_fields(war: ObjectNode) -> dict[str, float]:
    """递归收集战争块内一切含 score/warscore/ticking 的数值键，以及 participants 的 value/tag。"""
    out: dict[str, float] = {}

    def walk(node: ObjectNode, prefix: str) -> None:
        for key, val in node.values.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(val, ObjectNode):
                walk(val, path)
            elif isinstance(val, bool):
                continue
            elif isinstance(val, (int, float)):
                if _key_looks_score_related(key) or key in {"value"}:
                    out[path] = float(val)
            elif isinstance(val, str):
                if key == "tag" or _key_looks_score_related(key):
                    try:
                        out[path] = float(val.strip('"'))
                    except ValueError:
                        pass
        for key, vals in node.multi.items():
            for i, val in enumerate(vals):
                path = f"{prefix}.{key}[{i}]" if prefix else f"{key}[{i}]"
                if isinstance(val, ObjectNode):
                    walk(val, path)
                elif isinstance(val, (int, float)) and not isinstance(val, bool):
                    if _key_looks_score_related(key) or key in {"value"}:
                        out[path] = float(val)
        for key, lst in node.lists.items():
            path = f"{prefix}.{key}" if prefix else key
            for i, item in enumerate(lst):
                item_path = f"{path}[{i}]"
                if isinstance(item, ObjectNode):
                    walk(item, item_path)
                elif isinstance(item, (int, float)) and not isinstance(item, bool):
                    if _key_looks_score_related(key):
                        out[item_path] = float(item)

    walk(war, "")
    # participants 重复块：显式标出 tag/value/war_score
    for i, part in enumerate(war.all_objects("participants")):
        tag = part.get_str("tag") or f"#{i}"
        for key in ("value", "war_score", "warscore", "score"):
            if part.has(key):
                fv = part.get_float_optional(key)
                if fv is None and key in part.values:
                    raw = part.values[key]
                    try:
                        fv = float(raw)
                    except (TypeError, ValueError):
                        fv = None
                if fv is not None:
                    out[f"participants[{i}|{tag}].{key}"] = float(fv)
    return out


def _parse_one_war(
    war: ObjectNode, root: ObjectNode, *, finished: bool = False
) -> WarState:
    history = war.get_object("history")
    attackers = [str(x).strip('"') for x in war.get_list("attackers") if x]
    defenders = [str(x).strip('"') for x in war.get_list("defenders") if x]
    if not attackers and not defenders:
        # previous_war：结束时各方均 rem，当前集合常残留无关 TAG；用 lifetime
        attackers, defenders = _sides_from_history(
            history, lifetime=finished
        )
    elif finished:
        # 顶层攻守偶发残留；仍以 history lifetime 为准
        life_a, life_d = _sides_from_history(history, lifetime=True)
        if life_a or life_d:
            attackers, defenders = life_a, life_d
    elif not attackers or not defenders:
        # active_war 常一侧被 rem 清空，另一侧仍残留；用 history 当前集合补缺
        hist_a, hist_d = _sides_from_history(history, lifetime=False)
        if not attackers and hist_a:
            attackers = hist_a
        if not defenders and hist_d:
            defenders = hist_d

    participants = _parse_participants(war, attackers, defenders)
    # participants.side 比顶层 attackers/defenders 更完整（真档常见）
    attackers, defenders = _merge_sides_from_participants(
        attackers, defenders, participants
    )
    original_attacker = (war.get_str("original_attacker") or "").strip().strip('"')
    original_defender = (war.get_str("original_defender") or "").strip().strip('"')
    attackers = _lead_side(attackers, original_attacker)
    defenders = _lead_side(defenders, original_defender)
    goal = _parse_war_goal(war, history)
    battles = _parse_battles(history)
    # 已结束战争的「当前占领」对 curr 地图无意义，勿写入 0 处干扰文案
    occupied = None if finished else _count_occupied_provinces(root, attackers, defenders)
    raw_scores = _collect_raw_score_fields(war)

    outcome = war.get_int_optional("outcome")
    ended_date = war.get_str("action") or None
    if ended_date:
        ended_date = ended_date.strip().strip('"')

    state = WarState(
        # 乱码私有字体名仍保留作 Diff 身份键；可读化时再走模板兜底
        name=war.get_str("name") or war.get_str("war_name") or "未命名战争",
        attackers=attackers,
        defenders=defenders,
        participants=participants,
        original_attacker=original_attacker,
        original_defender=original_defender,
        attacker_score=war.get_float_optional("attacker_score"),
        defender_score=war.get_float_optional("defender_score"),
        last_warscore_quarter=war.get_float_optional("last_warscore_quarter"),
        last_warscore_year=war.get_float_optional("last_warscore_year"),
        raw_score_fields=raw_scores,
        war_goal_type=goal.get("type"),
        casus_belli=goal.get("casus_belli"),
        war_goal_province=goal.get("province"),
        war_goal_tag=goal.get("tag"),
        occupied_provinces=occupied,
        battles=battles,
        outcome=outcome,
        ended_date=ended_date,
    )
    state.resolve_total_and_ticking()
    return state


def format_war_score_dump(state: GameState, *, player_only: bool = True) -> str:
    """格式化玩家参与战争的原始分数字段，供本机贴回钉死映射。"""
    player = state.player
    lines: list[str] = [
        f"# dump-war-scores  date={state.date}  player={player or '?'}",
        f"# source={state.source_path or '(text)'}",
        "# 映射：total ← last_warscore_quarter（缺则 year / 非零 war_score / defender_score）；"
        "ticking ← attacker_score（禁止当 total）",
        "# participants.value=贡献度；participants.war_score≈0 不作 UI 总战分",
        "",
    ]
    wars = state.wars
    if player_only and player:
        wars = [
            w
            for w in state.wars
            if player in w.attackers
            or player in w.defenders
            or any(p.tag == player for p in w.participants)
        ]
    if not wars:
        lines.append("(无匹配的 active_war)")
        return "\n".join(lines)

    for idx, w in enumerate(wars, 1):
        side = "?"
        if player in w.attackers:
            side = "attackers"
        elif player in w.defenders:
            side = "defenders"
        lines.append(f"## [{idx}] {w.name}")
        lines.append(f"attackers={w.attackers}")
        lines.append(f"defenders={w.defenders}")
        lines.append(f"player_side={side}")
        lines.append(f"last_warscore_quarter={w.last_warscore_quarter}")
        lines.append(f"last_warscore_year={w.last_warscore_year}")
        lines.append(f"attacker_score={w.attacker_score}")
        lines.append(f"defender_score={w.defender_score}")
        lines.append(
            f"resolved_total_attacker={w.total_attacker_score}"
            f"  source={w.total_score_source}"
            f"  # ← UI 总战分（主展示）"
        )
        lines.append(
            f"resolved_ticking_attacker={w.ticking_attacker_score}"
            f"  source={w.ticking_score_source}"
            f"  # ← 战争目标加分 / ticking"
        )
        if player:
            lines.append(f"score_for(player)={w.score_for(player)}  # 玩家视角总战分")
            lines.append(f"ticking_for(player)={w.ticking_for(player)}  # 玩家视角 ticking")
        lines.append("participants:  # value=贡献度；war_score≈0 勿当总战分")
        for p in w.participants:
            lines.append(
                f"  - tag={p.tag} side={p.side} warscore_known={p.warscore_known}"
                f" warscore={p.warscore} contribution={p.contribution}"
            )
        lines.append("raw_score_fields:")
        if w.raw_score_fields:
            for k in sorted(w.raw_score_fields):
                lines.append(f"  {k}={w.raw_score_fields[k]}")
        else:
            lines.append("  (none)")
        lines.append("")
    return "\n".join(lines)


def dump_war_scores(path: Path | str, *, player_only: bool = True) -> str:
    """解析存档并返回 dump-war-scores 文本。"""
    state = parse_save(path)
    return format_war_score_dump(state, player_only=player_only)


def _normalize_tag(raw: str) -> str | None:
    """规范化 TAG：去引号/空白/尾部杂符（如 shell 残留 ~），大写；非法则 None。

    禁止生成幽灵 tag（如 POL~）；查不到就如实 missing，不发明近似键。
    """
    t = raw.strip().strip("\"'").upper()
    # 去掉尾部非字母数字（PowerShell/补全偶发 POL~）
    while t and not t[-1].isalnum():
        t = t[:-1]
    while t and not t[0].isalnum():
        t = t[1:]
    if len(t) != 3 or not t.isalnum():
        return None
    return t


def _normalize_tag_list(tags: list[str] | None) -> list[str] | None:
    if tags is None:
        return None
    out: list[str] = []
    for raw in tags:
        n = _normalize_tag(raw)
        if n and n not in out:
            out.append(n)
    return out


def _lookup_country(state: GameState, tag: str) -> CountryState | None:
    c = state.countries.get(tag)
    if c is not None:
        return c
    # 容错：键大小写不一致时仍命中真 TAG，不造幽灵键
    upper = tag.upper()
    for k, v in state.countries.items():
        if k.upper() == upper:
            return v
    return None


def _lookup_country_node(
    countries_root: ObjectNode | None, tag: str
) -> ObjectNode | None:
    if countries_root is None:
        return None
    raw = countries_root.values.get(tag)
    if isinstance(raw, ObjectNode):
        return raw
    upper = tag.upper()
    for k, val in countries_root.values.items():
        if k.upper() == upper and isinstance(val, ObjectNode):
            return val
    return None


def _default_military_dump_tags(state: GameState) -> list[str]:
    """玩家 + 其参战战争的攻守领袖。"""
    tags: list[str] = []
    player = state.player
    if player:
        n = _normalize_tag(player)
        if n:
            tags.append(n)
    for w in state.wars:
        involved = set()
        for t in (*w.attackers, *w.defenders):
            nt = _normalize_tag(t)
            if nt:
                involved.add(nt)
        player_n = _normalize_tag(player) if player else None
        if player_n and player_n not in involved:
            continue
        if w.attackers:
            n = _normalize_tag(w.attackers[0])
            if n:
                tags.append(n)
        if w.defenders:
            n = _normalize_tag(w.defenders[0])
            if n:
                tags.append(n)
    return list(dict.fromkeys(t for t in tags if t))


def format_military_dump(
    state: GameState,
    countries_root: ObjectNode | None,
    *,
    tags: list[str] | None = None,
) -> str:
    """格式化纪律/士气候选键与解析结果，供本机贴回确认。"""
    want = _normalize_tag_list(tags) or _default_military_dump_tags(state)
    lines: list[str] = [
        f"# dump-military  date={state.date}  player={state.player or '?'}",
        f"# source={state.source_path or '(text)'}",
        "# 说明：真档常无国块顶层 discipline/land_morale 裸字段；"
        "本工具会扫嵌套数值并聚合 modifier 内小幅 bonus（纪律按 1.0+sum）。",
        "# 无绝对 land_morale 时：用 army[*].regiment[*].morale 中位数作士气代理"
        "（parsed 旁注 regiment_morale_median）；纪律无数值保持 None，禁止臆造。",
        "# naval：navy[*].ship[*].morale 中位数 → parsed_naval_morale（可选舰船士气）。",
        "# named modifier 只有名字、无数值；需游戏定义文件才能换算，此处只列出。",
        f"# tags={want}",
        "",
    ]
    if not want:
        lines.append("(无目标 TAG：指定 --tags 或确保档内有 player / 战争领袖)")
        return "\n".join(lines)

    for tag in want:
        c = _lookup_country(state, tag)
        lines.append(f"## {tag}")
        if c is None:
            lines.append("  (countries 中无此 TAG)")
            lines.append("")
            continue
        lines.append(f"  name={c.name!r}")
        lines.append(f"  army_size={c.army_size}  navy_size={c.navy_size}")
        lines.append(f"  manpower={c.manpower}  max_manpower={c.max_manpower}")
        mil = (c.technology or {}).get("mil_tech")
        lines.append(f"  mil_tech={mil}")
        lines.append(f"  parsed_discipline={c.discipline}")
        if c.land_morale is not None and c.land_morale_proxy:
            lines.append(
                f"  parsed_land_morale={c.land_morale}  # regiment_morale_median（陆战单位士气代理）"
            )
        else:
            lines.append(f"  parsed_land_morale={c.land_morale}")
        lines.append(f"  parsed_naval_morale={c.naval_morale}")

        raw_node = _lookup_country_node(countries_root, tag)

        if raw_node is None:
            lines.append("  raw_country_node=(missing)")
            lines.append("")
            continue

        for key in _QUALITY_NUMERIC_KEYS:
            hits = _collect_key_floats(raw_node, key)
            if hits:
                lines.append(f"  numeric_{key}:")
                for loc, val in hits:
                    lines.append(f"    {loc}={val}")
            else:
                lines.append(f"  numeric_{key}: (none)")

        reg_morales = _unit_morale_values(raw_node, "army", "regiment")
        if reg_morales:
            med = _median(reg_morales)
            uniq = sorted(set(round(v, 4) for v in reg_morales))
            lines.append(
                f"  regiment_morale: n={len(reg_morales)} median={med} "
                f"distinct={uniq[:8]}{'…' if len(uniq) > 8 else ''}"
            )
        else:
            lines.append("  regiment_morale: (none)")

        ship_morales = _unit_morale_values(raw_node, "navy", "ship")
        if ship_morales:
            med = _median(ship_morales)
            lines.append(f"  ship_morale: n={len(ship_morales)} median={med}")
        else:
            lines.append("  ship_morale: (none)")

        named = _named_modifiers(raw_node)
        if named:
            lines.append(f"  named_modifiers ({len(named)}):")
            for n in named[:40]:
                lines.append(f"    - {n}")
            if len(named) > 40:
                lines.append(f"    … +{len(named) - 40} more")
        else:
            lines.append("  named_modifiers: (none)")

        cands = _candidate_military_keys(raw_node)
        if cands:
            lines.append(f"  candidate_keys ({len(cands)}):")
            for loc, summary in cands[:60]:
                lines.append(f"    {loc}={summary}")
            if len(cands) > 60:
                lines.append(f"    … +{len(cands) - 60} more")
        else:
            lines.append("  candidate_keys: (none matching discipline/morale/tradition/…)")
        lines.append("")
    return "\n".join(lines)


def dump_military(
    path: Path | str,
    *,
    tags: list[str] | None = None,
) -> str:
    """解析存档并返回 dump-military 文本（纪律/士气候选键）。"""
    path = Path(path)
    text = load_save_text(path)
    root = parse_clausewitz_v2(text)
    state = extract_game_state(root)
    state.source_path = str(path)
    countries_root = root.get_object("countries")
    return format_military_dump(state, countries_root, tags=tags)


def _iter_history_blocks(history: ObjectNode | None) -> list[tuple[str, ObjectNode]]:
    if history is None:
        return []
    items: list[tuple[str, ObjectNode]] = []
    for key, val in history.values.items():
        if isinstance(val, ObjectNode):
            items.append((key, val))
    for key, vals in history.multi.items():
        for val in vals:
            if isinstance(val, ObjectNode):
                items.append((key, val))
    return items


def _merge_sides_from_participants(
    attackers: list[str],
    defenders: list[str],
    participants: list,
) -> tuple[list[str], list[str]]:
    """用 participants.side 补全/校正攻守列表，保留既有顺序。"""
    att = [t for t in attackers if t]
    defe = [t for t in defenders if t]
    att_set, def_set = set(att), set(defe)
    for p in participants:
        tag = getattr(p, "tag", None) or ""
        side = getattr(p, "side", None)
        if not tag:
            continue
        if side == "attackers":
            if tag not in att_set:
                att.append(tag)
                att_set.add(tag)
            if tag in def_set:
                defe = [x for x in defe if x != tag]
                def_set.discard(tag)
        elif side == "defenders":
            if tag not in def_set:
                defe.append(tag)
                def_set.add(tag)
            if tag in att_set:
                att = [x for x in att if x != tag]
                att_set.discard(tag)
    return att, defe


def _lead_side(tags: list[str], leader: str) -> list[str]:
    """战争领袖放首位，避免字母序把附庸/盟友当成战争主角。"""
    if not leader:
        return list(tags)
    rest = [t for t in tags if t != leader]
    if leader in tags:
        return [leader, *rest]
    return [leader, *rest]


def _sides_from_history(
    history: ObjectNode | None, *, lifetime: bool = False
) -> tuple[list[str], list[str]]:
    """从 history 的 add_/rem_ attacker/defender 还原参战方。

    lifetime=False（active）：以 rem 后的当前集合为准。
    lifetime=True（previous_war）：忽略 rem，保留曾加入的攻/守方——
    结束时 rem 常把主角清掉，却留下无关残留 TAG。
    """
    attackers: set[str] = set()
    defenders: set[str] = set()
    ever_att: set[str] = set()
    ever_def: set[str] = set()
    for _date, block in _iter_history_blocks(history):
        for raw in block.get_list("add_attacker"):
            t = str(raw).strip('"')
            if t and t not in {"yes", "no"}:
                attackers.add(t)
                defenders.discard(t)
                ever_att.add(t)
                ever_def.discard(t)
        for raw in block.get_list("add_defender"):
            t = str(raw).strip('"')
            if t and t not in {"yes", "no"}:
                defenders.add(t)
                attackers.discard(t)
                ever_def.add(t)
                ever_att.discard(t)
        if not lifetime:
            for raw in block.get_list("rem_attacker"):
                attackers.discard(str(raw).strip('"'))
            for raw in block.get_list("rem_defender"):
                defenders.discard(str(raw).strip('"'))
    if lifetime:
        return sorted(ever_att), sorted(ever_def)
    if not attackers and not defenders and (ever_att or ever_def):
        return sorted(ever_att), sorted(ever_def)
    return sorted(attackers), sorted(defenders)


def _participant_score_fields(node: ObjectNode) -> tuple[float | None, float | None]:
    """返回 (显式战分, 贡献度 value)。

    真档 participants.value 多为参战贡献；显式战分键为 warscore / war_score。
    若仅有 value 且后续由战争级 score 覆盖，则 value 记为 contribution。
    """
    explicit: float | None = None
    for key in ("warscore", "war_score"):
        if node.has(key):
            explicit = node.get_float_optional(key)
            break
    contribution = node.get_float_optional("value")
    return explicit, contribution


def _parse_participants(
    war: ObjectNode,
    attackers: list[str],
    defenders: list[str],
) -> list[WarParticipant]:
    participants: list[WarParticipant] = []
    seen: set[str] = set()

    def add(tag: str, node: ObjectNode) -> None:
        if not tag or tag in seen:
            return
        seen.add(tag)
        side: str = "attackers" if tag in attackers else "defenders"
        side_s = node.get_str("side")
        if side_s in {"attackers", "defenders", "attacker", "defender"}:
            side = "attackers" if side_s.startswith("attack") else "defenders"
        explicit, contribution = _participant_score_fields(node)
        # 有符号 value（任一侧为负）时视为战分而非纯贡献
        signed_value = False
        if explicit is None and contribution is not None:
            # 延迟：调用方在收集完后再判定；此处先记下
            pass
        warscore = explicit if explicit is not None else 0.0
        known = explicit is not None
        participants.append(
            WarParticipant(
                tag=tag,
                side=side,  # type: ignore[arg-type]
                warscore=float(warscore),
                warscore_known=known,
                contribution=contribution,
                # stash raw value for signed pass — use contribution field
            )
        )
        # 暂存：若无 explicit，把 contribution 也写入以便二次判定
        if not known and contribution is not None:
            participants[-1].warscore = float(contribution)

    # 真档：重复键 participants={ value= tag= }
    for node in war.all_objects("participants"):
        tag = node.get_str("tag")
        if tag:
            add(tag, node)
            continue
        # 少见：participants 下挂 TAG={...}
        for key, val in node.values.items():
            if isinstance(val, ObjectNode) and len(key) == 3 and key.isalnum():
                add(key, val)

    # 合成样例：participants={ TEU={ warscore=42 } } 单对象
    part_obj = war.get_object("participants")
    if part_obj is not None and not war.all_objects("participants"):
        for key, val in part_obj.values.items():
            if isinstance(val, ObjectNode) and len(key) == 3 and key.isalnum():
                add(key, val)
    # 列表形态 participants={ { tag= value= } { ... } }
    for item in war.get_list("participants"):
        if isinstance(item, ObjectNode):
            tag = item.get_str("tag")
            if tag:
                add(tag, item)

    # 若多个参战 value 出现负数 → 按有符号战分处理
    values = [p.contribution for p in participants if p.contribution is not None]
    if values and any(v < 0 for v in values):
        for p in participants:
            if not p.warscore_known and p.contribution is not None:
                p.warscore = float(p.contribution)
                p.warscore_known = True

    return participants


def _parse_war_goal(
    war: ObjectNode, history: ObjectNode | None
) -> dict[str, str | int | None]:
    out: dict[str, str | int | None] = {
        "type": None,
        "casus_belli": None,
        "province": None,
        "tag": None,
    }
    for key in _WAR_GOAL_KEYS:
        node = war.get_object(key)
        if node is not None:
            out["type"] = node.get_str("type") or key
            out["casus_belli"] = node.get_str("casus_belli") or None
            out["province"] = node.get_int_optional("province")
            out["tag"] = node.get_str("tag") or None
            return out
    for _date, block in _iter_history_blocks(history):
        wg = block.get_object("war_goal")
        if wg is None:
            continue
        out["type"] = wg.get_str("type") or None
        out["casus_belli"] = wg.get_str("casus_belli") or None
        out["province"] = wg.get_int_optional("province")
        out["tag"] = wg.get_str("tag") or None
        return out
    return out


def _parse_battles(history: ObjectNode | None) -> list[WarBattle]:
    battles: list[WarBattle] = []
    for date, block in _iter_history_blocks(history):
        for battle in block.all_objects("battle"):
            battles.append(_battle_from_node(date, battle))
        b = block.get_object("battle")
        if b is not None and not block.all_objects("battle"):
            battles.append(_battle_from_node(date, b))
    # 重大：按双方损失合计降序，最多保留 5 场
    def loss_key(b: WarBattle) -> float:
        return (b.attacker_losses or 0) + (b.defender_losses or 0)

    battles.sort(key=loss_key, reverse=True)
    return battles[:5]


def _battle_from_node(date: str, battle: ObjectNode) -> WarBattle:
    att = battle.get_object("attacker")
    defe = battle.get_object("defender")
    result = battle.get("result")
    attacker_won: bool | None
    if isinstance(result, bool):
        attacker_won = result
    elif result in {"yes", "no"}:
        attacker_won = result == "yes"
    else:
        attacker_won = None
    return WarBattle(
        name=battle.get_str("name") or "",
        date=date,
        location=battle.get_int_optional("location"),
        attacker_won=attacker_won,
        attacker_tag=att.get_str("country") if att else None,
        defender_tag=defe.get_str("country") if defe else None,
        attacker_losses=att.get_float_optional("losses") if att else None,
        defender_losses=defe.get_float_optional("losses") if defe else None,
    )


def _count_occupied_provinces(
    root: ObjectNode, attackers: list[str], defenders: list[str]
) -> int | None:
    """owner≠controller 且分属交战双方时计为占领；档内无 controller 则返回 None。"""
    provinces = root.get_object("provinces")
    if provinces is None or not attackers or not defenders:
        return None
    att, defe = set(attackers), set(defenders)
    occupied = 0
    saw_controller = False
    for _key, node in provinces.values.items():
        if not isinstance(node, ObjectNode):
            continue
        owner = node.get_str("owner")
        controller = node.get_str("controller")
        if not controller:
            continue
        saw_controller = True
        if not owner or owner == controller:
            continue
        if (owner in defe and controller in att) or (owner in att and controller in defe):
            occupied += 1
    return occupied if saw_controller else None
