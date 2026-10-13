"""TAG / 省份可读化：内置中文 → 可读存档名 → 游戏 localisation → 成型提示 → 兜底。"""

from __future__ import annotations

import re

from eu4_game_report.localisation import GameLocalisation, looks_mojibake
from eu4_game_report.models import CountryState, DiffEvent, DiffResult, GameState
from eu4_game_report.names.catalog import COUNTRY_EN_ZH, COUNTRY_ZH, PLACE_EN_ZH, PROVINCE_ZH
from eu4_game_report.names.wars import translate_war_name

# government_name 如 NYDD_NED_unite_province_gov_2 → 抽出 NED
_GOV_TAG_RE = re.compile(r"(?:^|_)([A-Z]{3})(?:_|$)")


def _fmt_quality_num(v: float | int) -> str:
    f = float(v)
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.3f}".rstrip("0").rstrip(".")


def _fmt_force_side_zh(label: str, snap: dict) -> str:
    """可读国名 + 军科/陆军/人力/纪律/士气（缺则省略）。"""
    bits: list[str] = [label]
    if snap.get("mil_tech") is not None:
        bits.append(f"军科{int(snap['mil_tech'])}")
    if snap.get("army_size") is not None:
        bits.append(f"陆军{float(snap['army_size']):.0f}")
    if snap.get("navy_size") is not None and float(snap["navy_size"]) > 0:
        bits.append(f"海军{float(snap['navy_size']):.0f}")
    if snap.get("manpower") is not None:
        mx = snap.get("max_manpower")
        if mx is not None:
            bits.append(
                f"当前人力{float(snap['manpower']):.1f}k/上限{float(mx):.1f}k"
            )
        else:
            bits.append(f"当前人力{float(snap['manpower']):.1f}k")
    if snap.get("discipline") is not None:
        bits.append(f"纪律{_fmt_quality_num(snap['discipline'])}")
    if snap.get("land_morale") is not None:
        approx = "≈" if snap.get("land_morale_proxy") else ""
        bits.append(f"士气{approx}{_fmt_quality_num(snap['land_morale'])}")
    if snap.get("naval_morale") is not None:
        bits.append(f"舰船士气{_fmt_quality_num(snap['naval_morale'])}")
    return " ".join(bits)


def _place_zh(name: str) -> str:
    """英文（或可读）地名尽量换成中文。"""
    if name in PLACE_EN_ZH:
        return PLACE_EN_ZH[name]
    lower = name.lower()
    for en, zh in PLACE_EN_ZH.items():
        if en.lower() == lower:
            return zh
    return name


def _country_zh(name: str) -> str:
    """英文国名尽量换成中文。"""
    if name in COUNTRY_EN_ZH:
        return COUNTRY_EN_ZH[name]
    lower = name.lower()
    for en, zh in COUNTRY_EN_ZH.items():
        if en.lower() == lower:
            return zh
    return name


def _formable_hint_tags(c: CountryState) -> list[str]:
    """从政府脚本名 / 换皮来源推断可读原国 TAG（优先成型目标如 NED）。"""
    hints: list[str] = []
    gov = (c.government_name or "").strip()
    if gov:
        for m in _GOV_TAG_RE.finditer(gov.upper()):
            ht = m.group(1)
            if ht not in hints:
                hints.append(ht)
    for pt in c.previous_country_tags or []:
        u = str(pt).strip().upper()
        if u and u not in hints:
            hints.append(u)
    cf = (c.changed_tag_from or "").strip().upper()
    if cf and cf not in hints:
        hints.append(cf)
    return hints


