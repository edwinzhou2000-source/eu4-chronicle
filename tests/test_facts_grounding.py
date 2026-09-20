"""事实锚定：附庸+断盟合并、高战分措辞、反空话禁词。"""

from __future__ import annotations

from eu4_chronicle.ae import assess_player_ae
from eu4_chronicle.agents import _mock_editor, _mock_narrative_paragraph, _mock_war_section
from eu4_chronicle.agents.prompts import EDITOR_SYSTEM, HISTORIAN_SYSTEM
from eu4_chronicle.diff import diff_states
from eu4_chronicle.filter import consolidate_subject_alliance, filter_diff
from eu4_chronicle.models import (
    CountryState,
    DiffEvent,
    DiffResult,
    GameState,
    WarParticipant,
    WarState,
)
from eu4_chronicle.names import NameResolver
from eu4_chronicle.warscore import (
    BANNED_EMPTY_PHRASES,
    assess_player_wars,
    classify_warscore,
    contains_banned_empty_phrase,
    tier_phrase,
)


def _teu_diff(*events: DiffEvent) -> DiffResult:
    return DiffResult(
        prev_date="1447.1.1",
        curr_date="1454.1.1",
        player="TEU",
        events=list(events),
    )


def test_classify_warscore_tiers():
    assert classify_warscore(68) == "decisive"
    assert classify_warscore(50) == "decisive"
    assert classify_warscore(30) == "advantage"
    assert classify_warscore(0) == "contested"
    assert classify_warscore(-25) == "disadvantage"
    assert classify_warscore(-60) == "collapse"
    assert "基本打赢" in tier_phrase("decisive", score=68)
    assert "胜负未定" in tier_phrase("contested", score=2)
    assert "胜负未定" not in tier_phrase("decisive", score=68)


def test_alliance_break_plus_vassalize_merges_to_vassal():
    events = [
        DiffEvent(
            kind="alliance_broken",
            tag="TEU",
            other_tag="LIV",
            summary="TEU 与 LIV 同盟破裂",
        ),
        DiffEvent(
            kind="subject_changed",
            tag="TEU",
            summary="TEU 附庸变化：+['LIV'] -[]",
            detail={"gained": ["LIV"], "lost": []},
        ),
        DiffEvent(
            kind="alliance_formed",
            tag="TEU",
            other_tag="BOH",
            summary="TEU 与 BOH 结成同盟",
        ),
    ]
    merged = consolidate_subject_alliance(events, player="TEU")
    kinds = [e.kind for e in merged]
    assert "alliance_broken" not in kinds
    assert "subject_changed" in kinds
    assert "alliance_formed" in kinds
    sub = next(e for e in merged if e.kind == "subject_changed")
    assert "收附" in sub.summary
    assert "LIV" in sub.summary
    assert sub.detail.get("supersedes_alliance_break") == ["LIV"]


def test_mock_narrative_prioritizes_vassalize_not_alliance_tragedy():
    names = NameResolver()
    events = [
        DiffEvent(
            kind="alliance_broken",
            tag="TEU",
            other_tag="LIV",
            summary="断盟",
        ),
        DiffEvent(
            kind="subject_changed",
            tag="TEU",
            summary="收附",
            detail={"gained": ["LIV"], "lost": []},
        ),
        DiffEvent(
            kind="alliance_formed",
            tag="TEU",
            other_tag="BOH",
            summary="结盟",
        ),
    ]
    # 模拟 pipeline：先合并再可读化
    merged = consolidate_subject_alliance(events, player="TEU")
    diff = names.rewrite_diff(_teu_diff(*merged))
    ae = assess_player_ae(diff, country_label=names.country)
    md = _mock_editor(diff, names, ae)
    narrative = _mock_narrative_paragraph(diff, names, ae)

    assert "收附" in md and "利沃尼亚" in md
    assert "盟约撕裂" not in md
    assert "与 利沃尼亚骑士团 的盟约撕裂" not in md
    assert "利沃尼亚骑士团" in md
    assert "波希米亚" in md
    assert "收附" in narrative
    # 合并后不应再出现针对利沃尼亚的断盟措辞
    assert not any(
        e.kind == "alliance_broken" and {e.tag, e.other_tag} == {"TEU", "LIV"}
        for e in diff.events
    )


