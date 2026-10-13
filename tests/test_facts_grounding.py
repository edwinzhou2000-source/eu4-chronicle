"""事实锚定：附庸+断盟合并、高战分措辞、反空话禁词。"""

from __future__ import annotations

from eu4_chronicle.ae import assess_player_ae
from eu4_chronicle.agents import (
    _mock_editor,
    _mock_ending,
    _mock_narrative_paragraph,
    _mock_war_section,
)
from eu4_chronicle.agents.prompts import EDITOR_SYSTEM, HISTORIAN_SYSTEM
from eu4_chronicle.diff import diff_states
from eu4_chronicle.filter import (
    consolidate_subject_alliance,
    drop_lonely_alliance_breaks,
    filter_diff,
)
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


def test_banned_forward_looking_hold_gains_phrases():
    """「守住战果 / 接下来便是」类前瞻空话须命中禁词表。"""
    assert contains_banned_empty_phrase("四城既入，接下来便是守住这份战果。")
    assert contains_banned_empty_phrase("宜巩固战果")
    assert contains_banned_empty_phrase("据 Diff 巩固版图与附庸即可")
    assert "守住战果" in BANNED_EMPTY_PHRASES
    assert "接下来便是" in BANNED_EMPTY_PHRASES
    assert "守住（这份）战果" in HISTORIAN_SYSTEM
    assert "前瞻空话" in EDITOR_SYSTEM


def test_banned_manpower_literary_fluff_phrases():
    """人力等内政文言废话须命中禁词，提示要求数字体。"""
    assert contains_banned_empty_phrase(
        "可征之丁实有增益，惟现存之兵尚待休养。"
    )
    assert contains_banned_empty_phrase("宜休养生息")
    assert contains_banned_empty_phrase("兵甲稍充而元气未复")
    assert "可征之丁" in BANNED_EMPTY_PHRASES
    assert "尚待休养" in BANNED_EMPTY_PHRASES
    assert "丁口" in BANNED_EMPTY_PHRASES
    assert "内政数字体" in HISTORIAN_SYSTEM
    assert "可征之丁" in HISTORIAN_SYSTEM
    assert "内政数字体" in EDITOR_SYSTEM
    assert "可征之丁" in EDITOR_SYSTEM


def test_mock_ending_all_wars_ended_no_hold_gains_fluff():
    """全结束战争收束只点事实，不含巩固/守住套话。"""
    diff = _teu_diff(
        DiffEvent(
            kind="war_ended",
            tag="TEU",
            summary="终战",
            detail={
                "name": "Teutonic Conquest of Naklo",
                "attackers": ["TEU"],
                "defenders": ["POL"],
                "participants": ["TEU", "POL"],
                "outcome": 2,
                "player_won": True,
                "player_warscore": 45.0,
            },
        )
    )
    names = NameResolver()
    ae = assess_player_ae(diff, country_label=names.country)
    ending = _mock_ending(diff, names, ae)
    assert "落幕" in ending or "本页" in ending
    assert "战分" not in ending
    assert "+45" not in ending
    assert "巩固" not in ending
    assert "守住" not in ending
    assert "据 Diff" not in ending
    assert not contains_banned_empty_phrase(ending)


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


def test_lonely_alliance_break_dropped_from_report():
    """纯断盟 + 战争/得地、无其它外交戏 → 战报不写断盟。"""
    events = [
        DiffEvent(
            kind="alliance_broken",
            tag="NE8",
            other_tag="WES",
            summary="NE8 与 WES 同盟破裂",
        ),
        DiffEvent(
            kind="province_gained",
            tag="NE8",
            summary="得地",
            detail={"provinces": [54]},
        ),
        DiffEvent(
            kind="war_ended",
            tag="NE8",
            summary="终战",
            detail={
                "name": "war",
                "attackers": ["NE8"],
                "defenders": ["GOT"],
                "participants": ["NE8", "GOT"],
            },
        ),
    ]
    pruned = drop_lonely_alliance_breaks(events, player="NE8")
    assert not any(e.kind == "alliance_broken" for e in pruned)
    assert any(e.kind == "province_gained" for e in pruned)

    # 有新盟则保留断盟
    with_form = events + [
        DiffEvent(
            kind="alliance_formed",
            tag="NE8",
            other_tag="FRA",
            summary="结盟",
        )
    ]
    kept = drop_lonely_alliance_breaks(with_form, player="NE8")
    assert any(e.kind == "alliance_broken" for e in kept)

    diff = DiffResult(
        player="NE8",
        prev_date="1457.4.3",
        curr_date="1460.6.10",
        events=events,
    )
    filtered = filter_diff(diff, include_global=False)
    assert not any(e.kind == "alliance_broken" for e in filtered.events)


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
    # 收附仅写外交段，叙事不双写
    assert "收附" not in narrative
    diplo_block = next(s for s in md.split("## ") if s.startswith("外交"))
    assert "收附" in diplo_block and "利沃尼亚" in diplo_block
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
    # 战分/tier 仅战局；叙事只写指针
    assert "详见战局" in narrative
    assert "玩家总战分" not in narrative
    assert "玩家总战分 +68" in war
    assert "优势在握" in war or "基本打赢" in war
    assert "基本打赢（战分 +68）" not in war
    assert "下一页按战分" not in md
    assert "按战分与编制事实推进" not in md


