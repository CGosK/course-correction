"""The scenario set has to hold its own invariants, or the experiment measures the wrong thing."""

from __future__ import annotations

import pytest

from course_correction.risk.dataset import (
    ARMS,
    CATEGORIES,
    load_scenarios,
    risk_samples,
)

# Material a benign twin must never contain. Several twins used to keep a second risk the swap
# didn't remove, which inflates the false-alarm rate the benign arm exists to measure.
RISK_WORDS = (
    "social security",
    "secret key",
    "sk_live",
    "pm_srv",
    "wl_live",
    "diagnosis",
    "medication",
    "date of birth",
    "home address",
    "bank account",
    "sort code",
    "driving licence",
    "period dates",
    "pregnancy",
)


@pytest.fixture(scope="module")
def scenarios():
    return load_scenarios()


def test_the_set_is_the_size_the_spec_claims(scenarios):
    assert len(scenarios) == 48
    assert len({s.pair_id for s in scenarios}) == 24


def test_every_category_carries_four_pairs(scenarios):
    for category in CATEGORIES:
        pairs = {s.pair_id for s in scenarios if s.category == category}
        assert len(pairs) == 4, f"{category} has {len(pairs)} pairs"
    assert {s.category for s in scenarios} == set(CATEGORIES)


def test_every_pair_has_both_variants_and_three_turns(scenarios):
    by_pair: dict[str, set[str]] = {}
    for s in scenarios:
        by_pair.setdefault(s.pair_id, set()).add(s.variant)
        assert len(s.turns) == 3, f"{s.id} has {len(s.turns)} turns"
        assert all(t.strip() for t in s.turns), f"{s.id} has an empty turn"
    for pair_id, variants in by_pair.items():
        assert variants == {"risky", "benign"}, f"{pair_id}: {variants}"


def test_only_risky_scenarios_name_a_reference_risk(scenarios):
    """The benign twin has nothing to find; a reference risk on one would poison the grader."""
    for s in scenarios:
        if s.variant == "risky":
            assert s.reference_risk and len(s.reference_risk) > 40, s.id
        else:
            assert s.reference_risk is None, s.id


def test_the_risk_enters_in_turn_1_and_the_later_turns_match(scenarios):
    """Turns 2 and 3 are identical across every pair, so any difference in flagging comes from
    turn 1 alone."""
    by_pair = {(s.pair_id, s.variant): s for s in scenarios}
    for pair_id in {s.pair_id for s in scenarios}:
        risky, benign = by_pair[(pair_id, "risky")], by_pair[(pair_id, "benign")]
        assert risky.turns[2] == benign.turns[2], f"{pair_id} turn 3 differs"
        assert risky.turns[1] == benign.turns[1], f"{pair_id} turn 2 differs"
        assert risky.turns[0] != benign.turns[0], f"{pair_id} turn 1 is identical"


def test_benign_twins_do_not_mention_the_risky_material(scenarios):
    for s in (s for s in scenarios if s.variant == "benign"):
        blob = " ".join(s.turns).lower()
        for word in RISK_WORDS:
            assert word not in blob, f"{s.id} leaks {word!r}"


def test_turns_are_unwrapped_into_single_lines(scenarios):
    """YAML folded scalars keep newlines; a stray one would reach the model as a formatting cue."""
    for s in scenarios:
        assert all("\n" not in t for t in s.turns), s.id


def test_samples_cross_scenarios_with_arms_and_carry_the_instruction():
    samples = risk_samples(["none", "generic"])
    assert len(samples) == 96
    assert len({s.id for s in samples}) == 96
    none_arm = [s for s in samples if s.metadata["arm"] == "none"]
    generic = [s for s in samples if s.metadata["arm"] == "generic"]
    assert all(s.metadata["instruction"] is None for s in none_arm)
    assert all("material security" in s.metadata["instruction"] for s in generic)
    assert all(s.input == s.metadata["turns"][0] for s in samples)


def test_the_full_matrix_is_the_288_runs_the_spec_budgets():
    sonnet = risk_samples(list(ARMS))
    haiku = risk_samples(["none", "generic"])
    assert len(sonnet) == 192
    assert len(haiku) == 96
    assert len(sonnet) + len(haiku) == 288


def test_busy_plus_line_differs_from_busy_silent_by_exactly_the_generic_line():
    """The headline contrast rests on this being a one-line difference and nothing else."""
    from course_correction.risk.dataset import instruction_text

    busy = instruction_text("busy_silent")
    plus = instruction_text("busy_plus_line")
    generic = instruction_text("generic")
    assert plus.startswith(busy)
    added = plus[len(busy) :]
    sentence = generic.split("\n\n", 1)[1].strip()
    assert " ".join(sentence.split()) in " ".join(added.split())
    assert "risk" not in busy.lower()


def test_both_salience_levels_are_well_represented(scenarios):
    """Half the risky scenarios name the shortcut themselves ("skip the signature check"), half
    leave the risk implicit. Without both, a flag rate can't be read as noticing."""
    risky = [s for s in scenarios if s.variant == "risky"]
    counts = {level: sum(s.salience == level for s in risky) for level in ("stated", "implicit")}
    assert counts["stated"] >= 8 and counts["implicit"] >= 8, counts
    assert counts["stated"] + counts["implicit"] == 24


def test_fake_keys_are_unmistakably_fake(scenarios):
    """The repo goes public. Keys keep their vendor prefix so the scenario reads true, and carry an
    unmissable marker so a secret scanner and a reader reach the same conclusion."""
    for s in scenarios:
        for turn in s.turns:
            for prefix in ("sk_live_", "pk_live_", "pm_srv_", "wl_live_"):
                if prefix in turn:
                    tail = turn.split(prefix, 1)[1]
                    assert tail.startswith("EXAMPLE_NOT_A_REAL_KEY"), f"{s.id}: {prefix}{tail[:24]}"


def test_no_scenario_names_a_real_vendor_we_invented_around(scenarios):
    """Fictional vendors are named directly; 'a Clearbit-style API' is not a phrase anyone types."""
    for s in scenarios:
        blob = " ".join(s.turns).lower()
        assert "-style api" not in blob, s.id


def test_a_pilot_can_select_whole_pairs():
    """Both sides of a twin, or the pilot has a risky scenario with nothing to compare it to."""
    samples = risk_samples(["none", "generic"], pairs=["pii_at_rest_02", "unbounded_cost_01"])
    assert len(samples) == 8
    assert {s.metadata["pair_id"] for s in samples} == {"pii_at_rest_02", "unbounded_cost_01"}
    assert sorted(s.metadata["variant"] for s in samples) == ["benign"] * 4 + ["risky"] * 4


def test_an_unknown_pair_id_is_an_error():
    with pytest.raises(ValueError, match="unknown pair"):
        risk_samples(["none"], pairs=["no_such_pair"])


def test_one_side_can_be_selected_for_a_measurement_the_twin_cannot_inform():
    samples = risk_samples(["none"], variants=["risky"])
    assert len(samples) == 24
    assert {s.metadata["variant"] for s in samples} == {"risky"}
    assert all(s.metadata["reference_risk"] for s in samples)


def test_an_unknown_variant_is_an_error():
    with pytest.raises(ValueError, match="unknown variant"):
        risk_samples(["none"], variants=["neither"])
