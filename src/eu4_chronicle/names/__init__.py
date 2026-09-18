"""TAG / 省份可读化：存档字段优先，其次内置中文映射，最后「国名(TAG)」兜底。"""

from __future__ import annotations

from eu4_chronicle.models import DiffEvent, DiffResult, GameState
from eu4_chronicle.names.catalog import COUNTRY_ZH, PROVINCE_ZH


class NameResolver:
    """把 tag / province id 解析成面向读者的中文（或可读）名称。"""

    def __init__(
        self,
        *,
        country_names: dict[str, str] | None = None,
        province_names: dict[int, str] | None = None,
    ) -> None:
        self._countries: dict[str, str] = dict(country_names or {})
        self._provinces: dict[int, str] = dict(province_names or {})

    @classmethod
    def from_states(cls, *states: GameState) -> NameResolver:
        countries: dict[str, str] = {}
        provinces: dict[int, str] = {}
        for state in states:
            for tag, c in state.countries.items():
                if c.name and c.name != tag:
                    countries.setdefault(tag, c.name)
            for pid, pname in (state.province_names or {}).items():
                if pname:
                    provinces.setdefault(pid, pname)
        return cls(country_names=countries, province_names=provinces)

    def country(self, tag: str | None) -> str:
        if not tag:
            return "未知势力"
        t = tag.strip().upper()
        if t in COUNTRY_ZH:
            return COUNTRY_ZH[t]
        save_name = self._countries.get(t) or self._countries.get(tag)
        if save_name and save_name != tag and save_name != t:
            # 存档常为英文；附 TAG 便于核对
            return f"{save_name}（{t}）"
        return f"{t}"

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
            i = int(pid)
        except (TypeError, ValueError):
            return str(pid)
        if i in PROVINCE_ZH:
            return PROVINCE_ZH[i]
        save_name = self._provinces.get(i)
        if save_name:
            return save_name
        return f"省份{i}"

    def provinces(self, ids: list[int] | list[str] | None) -> str:
        if not ids:
            return "（无）"
        return "、".join(self.province(p) for p in ids)

    def rewrite_event(self, ev: DiffEvent) -> DiffEvent:
        """用可读名称重写 summary，保留原始 detail。"""
        tag = ev.tag
        other = ev.other_tag
        c = self.country
        p = self.provinces
        detail = dict(ev.detail)
        summary = ev.summary

        if ev.kind == "date_changed":
            summary = f"时间从 {detail.get('from') or '?'} 推进至 {detail.get('to') or '?'}"
        elif ev.kind == "province_gained":
            summary = f"{c(tag)} 取得 {p(detail.get('provinces'))}"
        elif ev.kind == "province_lost":
            if detail.get("annexed_or_missing"):
                summary = f"{c(tag)} 从档册中消失（或已遭吞并）"
            else:
                summary = f"{c(tag)} 失去 {p(detail.get('provinces'))}"
        elif ev.kind == "core_gained":
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
        elif ev.kind == "war_started":
            att = "、".join(c(x) for x in detail.get("attackers") or [])
            defe = "、".join(c(x) for x in detail.get("defenders") or [])
            summary = f"爆发战争「{detail.get('name') or '未名'}」：{att or '？'} 进攻 {defe or '？'}"
        elif ev.kind == "war_ended":
            summary = f"战争「{detail.get('name') or '未名'}」落下帷幕"
        elif ev.kind == "war_score_changed":
            summary = (
                f"战争「{detail.get('war') or '未名'}」中"
                f"{c(tag)} 战争分数 {detail.get('from', 0):.0f} → {detail.get('to', 0):.0f}"
            )
        elif ev.kind == "development_changed":
            summary = f"{c(tag)} 发展度 {detail.get('from', 0):.0f} → {detail.get('to', 0):.0f}"
        elif ev.kind == "tech_changed":
            labels = {"adm_tech": "行政科技", "dip_tech": "外交科技", "mil_tech": "军事科技"}
            tech = labels.get(str(detail.get("tech")), str(detail.get("tech")))
            summary = f"{c(tag)} {tech} {detail.get('from')} → {detail.get('to')}"
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
                f"{c(tag)} 人力 {detail.get('from', 0):.1f}/{detail.get('max_from', 0):.1f} → "
                f"{detail.get('to', 0):.1f}/{detail.get('max_to', 0):.1f}"
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

        return ev.model_copy(update={"summary": summary})

    def rewrite_diff(self, diff: DiffResult) -> DiffResult:
        return diff.model_copy(
            update={"events": [self.rewrite_event(e) for e in diff.events]}
        )


def default_resolver() -> NameResolver:
    return NameResolver()
