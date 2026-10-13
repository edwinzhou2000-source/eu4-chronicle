"""玩家 AE / 包围网风险评估（基于 Diff 跳变与档内 active_relations）。"""

from __future__ import annotations

from dataclasses import dataclass, field

from eu4_chronicle.models import DiffResult, GameState

# 欧陆风云：包围网——对他国 AE ≥ 50（好感修正绝对值）
COALITION_AE_THRESHOLD = 50.0
# 「接近」阈值：用于提前警告，但不等于已可建网
APPROACHING_AE_THRESHOLD = 45.0
# 组网门槛：至少 3 国可入网即可组建包围网
COALITION_MEMBER_MIN = 3
# AI 只会以愤慨/宿敌态度入网（友好态度即使 AE 高也不会入）
_COALITION_ATTITUDES = frozenset({"attitude_outraged", "attitude_rivalry"})


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
    # AE≥50、好感<0、无停战、愤慨/宿敌、非同盟附庸 → 可入网
    coalition_eligible: list[str] = field(default_factory=list)
    # AE≥50 但因停战/好感/态度/同盟等不能入网
    coalition_blocked: list[str] = field(default_factory=list)
    # 兼容旧字段名
    coalition_truce_blocked: list[str] = field(default_factory=list)

    @property
    def is_scare_forbidden(self) -> bool:
        """AE=0 / 无变化且远未达网时禁止「高 AE」恐吓套话。"""
        return self.level in {"none", "low"}


def _player_block_tags(curr: GameState, player: str) -> set[str]:
    """同盟 / 附庸不能加入针对玩家的包围网。"""
    p = curr.countries.get(player)
    if p is None:
        return set()
    blocked = set(p.allies or []) | set(p.subjects or [])
    blocked.add(player)
    return blocked