def test_high_warscore_not_undecided():
    names = NameResolver()
    diff = names.rewrite_diff(
        _teu_diff(
            DiffEvent(
                kind="war_started",
                tag="TEU",
                summary="war",
                detail={
                    "name": "Teutonic Conquest of Naklo",
                    "attackers": ["TEU"],
                    "defenders": ["POL"],
                    "participants": ["TEU", "POL"],
                    "scores": {"TEU": 68.0, "POL": -68.0},
                    "player_warscore": 68.0,
                },
            ),
            DiffEvent(
                kind="manpower_changed",
                tag="TEU",
                summary="人力",
                detail={"from": 15.2, "to": 8.5, "max_from": 20.0, "max_to": 20.0},
            ),
            DiffEvent(
                kind="navy_changed",
                tag="TEU",
                summary="海军",
                detail={"from": 26.0, "to": 28.0},
            ),
        )
    )
    ae = assess_player_ae(diff, country_label=names.country)
    wars = assess_player_wars(diff)
    assert wars.primary is not None
    assert wars.primary.tier == "decisive"
    assert wars.primary.player_score == 68

    md = _mock_editor(diff, names, ae)
    war = _mock_war_section(diff, names, ae, heading=False)
    narrative = _mock_narrative_paragraph(diff, names, ae)

    assert "68" in md
    assert "优势在握" in md or "基本打赢" in md
    assert "胜负未定" not in md
    assert "尘埃未定" not in md
    assert "胜负尚在尘埃未定" not in narrative
    assert "15.2" in narrative and "8.5" in narrative
    assert "26" in narrative and "28" in narrative
    assert "粮草" not in war
    assert "分数打实" not in war
    assert "补给" not in war
    # 叙事已写「玩家总战分 +68」时，tier 不再括号重复战分
    assert "玩家总战分 +68，优势在握，基本打赢" in narrative
    assert "基本打赢（战分 +68）" not in narrative
    assert "下一页按战分" not in md
    assert "按战分与编制事实推进" not in md


def test_mock_ticking_dedup_and_no_next_page_fluff():
    """叙事/要点各至多一句 ticking；成稿不含「下一页按战分」类套话。"""
    names = NameResolver()
    diff = names.rewrite_diff(
        _teu_diff(
            DiffEvent(
                kind="war_started",
                tag="TEU",
                summary="war",
                detail={
                    "name": "Teutonic Conquest of Naklo",
                    "name_zh": "条顿骑士团征服纳克沃",
                    "attackers": ["TEU"],
                    "defenders": ["POL"],
                    "participants": ["TEU", "POL"],
                    "player_warscore": 64.0,
                    "player_ticking_warscore": 16.8,
                    "scores": {"TEU": 64.0},
                    "war_goal_type": "take_claim",
                    "war_goal_province": 2963,
                },
            ),
            DiffEvent(
                kind="manpower_changed",
                tag="TEU",
                summary="人力",
                detail={"from": 15.2, "to": 8.5, "max_from": 20.0, "max_to": 20.0},
            ),
        )
    )
    ae = assess_player_ae(diff, country_label=names.country)
    md = _mock_editor(diff, names, ae)
    narrative = _mock_narrative_paragraph(diff, names, ae)
    war = _mock_war_section(diff, names, ae, heading=False)

    assert narrative.count("战争目标加分") == 1
    assert war.count("战争目标加分") == 1
    assert "战争目标加分 +17" in narrative
    assert "战争目标加分 +17" in war
    assert "约 -25～+25" not in narrative
    assert "约 -25～+25" not in war
    assert "（约-25～+25）" not in war
    assert "-25～+25" not in war
    assert "不作胶着依据" not in md
    assert "非总战分" not in md
    assert "目标 ticking" not in md
    assert "玩家总战分 +64，优势在握，基本打赢" in narrative
    assert "基本打赢（战分 +64）" not in narrative
    assert "下一页按战分" not in md
    assert "按战分与编制事实推进" not in md
    assert "下一页仍以 Diff 为准" not in md
    assert "下一页看附庸" not in md
    assert not contains_banned_empty_phrase(md), md
    # 全稿：叙事一次 + 要点一次（标题/结尾不应再写）
    sections = md.split("## ")
    narrative_block = next(s for s in sections if s.startswith("叙事"))
    war_block = next(s for s in sections if s.startswith("战局要点"))
    assert narrative_block.count("战争目标加分") == 1
    assert war_block.count("战争目标加分") == 1
    # 结尾段不得含战争目标加分或下一页套话
    ending = md.split("---")[-1]
    assert "战争目标加分" not in ending
    assert "ticking" not in ending.lower()
    assert "下一页" not in ending
    assert "-25～+25" not in md
    assert "约 -25～+25" not in HISTORIAN_SYSTEM
    assert "约 -25～+25" not in EDITOR_SYSTEM
    assert "战争目标加分 ±N" in HISTORIAN_SYSTEM
    assert "战争目标加分 ±N" in EDITOR_SYSTEM


