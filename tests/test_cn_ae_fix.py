"""中文国名 / 战争名 / AE 文案规则。"""

from __future__ import annotations

from eu4_chronicle.ae import (
    MECHANISM_FLUFF_PHRASES,
    ae_guidance_lines,
    assess_player_ae,
    contains_ae_scare,
    contains_mechanism_fluff,
)
from eu4_chronicle.agents import _mock_diplo_section, _mock_editor, _mock_war_section
from eu4_chronicle.agents import prompts as role_prompts
from eu4_chronicle.models import DiffEvent, DiffResult
from eu4_chronicle.names import NameResolver
from eu4_chronicle.names.wars import translate_war_name


def test_liv_and_baltic_tags_chinese():
    names = NameResolver()
    assert names.country("LIV") == "利沃尼亚骑士团"
    assert names.country("TEU") == "条顿骑士团"
    assert names.country("POL") == "波兰"
    assert names.country("LIT") == "立陶宛"
    assert names.country("HUN") == "匈牙利"
    assert names.country("CRO") == "克罗地亚"
    assert names.country("BOH") == "波希米亚"
    assert names.country("SIL") == "西里西亚"
    assert names.country("MAZ") == "马佐夫舍"
    assert names.country("MOL") == "摩尔达维亚"
    assert names.country("PRU") == "普鲁士"


def test_war_name_teutonic_conquest_of_naklo():
    zh = translate_war_name("Teutonic Conquest of Naklo", attackers=["TEU"], defenders=["POL"])
    assert "Teutonic" not in zh
    assert "Naklo" not in zh
    assert "条顿" in zh
    assert "纳克沃" in zh or "征服" in zh


def test_war_name_byzantine_reconquest_rewritten_in_event():
    names = NameResolver()
    ev = DiffEvent(
        kind="war_started",
        tag="BYZ",
        summary="war",
        detail={
            "name": "Byzantine Reconquest of Hüdavendigar",
            "attackers": ["BYZ"],
            "defenders": ["TUR"],
            "participants": ["BYZ", "TUR"],
        },
    )
    out = names.rewrite_event(ev)
    assert "Byzantine" not in out.summary
    assert "Hüdavendigar" not in out.summary
    assert "拜占庭" in out.summary
    assert "许达文迪加尔" in out.summary
    assert out.detail.get("name_zh")


def test_alliance_broken_uses_liv_chinese():
    names = NameResolver()
    ev = DiffEvent(
        kind="alliance_broken",
        tag="TEU",
        other_tag="LIV",
        summary="断盟",
    )
    out = names.rewrite_event(ev)
    assert "LIV" not in out.summary
    assert "利沃尼亚骑士团" in out.summary


def _teu_diff(*events: DiffEvent) -> DiffResult:
    return DiffResult(
        prev_date="1447.1.1",
        curr_date="1454.1.1",
        player="TEU",
        events=list(events),
    )


def test_ae_no_change_mock_has_no_scare_phrases():
    names = NameResolver()
    diff = _teu_diff(
        DiffEvent(
            kind="alliance_broken",
            tag="TEU",
            other_tag="LIV",
            summary="断盟",
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
            },
        ),
    )
    readable = names.rewrite_diff(diff)
    ae = assess_player_ae(readable, country_label=names.country)
    assert ae.level == "none"
    assert not ae.warn_coalition

    md = _mock_editor(readable, names, ae)
    diplo = _mock_diplo_section(readable, names, ae, heading=False)
    war = _mock_war_section(readable, names, ae, heading=False)

    assert "利沃尼亚骑士团" in md
    assert "LIV" not in md
    assert "Teutonic" not in md
    assert "当前未见高 AE" in diplo or "包围网风险低" in diplo
    assert not contains_ae_scare(md)
    assert not contains_ae_scare(war)
    assert not contains_mechanism_fluff(md)
    assert not contains_mechanism_fluff(diplo)
    # 平静期勿展开门槛教科书 / 宣战结算科普
    assert "机制：" not in diplo
    assert "宣战本身" not in diplo
    assert "苛刻和约" not in diplo


def test_ae_high_warns_coalition():
    names = NameResolver()
    diff = _teu_diff(
        DiffEvent(
            kind="ae_changed",
            tag="TEU",
            other_tag="POL",
            summary="ae",
            detail={"from": 20, "to": 62, "viewer": "POL", "target": "TEU"},
        )
    )
    ae = assess_player_ae(diff, country_label=names.country)
    assert ae.warn_coalition
    assert ae.level == "high"
    diplo = _mock_diplo_section(diff, names, ae, heading=False)
    assert "50" in diplo
    assert "包围网" in diplo
    assert ae.max_to >= 50
    # 高 AE 可点门槛，但勿用旧机制科普句式
    assert not contains_mechanism_fluff(diplo)


def test_ae_guidance_none_no_mechanism_fluff():
    ae = assess_player_ae(
        DiffResult(prev_date="a", curr_date="b", player="TEU", events=[]),
        country_label=lambda t: t,
    )
    lines = ae_guidance_lines(ae, player_label="条顿骑士团")
    blob = "".join(lines)
    assert "未见高 AE" in blob or "风险低" in blob
    assert "50" not in blob
    assert "机制" not in blob
    assert not contains_mechanism_fluff(blob)


def test_prompts_and_mock_forbid_mechanism_fluff():
    """提示词不得用肯定句教机制科普；mock 空外交成稿不得含禁句。"""
    prompt_blob = "\n".join(
        [
            role_prompts.HISTORIAN_SYSTEM,
            role_prompts.STRATEGIST_SYSTEM,
            role_prompts.DIPLOMAT_SYSTEM,
            role_prompts.EDITOR_SYSTEM,
        ]
    )
    # 用户成稿里出现过的禁句不得作为「要写的内容」留在提示词里
    affirmative_banned = (
        "宣战本身不等于结算 AE",
        "宣战本身不会立刻结算 AE",
        "并点明包围网一般需 AE>50",
        "（机制：包围网一般需",
    )
    for phrase in affirmative_banned:
        assert phrase not in prompt_blob, phrase

    names = NameResolver()
    diff = DiffResult(prev_date="a", curr_date="b", player="TEU", events=[])
    ae = assess_player_ae(diff, country_label=names.country)
    diplo = _mock_diplo_section(diff, names, ae, heading=False)
    for phrase in MECHANISM_FLUFF_PHRASES:
        assert phrase not in diplo, phrase
    assert "当前未见高 AE" in diplo or "包围网风险低" in diplo
