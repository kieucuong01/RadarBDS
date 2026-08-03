import math

import pytest

from services.signal_quality import effective_signal_mos_min


@pytest.mark.parametrize("tier", ("guest", "free", "unknown", ""))
@pytest.mark.parametrize("requested", (None, 0, 10, 20, "bad", math.inf))
def test_non_privileged_tiers_are_fixed_at_fifteen(tier, requested):
    assert effective_signal_mos_min(tier, requested) == 15.0


@pytest.mark.parametrize("tier", ("vip", "admin"))
@pytest.mark.parametrize("requested", (None, "", "bad", math.inf, -math.inf, math.nan))
def test_privileged_missing_or_invalid_values_default_to_fifteen(tier, requested):
    assert effective_signal_mos_min(tier, requested) == 15.0


@pytest.mark.parametrize("tier", ("vip", "admin"))
def test_privileged_explicit_values_are_retained_and_clamped(tier):
    assert effective_signal_mos_min(tier, 10) == 10.0
    assert effective_signal_mos_min(tier, "12.5") == 12.5
    assert effective_signal_mos_min(tier, -5) == 0.0
    assert effective_signal_mos_min(tier, 80) == 70.0


def test_explicit_flag_distinguishes_missing_from_numeric_zero():
    assert effective_signal_mos_min("vip", 0, was_explicit=False) == 15.0
    assert effective_signal_mos_min("vip", 0, was_explicit=True) == 0.0
