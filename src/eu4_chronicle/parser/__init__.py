"""非铁人 .eu4 存档加载与 GameState 抽取。"""

from __future__ import annotations

import zipfile
from pathlib import Path

from eu4_chronicle.models import (
    CountryState,
    GameState,
    Monarch,
    WarBattle,
    WarParticipant,
    WarState,
)
from eu4_chronicle.parser.clausewitz import ObjectNode, parse_clausewitz_v2

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
        wars.append(_parse_one_war(war, root))
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


def _parse_one_war(war: ObjectNode, root: ObjectNode) -> WarState:
    history = war.get_object("history")
    attackers = [str(x).strip('"') for x in war.get_list("attackers") if x]
    defenders = [str(x).strip('"') for x in war.get_list("defenders") if x]
    if not attackers and not defenders:
        attackers, defenders = _sides_from_history(history)

    participants = _parse_participants(war, attackers, defenders)
    goal = _parse_war_goal(war, history)
    battles = _parse_battles(history)
    occupied = _count_occupied_provinces(root, attackers, defenders)
    raw_scores = _collect_raw_score_fields(war)

    state = WarState(
        name=war.get_str("name") or war.get_str("war_name") or "未命名战争",
        attackers=attackers,
        defenders=defenders,
        participants=participants,
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
            f"  # ← 战争目标加分 / ticking（约 -25～+25）"
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


def _sides_from_history(history: ObjectNode | None) -> tuple[list[str], list[str]]:
    """从 history 的 add_/rem_ attacker/defender 还原当前参战方。"""
    attackers: set[str] = set()
    defenders: set[str] = set()
    for _date, block in _iter_history_blocks(history):
        for raw in block.get_list("add_attacker"):
            t = str(raw).strip('"')
            if t and t not in {"yes", "no"}:
                attackers.add(t)
                defenders.discard(t)
        for raw in block.get_list("add_defender"):
            t = str(raw).strip('"')
            if t and t not in {"yes", "no"}:
                defenders.add(t)
                attackers.discard(t)
        for raw in block.get_list("rem_attacker"):
            attackers.discard(str(raw).strip('"'))
        for raw in block.get_list("rem_defender"):
            defenders.discard(str(raw).strip('"'))
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
