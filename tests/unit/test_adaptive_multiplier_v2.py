"""Unit tests for redesigned AdaptiveMultiplier.

Design change: softer inflation rates to prevent one-round budget explosions
while allowing higher mult_max for gradual long-term growth.

Zone changes:
  Zone 4 (0.5 < ER < 1.0):  ×1.5 → ×1.3
  Zone 5 (ER == 1.0):       ×2.0 → ×1.5
  mult_max:                  5.0  → 50.0

Unchanged:
  Zone 1 (ER == 0):          ×(1 - cool_down) = ×0.95
  Zone 2 (0 < ER ≤ target):  no change
  Zone 3 (target < ER ≤ 0.5): ×1.2
  mult_min:                   0.5
"""
import pytest

from midas_agent.config import MidasConfig
from midas_agent.scheduler.budget_allocator import AdaptiveMultiplier


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_am(init=1.0, er_target=0.1, cool_down=0.05, mult_min=0.5, mult_max=50.0):
    return AdaptiveMultiplier(
        mode="adaptive",
        init_value=init,
        er_target=er_target,
        cool_down=cool_down,
        mult_min=mult_min,
        mult_max=mult_max,
    )


# ===========================================================================
# Zone behavior: individual zone rates
# ===========================================================================


@pytest.mark.unit
class TestZoneRates:
    """Verify each zone's inflation/deflation rate."""

    def test_zone1_er_zero_deflates(self):
        """ER=0 → multiplier × 0.95 (unchanged from old design)."""
        am = _make_am(init=2.0)
        result = am.update(eviction_rate=0.0)
        assert result == pytest.approx(2.0 * 0.95)

    def test_zone2_dead_zone_no_change(self):
        """0 < ER ≤ er_target → no change (unchanged)."""
        am = _make_am(init=2.0, er_target=0.1)
        result = am.update(eviction_rate=0.05)
        assert result == pytest.approx(2.0)

    def test_zone2_at_er_target_no_change(self):
        """ER exactly at er_target → dead zone, no change."""
        am = _make_am(init=2.0, er_target=0.1)
        result = am.update(eviction_rate=0.1)
        assert result == pytest.approx(2.0)

    def test_zone3_moderate_inflate(self):
        """er_target < ER ≤ 0.5 → ×1.2 (unchanged)."""
        am = _make_am(init=1.0)
        result = am.update(eviction_rate=0.3)
        assert result == pytest.approx(1.0 * 1.2)

    def test_zone3_at_half(self):
        """ER=0.5 → still Zone 3 → ×1.2."""
        am = _make_am(init=1.0)
        result = am.update(eviction_rate=0.5)
        assert result == pytest.approx(1.0 * 1.2)

    def test_zone4_strong_inflate_new_rate(self):
        """0.5 < ER < 1.0 → ×1.3 (was ×1.5). Softer to prevent explosion."""
        am = _make_am(init=1.0)
        result = am.update(eviction_rate=0.7)
        assert result == pytest.approx(1.0 * 1.3), (
            f"Zone 4 should be ×1.3 (new design), got {result}"
        )

    def test_zone4_at_0_9(self):
        """ER=0.9 → Zone 4 → ×1.3."""
        am = _make_am(init=2.0)
        result = am.update(eviction_rate=0.9)
        assert result == pytest.approx(2.0 * 1.3)

    def test_zone5_emergency_new_rate(self):
        """ER=1.0 → ×1.5 (was ×2.0). Softer emergency response."""
        am = _make_am(init=1.0)
        result = am.update(eviction_rate=1.0)
        assert result == pytest.approx(1.0 * 1.5), (
            f"Zone 5 should be ×1.5 (new design), got {result}"
        )

    def test_zone5_from_high_base(self):
        """ER=1.0 from multiplier=10.0 → 10.0 × 1.5 = 15.0."""
        am = _make_am(init=10.0)
        result = am.update(eviction_rate=1.0)
        assert result == pytest.approx(10.0 * 1.5)


# ===========================================================================
# Boundary precision
# ===========================================================================


