"""玩家 AE / 包围网风险评估（基于 Diff 跳变与可选档内数值）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from eu4_chronicle.models import DiffResult

# 欧陆风云：包围网一般需对你 AE 超过 50
COALITION_AE_THRESHOLD = 50.0
# 「接近」阈值：用于提前警告，但不等于已可建网
APPROACHING_AE_THRESHOLD = 45.0


@dataclass
class AeAssessment:
    """对玩家的 AE 态势。"""

    has_change: bool = False
    max_to: float = 0.0
    max_from: float = 0.0
    rising: bool = False
    warn_coalition: bool = False
    approaching: bool = False
    facts: list[str] = field(default_factory=list)
    level: str = "none"  # none | low | rising | approaching | high

    @property
    def is_scare_forbidden(self) -> bool:
        """AE=0 / 无变化时禁止「高 AE」恐吓套话。"""
        return self.level in {"none", "low"}


def assess_player_ae(
    diff: DiffResult,
    *,
    ae_snapshot: dict[str, float] | None = None,
    country_label=None,
) -> AeAssessment:
    """从 ae_changed 事件与可选快照评估玩家面临的 AE。

    存档语义（本项目）：player.aggressive_expansion[other] = other 对 player 的 AE。
    """
    label = country_label or (lambda t: t or "?")
    player = diff.player
    vs_player = [
        e
        for e in diff.events
        if e.kind == "ae_changed" and (e.detail.get("target") or e.tag) == player
    ]

    max_to = 0.0
    max_from = 0.0
    rising = False
    facts: list[str] = []

    for e in vs_player:
        fr = float(e.detail.get("from") or 0)
        to = float(e.detail.get("to") or 0)
        max_to = max(max_to, to)
        max_from = max(max_from, fr)
        if to > fr + 0.5:
            rising = True
        viewer = e.detail.get("viewer") or e.other_tag
        facts.append(f"{label(viewer)} 对 {label(player)} AE {fr:.0f}→{to:.0f}")

    # 无跳变时用快照（若有）
    if ae_snapshot and not vs_player:
        for other, val in sorted(ae_snapshot.items(), key=lambda x: -x[1]):
            v = float(val or 0)
            if v <= 0:
                continue
            max_to = max(max_to, v)
            facts.append(f"{label(other)} 对 {label(player)} AE ≈ {v:.0f}")

    has_change = bool(vs_player)
    approaching = max_to >= APPROACHING_AE_THRESHOLD
    warn = max_to >= COALITION_AE_THRESHOLD or (rising and max_to >= APPROACHING_AE_THRESHOLD)

    if max_to >= COALITION_AE_THRESHOLD:
        level = "high"
    elif approaching and (rising or has_change):
        level = "approaching"
    elif has_change and rising and max_to >= 15:
        level = "rising"
    elif max_to > 0 or has_change:
        level = "low"
    else:
        level = "none"

    # 无跳变且快照也空/全 0
    if not has_change and max_to <= 0:
        level = "none"

    return AeAssessment(
        has_change=has_change,
        max_to=max_to,
        max_from=max_from,
        rising=rising,
        warn_coalition=warn,
        approaching=approaching and max_to < COALITION_AE_THRESHOLD,
        facts=facts[:6],
        level=level,
    )


def ae_guidance_lines(ae: AeAssessment, *, player_label: str) -> list[str]:
    """外交/战局可用的诚实 AE 文案（无恐吓套话）。"""
    mech = "（机制：包围网一般需对他国对你 AE 超过 50）"
    if ae.level == "none":
        return [
            f"当前未见高 AE / 包围网风险低{mech}。",
            f"档内无 AE 跳变，也未读到主要邻国对你的显著扩张侵略度；勿编造恐吓。",
        ]
    if ae.level == "low":
        lines = [f"当前未见高 AE / 包围网风险低{mech}。"]
        if ae.facts:
            lines.append("已知数值：" + "；".join(ae.facts))
        elif ae.has_change:
            lines.append("虽有轻微 AE 变动，但远未接近包围网门槛。")
        return lines
    if ae.level == "rising":
        lines = [
            f"{player_label} 面临的扩张侵略度有所上升（峰值约 {ae.max_to:.0f}），"
            f"仍低于包围网常见门槛 50{mech}。"
        ]
        if ae.facts:
            lines.append("事实：" + "；".join(ae.facts))
        lines.append("可留意改善关系，但无需恐吓式措辞。")
        return lines
    if ae.level == "approaching":
        lines = [
            f"AE 已接近包围网门槛（约 {ae.max_to:.0f}，门槛 50）{mech}。",
        ]
        if ae.facts:
            lines.append("事实：" + "；".join(ae.facts))
        lines.append("建议：暂缓大规模割地，优先改善关系与结盟缓冲。")
        return lines
    # high
    lines = [
        f"AE 已达到或超过包围网门槛（约 {ae.max_to:.0f} ≥ 50）{mech}。",
    ]
    if ae.facts:
        lines.append("事实：" + "；".join(ae.facts))
    lines.append("警告：忌在高 AE 窗口另开第二战场；用改善关系与外交隔离对冲联军风险。")
    return lines


# 成稿在低 AE 时禁止的恐吓片段（「未见高 AE」为允许的诚实表述）
AE_SCARE_PHRASES = (
    "AE 高企",
    "勿在下一次割地时掉以轻心",
    "对冲高 AE",
    "忌在 AE 高企",
    "列强开始侧目",
    "包围网风险高",
)


def contains_ae_scare(text: str) -> bool:
    """检测恐吓套话；允许「未见高 AE」等诚实否定句。"""
    if any(p in text for p in AE_SCARE_PHRASES):
        return True
    # 单独的「高 AE」恐吓，但排除「未见高 AE」等否定语境
    allowed_contexts = ("未见高 AE", "无高 AE", "不是高 AE", "非高 AE")
    idx = 0
    while True:
        i = text.find("高 AE", idx)
        if i < 0:
            break
        window = text[max(0, i - 4) : i + 4]
        if any(a in text[max(0, i - 6) : i + 6] for a in allowed_contexts):
            idx = i + 1
            continue
        # 若该处落在允许短语内则跳过
        if any(a in text[max(0, i - len(a)) : i + 4] for a in allowed_contexts):
            idx = i + 1
            continue
        return True
    return False
