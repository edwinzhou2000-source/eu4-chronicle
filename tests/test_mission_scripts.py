"""任务脚本：完成 effect 中的 country_event 索引与单选项连锁。"""

from __future__ import annotations

from eu4_chronicle.localisation import GameLocalisation
from eu4_chronicle.mission_scripts import (
    build_mission_script_index,
    index_events_file,
    index_missions_file,
)


SAMPLE_MISSION = """
teu_seek_imperial_protection = {
	icon = mission_alliances
	position = 1
	required_missions = { }
	trigger = { always = yes }
	effect = {
		if = {
			limit = { hre_size = 1 }
			country_event = { id = flavor_teu.17 }
		}
		else = {
			add_dip_power = 100
		}
	}
}
"""

SAMPLE_EVENT = """
country_event = {
	id = flavor_teu.17
	title = flavor_teu.EVTNAME17
	desc = flavor_teu.EVTDESC17
	option = {
		name = flavor_teu.17.a
		add_prestige = 10
	}
	option = {
		name = flavor_teu.17.b
		add_dip_power = 50
	}
}
"""

CHAIN_MISSION = """
teu_bound_of_the_orders = {
	icon = mission_alliances
	position = 2
	required_missions = { }
	trigger = { always = yes }
	effect = {
		country_event = { id = flavor_teu.100 }
	}
}
"""

CHAIN_EVENTS = """
country_event = {
	id = flavor_teu.100
	title = flavor_teu.EVTNAME100
	desc = flavor_teu.EVTDESC100
	option = {
		name = flavor_teu.100.a
		country_event = { id = flavor_teu.101 }
	}
}
country_event = {
	id = flavor_teu.101
	title = flavor_teu.EVTNAME101
	desc = flavor_teu.EVTDESC101
	option = {
		name = flavor_teu.101.a
		add_prestige = 5
	}
}
"""

CYCLE_EVENTS = """
country_event = {
	id = flavor_teu.200
	title = flavor_teu.EVTNAME200
	desc = flavor_teu.EVTDESC200
	option = {
		name = flavor_teu.200.a
		country_event = { id = flavor_teu.201 }
	}
}
country_event = {
	id = flavor_teu.201
	title = flavor_teu.EVTNAME201
	desc = flavor_teu.EVTDESC201
	option = {
		name = flavor_teu.201.a
		country_event = { id = flavor_teu.200 }
	}
}
"""

CYCLE_MISSION = """
teu_cycle_test = {
	icon = mission_alliances
	position = 1
	required_missions = { }
	trigger = { always = yes }
	effect = {
		country_event = { id = flavor_teu.200 }
	}
}
"""


def test_index_mission_effect_events():
    mapped = index_missions_file(SAMPLE_MISSION)
    assert mapped["teu_seek_imperial_protection"] == ["flavor_teu.17"]


def test_index_event_keys_and_reward_text(tmp_path):
    game = tmp_path / "game"
    (game / "missions").mkdir(parents=True)
    (game / "events").mkdir(parents=True)
    (game / "missions" / "teu.txt").write_text(SAMPLE_MISSION, encoding="utf-8")
    (game / "events" / "flavor.txt").write_text(SAMPLE_EVENT, encoding="utf-8")
    keys = index_events_file(SAMPLE_EVENT)
    assert keys["flavor_teu.17"]["title_key"] == "flavor_teu.EVTNAME17"
    assert keys["flavor_teu.17"]["option_keys"] == ["flavor_teu.17.a", "flavor_teu.17.b"]
    assert keys["flavor_teu.17"]["option_followups"] == [[], []]

    idx = build_mission_script_index([game])
    loc = GameLocalisation(
        entries={
            "flavor_teu.EVTNAME17": "Join the Empire",
            "flavor_teu.EVTDESC17": "The Emperor offers protection.",
            "flavor_teu.17.a": "Accept",
            "flavor_teu.17.b": "Refuse",
        }
    )
    rewards = idx.reward_events_for("teu_seek_imperial_protection", loc)
    assert len(rewards) == 1
    assert rewards[0].title == "Join the Empire"
    assert "Emperor" in rewards[0].desc
    assert rewards[0].options == ["Accept", "Refuse"]
    assert rewards[0].choice_known is False
    assert rewards[0].chain_deterministic is False


def test_single_option_chains_to_followup(tmp_path):
    game = tmp_path / "game"
    (game / "missions").mkdir(parents=True)
    (game / "events").mkdir(parents=True)
    (game / "missions" / "teu.txt").write_text(CHAIN_MISSION, encoding="utf-8")
    (game / "events" / "flavor.txt").write_text(CHAIN_EVENTS, encoding="utf-8")
    keys = index_events_file(CHAIN_EVENTS)
    assert keys["flavor_teu.100"]["option_keys"] == ["flavor_teu.100.a"]
    assert keys["flavor_teu.100"]["option_followups"] == [["flavor_teu.101"]]

    idx = build_mission_script_index([game])
    loc = GameLocalisation(
        entries={
            "flavor_teu.EVTNAME100": "Unification of the Orders?",
            "flavor_teu.EVTDESC100": "Shall the orders unite?",
            "flavor_teu.100.a": "Continue",
            "flavor_teu.EVTNAME101": "Bound Confirmed",
            "flavor_teu.EVTDESC101": "The bond is sealed.",
            "flavor_teu.101.a": "Excellent",
        }
    )
    rewards = idx.reward_events_for("teu_bound_of_the_orders", loc)
    assert [r.event_id for r in rewards] == ["flavor_teu.100", "flavor_teu.101"]
    assert rewards[0].depth == 0 and rewards[1].depth == 1
    assert rewards[0].chain_deterministic is True
    assert rewards[1].title == "Bound Confirmed"