@pytest.mark.unit
class TestZoneBoundaries:
    """Test exact boundary values between zones."""

    def test_just_above_er_target(self):
        """ER just above er_target enters Zone 3."""
        am = _make_am(init=1.0, er_target=0.1)
        result = am.update(eviction_rate=0.1001)
        assert result == pytest.approx(1.0 * 1.2)

    def test_just_above_half(self):
        """ER just above 0.5 enters Zone 4 (×1.3, not ×1.2)."""
        am = _make_am(init=1.0)
        result = am.update(eviction_rate=0.5001)
        assert result == pytest.approx(1.0 * 1.3)

    def test_just_below_one(self):
        """ER=0.9999 is Zone 4 (×1.3), not Zone 5 (×1.5)."""
        am = _make_am(init=1.0)
        result = am.update(eviction_rate=0.9999)
        assert result == pytest.approx(1.0 * 1.3)


# ===========================================================================
# Clamping
# ===========================================================================


@pytest.mark.unit
class TestClamping:
    """Test mult_min and mult_max clamping."""

    def test_mult_max_50(self):
        """Multiplier is clamped at 50.0 (new max, was 5.0)."""
        am = _make_am(init=40.0, mult_max=50.0)
        result = am.update(eviction_rate=1.0)
        # 40 × 1.5 = 60, clamped to 50
        assert result == 50.0

    def test_mult_max_holds_at_ceiling(self):
        """Once at max, repeated inflation stays at max."""
        am = _make_am(init=50.0, mult_max=50.0)
        for _ in range(10):
            result = am.update(eviction_rate=1.0)
        assert result == 50.0

    def test_mult_min_holds_at_floor(self):
        """Repeated deflation stops at mult_min."""
        am = _make_am(init=0.6, mult_min=0.5)
        for _ in range(100):
            am.update(eviction_rate=0.0)
        assert am.current_value == pytest.approx(0.5)

    def test_config_default_mult_max_is_50(self):
        """MidasConfig default mult_max should be 50.0."""
        config = MidasConfig(
            initial_budget=100000,
            workspace_count=2,
            runtime_mode="graph_emergence",
        )
        assert config.mult_max == 50.0


# ===========================================================================
# Multi-episode sequences
# ===========================================================================


@pytest.mark.unit
class TestMultiEpisodeSequences:
    """Test multiplier behavior across realistic episode sequences."""

    def test_10_consecutive_exhaustions_reaches_near_50(self):
        """10 consecutive ER=1.0 episodes: 1.0 × 1.5^10 ≈ 57.7,
        clamped at 50.0. Gradual growth, not explosive."""
        am = _make_am(init=1.0, mult_max=50.0)
        for _ in range(10):
            am.update(eviction_rate=1.0)
        assert am.current_value == 50.0
        # Verify it took multiple rounds to hit max, not 2-3
        # 1.5^n >= 50 → n >= log(50)/log(1.5) ≈ 9.6 → 10 rounds
        am2 = _make_am(init=1.0, mult_max=50.0)
        for i in range(9):
            am2.update(eviction_rate=1.0)
        # After 9 rounds: 1.5^9 ≈ 38.4, still under 50
        assert am2.current_value < 50.0

    def test_5_exhaustions_is_moderate(self):
        """5 consecutive ER=1.0: 1.0 × 1.5^5 ≈ 7.6. Not explosive."""
        am = _make_am(init=1.0)
        for _ in range(5):
            am.update(eviction_rate=1.0)
        expected = 1.0 * 1.5 ** 5  # ≈ 7.59
        assert am.current_value == pytest.approx(expected, rel=0.01)
        assert am.current_value < 10.0, "5 rounds should not exceed 10x"

    def test_3_exhaustions_then_stabilize(self):
        """3 ER=1.0 then ER drops to dead zone → multiplier holds."""
        am = _make_am(init=1.0, er_target=0.1)
        for _ in range(3):
            am.update(eviction_rate=1.0)
        val_after_inflate = am.current_value  # 1.5^3 ≈ 3.375

        # Dead zone: no change
        for _ in range(5):
            am.update(eviction_rate=0.05)
        assert am.current_value == pytest.approx(val_after_inflate)

    def test_inflate_then_deflate_convergence(self):
        """After inflating to 20, deflation at ×0.95/round takes
        ~28 rounds to halve to 10."""
        am = _make_am(init=20.0)
        rounds_to_half = 0
        while am.current_value > 10.0:
            am.update(eviction_rate=0.0)
            rounds_to_half += 1
            if rounds_to_half > 100:
                break
        # log(0.5) / log(0.95) ≈ 13.5 rounds to halve
        assert 10 <= rounds_to_half <= 20, (
            f"Expected ~14 rounds to halve from 20 to 10, got {rounds_to_half}"
        )

    def test_from_max_deflate_to_1(self):
        """From mult_max=50, deflation at ×0.95/round to reach ~1.0
        takes ~76 rounds. Slow but steady."""
        am = _make_am(init=50.0)
        rounds = 0
        while am.current_value > 1.05:
            am.update(eviction_rate=0.0)
            rounds += 1
            if rounds > 200:
                break
        # log(1/50) / log(0.95) ≈ 76 rounds
        assert 60 <= rounds <= 90, (
            f"Expected ~76 rounds to deflate from 50 to 1, got {rounds}"
        )

    def test_realistic_swebench_scenario(self):
        """Realistic scenario: first 3 episodes all-exhausted (ER=1.0),
        then agents start solving (ER drops to 0.3), then stable (ER=0).

        Multiplier should inflate to handle initial budget shortage,
        then slowly deflate once budget is sufficient."""
        am = _make_am(init=1.0)

        # Phase 1: all-exhausted, need more budget
        for _ in range(3):
            am.update(eviction_rate=1.0)
        phase1_value = am.current_value
        assert phase1_value > 2.0, "Should have inflated significantly"

        # Phase 2: partial success, moderate ER
        for _ in range(5):
            am.update(eviction_rate=0.3)
        phase2_value = am.current_value
        assert phase2_value > phase1_value, (
            "ER=0.3 is Zone 3 (×1.2), should still inflate"
        )

        # Phase 3: agents performing well, no exhaustion
        for _ in range(10):
            am.update(eviction_rate=0.0)
        phase3_value = am.current_value
        assert phase3_value < phase2_value, (
            "ER=0 should deflate multiplier"
        )

    def test_oscillating_er(self):
        """ER alternates between 0 (deflate) and 1.0 (inflate).
        Net effect: 1.5 × 0.95 = 1.425 per 2 rounds → slow growth."""
        am = _make_am(init=1.0)
        for _ in range(10):
            am.update(eviction_rate=1.0)  # ×1.5
            am.update(eviction_rate=0.0)  # ×0.95
        # After 10 cycles: 1.0 × (1.5 × 0.95)^10 = 1.0 × 1.425^10 ≈ 27.3
        expected = (1.5 * 0.95) ** 10
        assert am.current_value == pytest.approx(expected, rel=0.05)


