from datetime import date
import pytest
from summer_astro.engine import SummerEngine, load_policy
from summer_astro.contracts import DOMAINS
from summer_astro.signals import make_signal
from summer_astro.reasoning import window_engine, aggregate
from summer_astro.diagnostics import diagnostic_views


@pytest.fixture
def request_data():
    # Synthetic public fixture; never publish the owner's birth data.
    return {"birth": {"date": "2000-01-01", "time": "12:00", "timezone": "UTC",
                     "latitude": 40.0, "longitude": 0.0, "uncertainty_minutes": None},
            "start": "2026-10-01", "end": "2026-10-31", "as_of": "2026-09-29T20:00:00Z"}


def test_single_day_raw_complete_without_reading(request_data):
    engine = SummerEngine()
    req = {**request_data, "start": "2025-09-09", "end": "2025-09-09", "max_display": 0}
    result = engine.forecast(req)
    assert result["diagnostics"]["signal_count"] == len(result["raw_signals"]) > 0
    assert result["displayed_readings"] == []
    assert {r["domain"] for r in result["domain_ranking"]} == DOMAINS
    for row in result["domain_ranking"]:
        daily = result["daily_activation"].get(row["domain"], [])
        assert row["score"] == max((r["score"] for r in daily), default=0)
    for signal in result["raw_signals"]:
        assert signal["lineage"]["primitive_ids"] == signal["primitive_ids"]
        assert signal["signal_threshold"] is None
        assert signal["qualification_status"]
        if signal["family"] == "transit":
            assert signal["exactness"]["minimum_sampled_orb_degrees"] is not None


def test_dependent_signals_not_double_counted_and_weak_signals_retained():
    policy = load_policy()
    day = date(2025, 9, 9)
    signals = [make_signal("transit", "tropical", "same-primitive", ["same"], str(i), day, day,
               strength, {"romance": .8}, metadata={"temporal_role": "trigger"}) for i, strength in enumerate([.7, .6, .01])]
    windows, timeline = window_engine(signals, day, day, policy)
    raw, ranking = diagnostic_views(signals, timeline, windows, [], policy)
    row = next(r for r in ranking if r["domain"] == "romance")
    assert row["score"] == aggregate(signals, "romance", day, policy)["score"]
    assert row["score_before_dependence_correction"] > row["score_after_dependence_correction"]
    assert len(raw) == 3 and raw[-1]["strength"] == .01
    assert "below_window_entry_threshold" in raw[-1]["reason_not_qualified"]
    assert row["occurrence_probability"] is None


def test_diagnostics_independent_of_display_cap(request_data):
    engine = SummerEngine()
    first = engine.forecast({**request_data, "max_display": 0})
    second = engine.forecast({**request_data, "max_display": 6})
    assert first["raw_signals"] == second["raw_signals"]
    assert first["domain_ranking"] == second["domain_ranking"]