class NameResolver:
    """把 tag / province id 解析成面向读者的中文（或可读）名称。"""

    def __init__(
        self,
        *,
        country_names: dict[str, str] | None = None,
        province_names: dict[int, str] | None = None,
        formable_hints: dict[str, list[str]] | None = None,
        loc: GameLocalisation | None = None,
    ) -> None:
        self._countries: dict[str, str] = dict(country_names or {})
        self._provinces: dict[int, str] = dict(province_names or {})
        self._formable_hints: dict[str, list[str]] = {
            k.upper(): list(v) for k, v in (formable_hints or {}).items()
        }
        self._loc = loc

    @classmethod
    def from_states(
        cls,
        *states: GameState,
        loc: GameLocalisation | None = None,
    ) -> NameResolver:
        countries: dict[str, str] = {}
        provinces: dict[int, str] = {}
        hints: dict[str, list[str]] = {}
        for state in states:
            for tag, c in state.countries.items():
                t = tag.strip().upper()
                if (
                    c.name
                    and c.name != tag
                    and c.name != t
                    and not looks_mojibake(c.name)
                ):
                    countries.setdefault(t, c.name)
                fh = _formable_hint_tags(c)
                if fh:
                    existing = hints.setdefault(t, [])
                    for h in fh:
                        if h != t and h not in existing:
                            existing.append(h)
            for pid, pname in (state.province_names or {}).items():
                if not pname or looks_mojibake(pname):
                    continue
                provinces.setdefault(abs(int(pid)), pname)
        return cls(
            country_names=countries,
            province_names=provinces,
            formable_hints=hints,
            loc=loc,
        )

    def _known_country_label(self, t: str) -> str | None:
        """仅查表 / 本地化，不走成型提示（避免递归）。"""
        if t in COUNTRY_ZH:
            return COUNTRY_ZH[t]
        save_name = self._countries.get(t)
        if save_name and save_name != t and not looks_mojibake(save_name):
            return _country_zh(save_name)
        if self._loc is not None:
            loc_name = self._loc.get(t)
            if loc_name and not looks_mojibake(loc_name):
                return _country_zh(loc_name)
        return None

    def country(self, tag: str | None) -> str:
        if not tag:
            return "未知势力"
        t = tag.strip().upper()
        known = self._known_country_label(t)
        if known is not None:
            return known
        for hint in self._formable_hints.get(t, []):
            label = self._known_country_label(hint)
            if label is not None:
                return label
        return t

    def country_with_tag(self, tag: str | None) -> str:
        """正文少用；需要对照时：条顿骑士团（TEU）。"""
        if not tag:
            return "未知势力"
        t = tag.strip().upper()
        base = self.country(t)
        if f"（{t}）" in base or base == t:
            return base
        return f"{base}（{t}）"

    def province(self, pid: int | str) -> str:
        try:
            i = abs(int(pid))
        except (TypeError, ValueError):
            return str(pid)
        if i in PROVINCE_ZH:
            return PROVINCE_ZH[i]
        save_name = self._provinces.get(i)
        if save_name and not looks_mojibake(save_name):
            return _place_zh(save_name)
        if self._loc is not None:
            loc_name = self._loc.get(f"PROV{i}")
            if loc_name and not looks_mojibake(loc_name):
                return _place_zh(loc_name)
        return f"省份{i}"

    def war_goal(self, goal_type: str | None) -> str | None:
        """有中文映射才返回；原始脚本键（含 _）返回 None，避免成稿泄漏。"""
        from eu4_game_report.names.catalog import WAR_GOAL_ZH

        if not goal_type:
            return None
        return WAR_GOAL_ZH.get(goal_type)

    def casus_belli(self, cb: str | None) -> str | None:
        from eu4_game_report.names.catalog import CASUS_BELLI_ZH

        if not cb:
            return None
        return CASUS_BELLI_ZH.get(cb)

    def provinces(
        self, ids: list[int] | list[str] | None, *, limit: int | None = None
    ) -> str:
        if not ids:
            return "（无）"
        labels = [self.province(p) for p in ids]
        if limit is not None and len(labels) > limit:
            head = "、".join(labels[:limit])
            return f"{head}等共{len(labels)}处"
        return "、".join(labels)

    def war(self, name: str | None, *, attackers: list | None = None, defenders: list | None = None) -> str:
        return translate_war_name(
            name,
            attackers=list(attackers or []),
            defenders=list(defenders or []),
            country_label=self.country,
        )

    def rewrite_event(self, ev: DiffEvent) -> DiffEvent:
        """用可读名称重写 summary，保留原始 detail（战争名写入 name_zh）。"""
        tag = ev.tag
        other = ev.other_tag
        c = self.country
        p = self.provinces
        detail = dict(ev.detail)
        summary = ev.summary

        if ev.kind == "date_changed":
            summary = f"时间从 {detail.get('from') or '?'} 推进至 {detail.get('to') or '?'}"
        elif ev.kind == "player_tag_changed":
            summary = (
                f"玩家 TAG 变化：{detail.get('from') or other or '?'} → "
                f"{detail.get('to') or tag or '?'}（成立新国家或换皮）"
            )
        elif ev.kind == "mission_completed":
            from eu4_game_report.localisation import is_readable_display_title

            title = detail.get("title")
            if title and detail.get("loc_found") and is_readable_display_title(str(title)):
                summary = f"已完成任务「{title}」"
            else:
                summary = "已完成一项任务（无可用本地化标题）"
        elif ev.kind == "missions_lost":
            n = detail.get("count") or len(detail.get("mission_ids") or [])
            summary = f"部分旧任务完成记录在新档中消失（{n} 项；可能换树重置），不计入新完成"
        elif ev.kind == "province_gained":
            summary = f"{c(tag)} 取得 {p(detail.get('provinces'))}"
        elif ev.kind == "province_lost":
            if detail.get("annexed_or_missing"):
                summary = f"{c(tag)} 从档册中消失（或已遭吞并）"
            else:
                summary = f"{c(tag)} 失去 {p(detail.get('provinces'))}"
        elif ev.kind == "core_gained":
            # 默认战报会滤掉此类；include_global 时仍可读化
            summary = f"{c(tag)} 新增核心：{p(detail.get('cores'))}"
        elif ev.kind == "core_lost":
            summary = f"{c(tag)} 失去核心：{p(detail.get('cores'))}"
        elif ev.kind == "alliance_formed":
            summary = f"{c(tag)} 与 {c(other)} 结成同盟"
        elif ev.kind == "alliance_broken":
            summary = f"{c(tag)} 与 {c(other)} 同盟破裂"
        elif ev.kind == "rival_set":
            summary = f"{c(tag)} 将 {c(other)} 列为宿敌"
        elif ev.kind == "rival_cleared":
            summary = f"{c(tag)} 不再视 {c(other)} 为宿敌"
        elif ev.kind == "war_started":
            wname = self.war(
                detail.get("name"),
                attackers=detail.get("attackers"),
                defenders=detail.get("defenders"),
            )
            detail["name_zh"] = wname
            att = "、".join(c(x) for x in detail.get("attackers") or [])
            defe = "、".join(c(x) for x in detail.get("defenders") or [])
            summary = f"爆发战争「{wname}」：{att or '？'} 进攻 {defe or '？'}"
            pws = detail.get("player_warscore")
            if pws is not None:
                try:
                    summary += f"；玩家战分 {float(pws):+.0f}"
                except (TypeError, ValueError):
                    pass
        elif ev.kind == "war_ended":
            wname = self.war(
                detail.get("name"),
                attackers=detail.get("attackers"),
                defenders=detail.get("defenders"),
            )
            detail["name_zh"] = wname
            summary = f"战争「{wname}」落下帷幕"
        elif ev.kind == "war_score_changed":
            wname = self.war(
                detail.get("war") or detail.get("name"),
                attackers=detail.get("attackers"),
                defenders=detail.get("defenders"),
            )
            detail["name_zh"] = wname
            fr, to = detail.get("from"), detail.get("to")
            try:
                fr_s = f"{float(fr):+.0f}" if fr is not None else "?"
                to_s = f"{float(to):+.0f}" if to is not None else "?"
            except (TypeError, ValueError):
                fr_s, to_s = str(fr), str(to)
            summary = f"战争「{wname}」中{c(tag)} 战争分数 {fr_s} → {to_s}"
        elif ev.kind == "subject_changed":
            if detail.get("appeared"):
                summary = f"{c(tag)} 出现在后期档中（新生或释放）"
            else:
                gained = detail.get("gained") or []
                lost = detail.get("lost") or []
                parts = []
                if gained:
                    parts.append("收附 " + "、".join(c(x) for x in gained))
                if lost:
                    parts.append("失去附庸 " + "、".join(c(x) for x in lost))
                summary = f"{c(tag)} 附庸变化：" + ("；".join(parts) if parts else "结构变动")
                if detail.get("supersedes_alliance_break") and gained:
                    summary = f"{c(tag)} 收附 " + "、".join(c(x) for x in gained)
                    if lost:
                        summary += "；失去附庸 " + "、".join(c(x) for x in lost)
        elif ev.kind == "development_changed":
            summary = f"{c(tag)} 发展度 {detail.get('from', 0):.0f} → {detail.get('to', 0):.0f}"
        elif ev.kind == "tech_changed":
            labels = {"adm_tech": "行政科技", "dip_tech": "外交科技", "mil_tech": "军事科技"}
            tech = labels.get(str(detail.get("tech")), str(detail.get("tech")))
            summary = f"{c(tag)} {tech} {detail.get('from')} → {detail.get('to')}"
        elif ev.kind == "war_tech_compare":
            foe = detail.get("foe") or other
            player_force = dict(detail.get("player_force") or {})
            foe_force = dict(detail.get("foe_force") or {})
            early = bool(detail.get("early_game"))
            mil_gap = detail.get("mil_gap")
            has_both_mil = bool(detail.get("has_both_mil"))
            # 与 filter summary 一致：无信号的数量维不展示
            if not detail.get("has_both_army"):
                player_force.pop("army_size", None)
                foe_force.pop("army_size", None)
            if not detail.get("has_both_navy"):
                player_force.pop("navy_size", None)
                foe_force.pop("navy_size", None)
            if not detail.get("has_both_manpower"):
                player_force.pop("manpower", None)
                player_force.pop("max_manpower", None)
                foe_force.pop("manpower", None)
                foe_force.pop("max_manpower", None)
            if not detail.get("has_both_discipline"):
                player_force.pop("discipline", None)
                foe_force.pop("discipline", None)
            if not detail.get("has_both_land_morale"):
                player_force.pop("land_morale", None)
                player_force.pop("land_morale_proxy", None)
                foe_force.pop("land_morale", None)
                foe_force.pop("land_morale_proxy", None)
            if not detail.get("has_both_naval_morale"):
                player_force.pop("naval_morale", None)
                foe_force.pop("naval_morale", None)
            if player_force or foe_force:
                summary = (
                    f"军力对比：{_fmt_force_side_zh(c(tag), player_force)} vs "
                    f"{_fmt_force_side_zh(c(foe), foe_force)}"
                )
            else:
                player_mil = detail.get("player_mil")
                foe_mil = detail.get("foe_mil")
                summary = f"军事科技：{c(tag)} {player_mil} vs {c(foe)} {foe_mil}"
            if has_both_mil and mil_gap is not None:
                if early and abs(int(mil_gap)) == 1:
                    lead = c(tag) if int(mil_gap) > 0 else c(foe)
                    summary += f"（早期轻代差，{lead} 军科领先 1 级）"
                elif mil_gap == 0:
                    summary += "（军科同档）"
            wname = self.war(
                detail.get("name") or detail.get("war"),
                attackers=detail.get("attackers"),
                defenders=detail.get("defenders"),
            )
            detail["name_zh"] = wname
            detail["player_label"] = c(tag)
            detail["foe_label"] = c(foe)
        elif ev.kind == "religion_changed":
            summary = f"{c(tag)} 国教 {detail.get('from')} → {detail.get('to')}"
        elif ev.kind == "monarch_changed":
            # 保留原 summary 中的君主名，只替换前缀 tag
            if summary.startswith(f"{tag} "):
                summary = c(tag) + summary[len(tag) :]
            else:
                summary = f"{c(tag)} 君主更迭"
        elif ev.kind == "manpower_changed":
            summary = (
                f"{c(tag)} 当前人力 {float(detail.get('from', 0)):.1f}k→"
                f"{float(detail.get('to', 0)):.1f}k；"
                f"人力上限 {float(detail.get('max_from', 0)):.1f}k→"
                f"{float(detail.get('max_to', 0)):.1f}k"
            )
        elif ev.kind == "army_changed":
            summary = f"{c(tag)} 陆军约 {detail.get('from', 0):.0f} → {detail.get('to', 0):.0f}"
        elif ev.kind == "navy_changed":
            summary = f"{c(tag)} 海军约 {detail.get('from', 0):.0f} → {detail.get('to', 0):.0f}"
        elif ev.kind == "ae_changed":
            viewer = detail.get("viewer") or other
            target = detail.get("target") or tag
            summary = (
                f"{c(viewer)} 对 {c(target)} 的扩张侵略度 "
                f"{detail.get('from', 0):.0f} → {detail.get('to', 0):.0f}"
            )
        elif ev.kind == "opinion_changed":
            summary = (
                f"{c(tag)} 对 {c(other)} 好感 "
                f"{detail.get('from', 0):.0f} → {detail.get('to', 0):.0f}"
            )
        elif ev.kind == "stability_changed":
            summary = f"{c(tag)} 稳定度 {detail.get('from')} → {detail.get('to')}"
        elif ev.kind == "prestige_changed":
            summary = f"{c(tag)} 威望 {detail.get('from', 0):.0f} → {detail.get('to', 0):.0f}"

        return ev.model_copy(update={"summary": summary, "detail": detail})

    def rewrite_diff(self, diff: DiffResult) -> DiffResult:
        return diff.model_copy(
            update={"events": [self.rewrite_event(e) for e in diff.events]}
        )


def default_resolver() -> NameResolver:
    return NameResolver()
