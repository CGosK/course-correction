"""The confirmatory set has to hold the design its pre-registration describes."""

from __future__ import annotations

from collections import Counter

import pytest

from course_correction.risk.dataset import durability_samples


@pytest.fixture(scope="module")
def samples():
    return durability_samples()


def test_the_set_is_balanced_on_the_variable_under_test(samples):
    assert len(samples) == 16
    assert Counter(s.metadata["harm_falls_on"] for s in samples) == {"owner": 8, "third_party": 8}


def test_every_mechanism_appears_once_on_each_side(samples):
    """Mechanism is held constant and who-gets-hurt varies. If a mechanism appeared only as
    owner-harm, severity would be free to explain the result instead."""
    by_mechanism: dict[str, set[str]] = {}
    for s in samples:
        by_mechanism.setdefault(s.metadata["mechanism"], set()).add(s.metadata["harm_falls_on"])
    assert len(by_mechanism) == 8
    for mechanism, sides in by_mechanism.items():
        assert sides == {"owner", "third_party"}, f"{mechanism}: {sides}"


def test_every_scenario_has_three_turns_and_a_reference_risk(samples):
    for s in samples:
        assert len(s.metadata["turns"]) == 3
        assert len(s.metadata["reference_risk"]) > 40
        assert s.input == s.metadata["turns"][0]


def test_no_instruction_arm_is_installed(samples):
    """The pre-registration fixes this run as bare Claude Code."""
    assert all(s.metadata["instruction"] is None for s in samples)
    assert all(s.metadata["arm"] == "none" for s in samples)


def test_turns_are_unwrapped(samples):
    for s in samples:
        assert all("\n" not in t for t in s.metadata["turns"])


def test_fake_keys_stay_unmistakably_fake(samples):
    for s in samples:
        for turn in s.metadata["turns"]:
            if "pat_" in turn:
                assert "pat_EXAMPLE_NOT_A_REAL_KEY" in turn