def test_mock_has_no_banned_empty_phrases():
    names = NameResolver()
    diff = names.rewrite_diff(
        _teu_diff(
            DiffEvent(
                kind="war_started",
                tag="TEU",
                summary="war",
                detail={
                    "name": "Teutonic Conquest of Naklo",
                    "name_zh": "条顿骑士团征服纳克沃",
                    "attackers": ["TEU"],
                    "defenders": ["POL"],
                    "participants": ["TEU", "POL"],
                    "player_warscore": 68.0,
                    "scores": {"TEU": 68.0},
                },
            ),
            DiffEvent(
                kind="subject_changed",
                tag="TEU",
                summary="收附 LIV",
                detail={"gained": ["LIV"], "lost": [], "supersedes_alliance_break": ["LIV"]},
            ),
            DiffEvent(
                kind="alliance_formed",
                tag="TEU",
                other_tag="BOH",
                summary="结盟",
            ),
            DiffEvent(
                kind="manpower_changed",
                tag="TEU",
                summary="人力",
                detail={"from": 15.2, "to": 8.5, "max_from": 20.0, "max_to": 20.0},
            ),
        )
    )
    ae = assess_player_ae(diff, country_label=names.country)
    md = _mock_editor(diff, names, ae)
    assert not contains_banned_empty_phrase(md), md
    for phrase in BANNED_EMPTY_PHRASES:
        assert phrase not in md
    # 调试旁注不得进成稿
    assert "勿编造恐吓" not in md
    assert "档内无 AE" not in md


def test_diff_war_started_includes_player_warscore():
    prev = GameState(
        date="1447.1.1",
        player="TEU",
        countries={"TEU": CountryState(tag="TEU", name="Teutonic Order", allies=["LIV"])},
        wars=[],
    )
    curr = GameState(
        date="1454.1.1",
        player="TEU",
        countries={
            "TEU": CountryState(
                tag="TEU",
                name="Teutonic Order",
                allies=["BOH"],
                subjects=["LIV"],
                manpower=8.5,
                max_manpower=20,
                navy_size=28,
            ),
            "LIV": CountryState(tag="LIV", name="Livonian Order"),
            "BOH": CountryState(tag="BOH", name="Bohemia"),
            "POL": CountryState(tag="POL", name="Poland"),
        },
        wars=[
            WarState(
                name="Teutonic Conquest of Naklo",
                attackers=["TEU"],
                defenders=["POL"],
                participants=[
                    WarParticipant(tag="TEU", side="attackers", warscore=68),
                    WarParticipant(tag="POL", side="defenders", warscore=-68),
                ],
            )
        ],
    )
    raw = diff_states(prev, curr)
    filtered = filter_diff(raw, prev=prev, curr=curr)
    war_ev = next(e for e in filtered.events if e.kind == "war_started")
    assert war_ev.detail.get("player_warscore") == 68
    assert "alliance_broken" not in {e.kind for e in filtered.events}
    assert any(
        e.kind == "subject_changed" and "LIV" in (e.detail.get("gained") or [])
        for e in filtered.events
    )

    names = NameResolver.from_states(prev, curr)
    readable = names.rewrite_diff(filtered)
    ae = assess_player_ae(readable, country_label=names.country)
    md = _mock_editor(readable, names, ae)
    assert "优势在握" in md or "基本打赢" in md
    assert "收附" in md and "利沃尼亚" in md
    assert not contains_banned_empty_phrase(md)
    assert "盟约撕裂" not in md