def assess_player_ae(
    diff: DiffResult,
    *,
    ae_snapshot: dict[str, float] | None = None,
    country_label=None,
    curr: GameState | None = None,
) -> AeAssessment:
    """从 ae_changed、快照与 curr.active_relations 评估玩家面临的 AE。

    存档语义：
    - player.aggressive_expansion[other] = other 对 player 的 AE
    - AE = 他国 active_relations[player] 中 aggressive_expansion 好感修正的绝对值
    - 可入网（AI）：AE≥50、总好感<0、无停战、态度愤慨/宿敌、非同盟/附庸
    - 组网警告：可入网者 ≥ 3
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

    snapshot = dict(ae_snapshot or {})
    eligible: list[str] = []
    blocked: list[str] = []
    truce_blocked: list[str] = []
    dip_block = _player_block_tags(curr, player) if curr is not None and player else set()

    if curr is not None and player:
        rows: list[tuple[str, float, float, bool, str]] = []
        for tag, c in curr.countries.items():
            if tag == player:
                continue
            # 无地幽灵国（如灭国后的 POM）不参与 AE / 包围网叙述
            if not (c.owned_provinces or []):
                continue
            rel = (c.relations or {}).get(player)
            if rel is None:
                continue
            rows.append(
                (
                    tag,
                    float(rel.ae),
                    float(rel.opinion),
                    bool(rel.truce),
                    (rel.attitude or "").strip(),
                )
            )
        for tag, ae, opinion, truce, attitude in sorted(rows, key=lambda x: -x[1]):
            if ae > 0:
                snapshot[tag] = max(float(snapshot.get(tag, 0) or 0), ae)
                max_to = max(max_to, ae)
            if ae < COALITION_AE_THRESHOLD:
                continue
            # 好感用整数观感：>-0.5 视作未到「好感为负」（避免 -0.3 显示成 0）
            opinion_neg = opinion < -0.5
            attitude_ok = attitude in _COALITION_ATTITUDES
            ally_or_subject = tag in dip_block
            if (
                opinion_neg
                and not truce
                and attitude_ok
                and not ally_or_subject
            ):
                eligible.append(tag)
            else:
                blocked.append(tag)
                if truce:
                    truce_blocked.append(tag)

    # 无跳变时用快照补事实句
    if not vs_player and snapshot:
        for other, val in sorted(snapshot.items(), key=lambda x: -x[1])[:6]:
            v = float(val or 0)
            if v <= 0:
                continue
            if curr is not None:
                oc = curr.countries.get(other)
                if oc is None or not (oc.owned_provinces or []):
                    continue
            max_to = max(max_to, v)
            facts.append(f"{label(other)} 对 {label(player)} AE ≈ {v:.0f}")

    has_change = bool(vs_player)
    approaching = max_to >= APPROACHING_AE_THRESHOLD
    warn = len(eligible) >= COALITION_MEMBER_MIN

    if warn or max_to >= COALITION_AE_THRESHOLD:
        level = "high"
    elif approaching and (rising or has_change or max_to >= APPROACHING_AE_THRESHOLD):
        level = "approaching"
    elif has_change and rising and max_to >= 15:
        level = "rising"
    elif max_to > 0 or has_change:
        level = "low"
    else:
        level = "none"

    if not has_change and max_to <= 0:
        level = "none"

    if max_to >= COALITION_AE_THRESHOLD and level == "none":
        level = "high"

    return AeAssessment(
        has_change=has_change,
        max_to=max_to,
        max_from=max_from,
        rising=rising,
        warn_coalition=warn,
        approaching=approaching and max_to < COALITION_AE_THRESHOLD,
        facts=facts[:6],
        level=level,
        # 保留完整名单：成稿要写准确国数与国名，勿截断后说「约 N 国」
        coalition_eligible=eligible,
        coalition_blocked=blocked,
        coalition_truce_blocked=truce_blocked,
    )


def _format_tag_names(
    tags: list[str],
    country_label,
    *,
    limit: int = 8,
) -> str:
    """TAG 列表 →「甲、乙、丙」；超出 limit 加「等」。"""
    label = country_label or (lambda t: t or "?")
    names = [str(label(t)) for t in tags[:limit]]
    if not names:
        return ""
    if len(tags) > limit:
        return "、".join(names) + "等"
    return "、".join(names)


def ae_guidance_lines(
    ae: AeAssessment,
    *,
    player_label: str,
    for_user: bool = True,
    country_label=None,
) -> list[str]:
    """外交/战局可用的诚实 AE 文案（无恐吓套话、无平静期机制科普）。

    for_user=True：可进成稿正文。
    for_user=False：可含调试旁注，仅供 brief / LLM，勿写入用户成稿。
    国数、停战国名用档内准确名单，禁止「约 N 国因停战」。
    """
    n_ok = len(ae.coalition_eligible)
    n_blocked = len(ae.coalition_blocked)
    n_truce = len(ae.coalition_truce_blocked)
    truce_set = set(ae.coalition_truce_blocked)
    other_blocked = [t for t in ae.coalition_blocked if t not in truce_set]
    n_other = len(other_blocked)

    if ae.level == "none":
        lines = ["当前未见高 AE / 包围网风险低。"]
        if not for_user:
            lines.append("档内无 AE 跳变或显著数值；勿编造恐吓；勿写机制科普。")
        return lines

    if ae.level == "low":
        lines = ["当前未见高 AE / 包围网风险低。"]
        if ae.facts:
            lines.append("已知数值：" + "；".join(ae.facts))
        elif ae.has_change:
            lines.append("虽有轻微 AE 变动，但远未接近包围网门槛。")
        return lines

    if ae.warn_coalition:
        ok_names = _format_tag_names(ae.coalition_eligible, country_label)
        lines = [
            f"包围网风险高：可入网 {n_ok} 国对 {player_label} AE≥50、好感<0、"
            f"愤慨/宿敌且无停战（峰值 AE {ae.max_to:.0f}）"
            + (f"：{ok_names}" if ok_names else "")
            + "。",
        ]
        if ae.facts:
            lines.append("事实：" + "；".join(ae.facts))
        lines.append("忌在高 AE 窗口另开第二战场；优先改善关系与停战缓冲。")
        return lines

    if ae.level == "high" or ae.max_to >= COALITION_AE_THRESHOLD:
        lines = [
            f"多国对 {player_label} AE 已高（峰值 {ae.max_to:.0f}≥50），"
            f"可入网者 {n_ok} 国（需≥{COALITION_MEMBER_MIN}），包围网尚未形成。",
        ]
        if n_truce:
            named = _format_tag_names(ae.coalition_truce_blocked, country_label)
            lines.append(
                f"其中停战未能入网 {n_truce} 国"
                + (f"：{named}" if named else "")
                + "。"
            )
        if n_other:
            named = _format_tag_names(other_blocked, country_label)
            lines.append(
                f"另有 {n_other} 国因好感未负/态度非愤慨或同盟附庸而不能入网"
                + (f"：{named}" if named else "")
                + "。"
            )
        elif n_blocked and not n_truce:
            lines.append(
                f"另有 {n_blocked} 国因好感未负/态度非愤慨或同盟附庸而不能入网。"
            )
        if ae.facts:
            lines.append("事实：" + "；".join(ae.facts))
        if not for_user:
            lines.append(
                "可入网：AE≥50 + 好感<0 + 无停战 + 愤慨/宿敌 + 非同盟附庸；"
                f"至少 {COALITION_MEMBER_MIN} 国。国数与名单须按上列写准，禁止「约 N 国」。"
            )
        return lines

    if ae.level == "rising":
        lines = [
            f"{player_label} 面临的扩张侵略度有所上升（峰值 {ae.max_to:.0f}），"
            f"仍低于包围网常见门槛 50。"
        ]
        if ae.facts:
            lines.append("事实：" + "；".join(ae.facts))
        if not for_user:
            lines.append("可留意改善关系，但无需恐吓式措辞。")
        return lines

    if ae.level == "approaching":
        lines = [
            f"AE 已接近包围网门槛（{ae.max_to:.0f}，门槛 50）。",
        ]
        if ae.facts:
            lines.append("事实：" + "；".join(ae.facts))
        lines.append("建议：暂缓大规模割地，优先改善关系与结盟缓冲。")
        return lines

    lines = [f"AE 峰值 {ae.max_to:.0f}。"]
    if ae.facts:
        lines.append("事实：" + "；".join(ae.facts))
    return lines


# 无 AE 跳变/高 AE 时禁止写入成稿的机制科普句（LLM 易复读）
MECHANISM_FLUFF_PHRASES = (
    "宿敌关系本身不直接",
    "宣战亦不结算 AE",
    "宣战本身不会立刻结算 AE",
    "宣战本身不等于结算 AE",
    "割地与苛刻和约才会",
    "机制上，包围网",
    "（机制：包围网一般需",
    "机制：包围网一般需",
    "并点明包围网一般需 AE>50",
)


def contains_mechanism_fluff(text: str) -> bool:
    return any(p in text for p in MECHANISM_FLUFF_PHRASES)


# 成稿在低 AE 时禁止的恐吓片段（「未见高 AE」为允许的诚实表述）
AE_SCARE_PHRASES = (
    "AE 高企",
    "勿在下一次割地时掉以轻心",
    "对冲高 AE",
    "忌在 AE 高企",
    "列强开始侧目",
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
        if any(a in text[max(0, i - 6) : i + 6] for a in allowed_contexts):
            idx = i + 1
            continue
        if any(a in text[max(0, i - len(a)) : i + 4] for a in allowed_contexts):
            idx = i + 1
            continue
        return True
    return False