def test_multi_option_does_not_expand(tmp_path):
    game = tmp_path / "game"
    (game / "missions").mkdir(parents=True)
    (game / "events").mkdir(parents=True)
    (game / "missions" / "teu.txt").write_text(SAMPLE_MISSION, encoding="utf-8")
    multi_with_followup = """
country_event = {
	id = flavor_teu.17
	title = flavor_teu.EVTNAME17
	desc = flavor_teu.EVTDESC17
	option = {
		name = flavor_teu.17.a
		country_event = { id = flavor_teu.99 }
	}
	option = {
		name = flavor_teu.17.b
		add_dip_power = 50
	}
}
country_event = {
	id = flavor_teu.99
	title = flavor_teu.EVTNAME99
	desc = flavor_teu.EVTDESC99
	option = { name = flavor_teu.99.a }
}
"""
    (game / "events" / "flavor.txt").write_text(multi_with_followup, encoding="utf-8")
    idx = build_mission_script_index([game])
    loc = GameLocalisation(
        entries={
            "flavor_teu.EVTNAME17": "Join the Empire",
            "flavor_teu.EVTDESC17": "Choose.",
            "flavor_teu.17.a": "Accept",
            "flavor_teu.17.b": "Refuse",
            "flavor_teu.EVTNAME99": "Should not appear",
            "flavor_teu.EVTDESC99": "Hidden.",
        }
    )
    rewards = idx.reward_events_for("teu_seek_imperial_protection", loc)
    assert [r.event_id for r in rewards] == ["flavor_teu.17"]


def test_comment_title_fallback_when_no_loc(tmp_path):
    mission = """
teu_end_crazy = {
	icon = mission_alliances
	position = 1
	required_missions = { }
	trigger = { always = yes }
	effect = {
		country_event = { id = DD_NED.17 }
	}
}
"""
    events = """
#17 癫狂之终
country_event = {
	id = DD_NED.17
	title = DD_NED_17_t
	desc = DD_NED_17_d
	option = {
		name = DD_NED_17a
		country_event = { id = DD_NED.18 }
	}
}
#18 共和同盟的遗产
country_event = {
	id = DD_NED.18
	title = DD_NED_18_t
	desc = DD_NED_18_d
	option = {
		name = DD_NED_18a
		add_prestige = 5
	}
}
"""
    game = tmp_path / "game"
    (game / "missions").mkdir(parents=True)
    (game / "events").mkdir(parents=True)
    (game / "missions" / "teu.txt").write_text(mission, encoding="utf-8")
    (game / "events" / "flavor.txt").write_text(events, encoding="utf-8")
    keys = index_events_file(events)
    assert keys["DD_NED.17"]["comment_title"] == "癫狂之终"
    assert keys["DD_NED.18"]["comment_title"] == "共和同盟的遗产"

    idx = build_mission_script_index([game])
    loc = GameLocalisation(entries={})  # 无私有字形 loc
    rewards = idx.reward_events_for("teu_end_crazy", loc)
    assert [r.title for r in rewards] == ["癫狂之终", "共和同盟的遗产"]
    assert rewards[0].title_source == "script_comment"
    assert rewards[0].depth == 0
    assert rewards[1].depth == 1


def test_loc_title_wins_over_comment(tmp_path):
    mission = """
teu_x = {
	icon = mission_alliances
	position = 1
	required_missions = { }
	trigger = { always = yes }
	effect = { country_event = { id = flavor_teu.17 } }
}
"""
    events = """
#17 注释标题
country_event = {
	id = flavor_teu.17
	title = flavor_teu.EVTNAME17
	desc = flavor_teu.EVTDESC17
	option = { name = flavor_teu.17.a }
}
"""
    game = tmp_path / "game"
    (game / "missions").mkdir(parents=True)
    (game / "events").mkdir(parents=True)
    (game / "missions" / "teu.txt").write_text(mission, encoding="utf-8")
    (game / "events" / "flavor.txt").write_text(events, encoding="utf-8")
    idx = build_mission_script_index([game])
    loc = GameLocalisation(
        entries={
            "flavor_teu.EVTNAME17": "Join the Empire",
            "flavor_teu.EVTDESC17": "The Emperor offers protection.",
        }
    )
    rewards = idx.reward_events_for("teu_x", loc)
    assert len(rewards) == 1
    assert rewards[0].title == "Join the Empire"
    assert rewards[0].title_source == "loc"


def test_cycle_chain_truncates(tmp_path):
    game = tmp_path / "game"
    (game / "missions").mkdir(parents=True)
    (game / "events").mkdir(parents=True)
    (game / "missions" / "teu.txt").write_text(CYCLE_MISSION, encoding="utf-8")
    (game / "events" / "flavor.txt").write_text(CYCLE_EVENTS, encoding="utf-8")
    idx = build_mission_script_index([game])
    loc = GameLocalisation(
        entries={
            "flavor_teu.EVTNAME200": "A",
            "flavor_teu.EVTDESC200": "a",
            "flavor_teu.200.a": "go",
            "flavor_teu.EVTNAME201": "B",
            "flavor_teu.EVTDESC201": "b",
            "flavor_teu.201.a": "back",
        }
    )
    rewards = idx.reward_events_for("teu_cycle_test", loc)
    ids = [r.event_id for r in rewards]
    assert ids == ["flavor_teu.200", "flavor_teu.201"]
    assert len(ids) == len(set(ids))