# ===========================================================================
# Static mode unchanged
# ===========================================================================


@pytest.mark.unit
class TestStaticModeUnchanged:
    """Static mode must be completely unaffected by design change."""

    def test_static_ignores_all_er(self):
        """Static mode always returns init_value."""
        am = AdaptiveMultiplier(mode="static", init_value=1.5)
        for er in [0.0, 0.1, 0.3, 0.5, 0.7, 1.0]:
            result = am.update(eviction_rate=er)
            assert result == 1.5


# ===========================================================================
# Comparison with old design (regression awareness)
# ===========================================================================


@pytest.mark.unit
class TestOldDesignDifferences:
    """Explicitly test that old rates are NOT used."""

    def test_zone4_not_1_5(self):
        """Zone 4 must be ×1.3, NOT the old ×1.5."""
        am = _make_am(init=1.0)
        result = am.update(eviction_rate=0.7)
        assert result != pytest.approx(1.5), "Old rate ×1.5 must not be used"
        assert result == pytest.approx(1.3)

    def test_zone5_not_2_0(self):
        """Zone 5 must be ×1.5, NOT the old ×2.0."""
        am = _make_am(init=1.0)
        result = am.update(eviction_rate=1.0)
        assert result != pytest.approx(2.0), "Old rate ×2.0 must not be used"
        assert result == pytest.approx(1.5)

    def test_mult_max_not_5(self):
        """Default mult_max must be 50.0, NOT the old 5.0."""
        config = MidasConfig(
            initial_budget=100000,
            workspace_count=2,
            runtime_mode="graph_emergence",
        )
        assert config.mult_max != 5.0, "Old mult_max=5.0 must not be used"
        assert config.mult_max == 50.0

    def test_old_design_would_overshoot(self):
        """With old ×2.0 rate, 3 rounds would reach 8.0.
        With new ×1.5 rate, 3 rounds reach 3.375. Much safer."""
        am = _make_am(init=1.0)
        for _ in range(3):
            am.update(eviction_rate=1.0)
        assert am.current_value < 4.0, (
            f"3 rounds of ER=1.0 should be < 4.0 (new design), "
            f"got {am.current_value}"
        )