def test_mock_ticking_dedup_and_no_next_page_fluff():
    """战争目标加分全文仅战局一次；成稿不含「下一页按战分」类套话。"""
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

    assert narrative.count("战争目标加分") == 0
    assert war.count("战争目标加分") == 1
    assert "战争目标加分 +17" in war
    assert "约 -25～+25" not in narrative
    assert "约 -25～+25" not in war
    assert "（约-25～+25）" not in war
    assert "-25～+25" not in war
    assert "不作胶着依据" not in md
    assert "非总战分" not in md
    assert "目标 ticking" not in md
    assert "详见战局" in narrative
    assert "玩家总战分" not in narrative
    assert "玩家总战分 +64" in war
    assert "优势在握" in war or "基本打赢" in war
    assert "基本打赢（战分 +64）" not in war
    assert "下一页按战分" not in md
    assert "按战分与编制事实推进" not in md
    assert "下一页仍以 Diff 为准" not in md
    assert "下一页看附庸" not in md
    assert not contains_banned_empty_phrase(md), md
    sections = md.split("## ")
    narrative_block = next(s for s in sections if s.startswith("叙事"))
    war_block = next(s for s in sections if s.startswith("战局要点"))
    assert narrative_block.count("战争目标加分") == 0
    assert war_block.count("战争目标加分") == 1
    assert md.count("战争目标加分") == 1
    ending = md.split("---")[-1]
    assert "战争目标加分" not in ending
    assert "ticking" not in ending.lower()
    assert "下一页" not in ending
    assert "+64" not in ending
    assert "-25～+25" not in md
    assert "约 -25～+25" not in HISTORIAN_SYSTEM
    assert "约 -25～+25" not in EDITOR_SYSTEM
    assert "战争目标加分" in EDITOR_SYSTEM
    assert "未及全功" in EDITOR_SYSTEM
    assert "已结束" in EDITOR_SYSTEM


def test_section_ownership_no_cross_repeat_ae_or_vassal():
    """AE 引导与收附不跨叙事/战局重复。"""
    from eu4_chronicle.agents import _mock_diplo_section
    from eu4_chronicle.models import CountryRelation, CountryState, GameState

    names = NameResolver()
    diff = names.rewrite_diff(
        _teu_diff(
            DiffEvent(
                kind="subject_changed",
                tag="TEU",
                summary="收附",
                detail={"gained": ["LIV"], "lost": []},
            ),
            DiffEvent(
                kind="war_started",
                tag="TEU",
                summary="war",
                detail={
                    "name": "Teutonic Conquest of Naklo",
                    "attackers": ["TEU"],
                    "defenders": ["POL"],
                    "participants": ["TEU", "POL"],
                    "player_warscore": 55.0,
                    "scores": {"TEU": 55.0},
                },
            ),
        )
    )
    curr = GameState(
        date="1454.1.1",
        player="TEU",
        countries={
            "TEU": CountryState(tag="TEU", owned_provinces=[1]),
            "HSA": CountryState(
                tag="HSA",
                owned_provinces=[45],
                relations={
                    "TEU": CountryRelation(
                        tag="TEU",
                        ae=70,
                        opinion=-30,
                        truce=True,
                        attitude="attitude_outraged",
                    )
                },
            ),
        },
    )
    ae = assess_player_ae(diff, country_label=names.country, curr=curr)
    md = _mock_editor(diff, names, ae)
    narrative = _mock_narrative_paragraph(diff, names, ae)
    war = _mock_war_section(diff, names, ae, heading=False)
    diplo = _mock_diplo_section(diff, names, ae, heading=False)

    assert "收附" not in narrative
    assert "收附" not in war
    assert "收附" in diplo
    assert "停战未能入网" in diplo or "AE" in diplo
    assert "停战未能入网" not in narrative
    assert "停战未能入网" not in war
    assert "忌另开第二战场" not in war
    assert "当前 AE 偏高" not in war
    assert md.count("收附") >= 1
    # 标题可钩收附；正文外交写一次即可（标题+外交）
    body = md.split("\n", 1)[-1]
    assert body.count("收附") == 1


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
