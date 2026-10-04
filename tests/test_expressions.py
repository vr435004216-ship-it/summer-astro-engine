import copy
import json
import os
from pathlib import Path
import pytest
from summer_astro.contracts import ForecastRequest
from summer_astro.engine import SummerEngine, load_policy
from summer_astro.signals import make_signal
from summer_astro.temporal import daily_views, daily_reading
from summer_astro.expressions import expression_views, attach_reading_expressions
from summer_astro.storage import ForecastStore
from summer_astro.historical import HistoricalTest, record_test, report_tests


@pytest.fixture
def req():
    return ForecastRequest.model_validate({"birth": {"date": "2000-01-01", "time": "12:00", "timezone": "UTC", "latitude": 40, "longitude": 0},
        "start": "2025-09-09", "end": "2025-09-09", "as_of": "2026-09-30T20:00:00Z"})


def views(req, support, axes=None):
    signal = make_signal("transit", "tropical", "one", ["primitive"], "TRANSIT-1", req.start, req.end, .8, support,
                         axes=axes, metadata={"temporal_role": "trigger"})
    profiles, _ = daily_views([signal], req, load_policy(), {"stability": 1})
    original = copy.deepcopy(profiles)
    output = expression_views(profiles, [signal], req)
    assert profiles == original
    return profiles, output


@pytest.mark.parametrize("support", [{"partnership": 1}, {"shared_resources": 1}, {"partnership": 1, "shared_resources": 1, "romance": 1}])
def test_coactivation_does_not_identify_intimacy(req, support):
    _, output = views(req, support)
    assert all(not r["detected_subtypes"] for r in output[0]["domains"])
    assert output[0]["intimacy_guard"]["coactivation_alone_is_insufficient"]
    resource = next(r for r in output[0]["domains"] if r["domain"] == "shared_resources")
    assert resource["candidate_expressions"] == []


def test_withdrawal_keeps_internal_external_uncertainty(req):
    _, output = views(req, {"withdrawal": 1, "self": 1})
    row = next(r for r in output[0]["domains"] if r["domain"] == "withdrawal")
    assert row["internal_vs_external"] == "unknown"
    assert {"internal_withdrawal", "external_withdrawal"} <= set(row["candidate_expressions"])
    assert not row["detected_subtypes"]
    assert row["event_salience"] is None


def test_work_parallel_without_score_or_threshold_boost(req):
    profiles, output = views(req, {"self": 1, "work_routine": .6}, {"constraint": .85})
    reading = daily_reading(profiles[0], req, load_policy(), 6)
    before = copy.deepcopy(reading[0]["domains"])
    attach_reading_expressions(reading, output)
    assert reading[0]["domains"] == before
    work = reading[0]["practical_parallel_support"][0]
    assert work["expression_type"] == "unknown_expression"
    assert work["supported_modifiers"][0]["modifier"] == "constraint"
    assert "للروتين العملي" in reading[0]["summary"]


def test_no_trigger_no_family_and_no_communication_carrier(req):
    _, output = views(req, {"partnership": 1})
    rows = {r["domain"]: r for r in output[0]["domains"]}
    assert rows["family"]["qualification_status"] == "no_daily_support"
    assert rows["communication"]["qualification_status"] == "no_daily_support"
    assert rows["partnership"]["carrier_domain"] is None


def test_context_subtypes_do_not_become_predictions(req):
    value = req.model_dump(mode="json")
    value.update(mode="context_assisted", context=[{"fact_id": "known", "subject_id": "subject", "known_at": "2025-09-08T00:00:00Z",
        "start": "2025-09-09", "end": "2025-09-09", "primary_domain": "partnership", "subtypes": ["sexual_contact"]}])
    _, output = views(ForecastRequest.model_validate(value), {"partnership": 1})
    assert output[0]["context_supplied_expressions"][0]["expression_types"] == ["sexual_contact"]
    assert all(not r["detected_subtypes"] for r in output[0]["domains"])


def test_validation_distinguishes_errors_and_never_rewrites_forecast(req, tmp_path):
    store = ForecastStore(tmp_path / "tests.sqlite")
    result = SummerEngine(store).forecast(req)
    before = store.get(result["run_id"])
    record = record_test(store, HistoricalTest.model_validate({"run_id": result["run_id"], "case_id": "generic-case", "day": "2025-09-09",
        "actual_domains": ["partnership", "family", "work_routine"], "actual_event_types": ["relationship_contact", "family_event"],
        "actual_subtypes": ["sexual_contact", "internal_withdrawal", "access_system_issue", "family_meal"],
        "error_annotations": [{"kind": "salience_underestimated", "domain": "work_routine", "reason": "User assessment of practical salience."}]}))
    assert store.get(result["run_id"]) == before
    assert record["false_positive_domains"] is None
    assert "sexual_contact" in record["subtype_misses"]
    report = report_tests(store)["versions"][0]
    assert report["error_counts"]["user_annotations"]["salience_underestimated"] == 1
    assert report["error_counts"]["computed_comparisons"]["salience_underestimated"] == 0


def test_private_regression_fixture():
    # User truth and birth data belong in a private fixture, never this repository.
    path = os.environ.get("SUMMER_PRIVATE_REGRESSION")
    if not path: pytest.skip("private owner fixture not supplied")
    fixture = json.loads(Path(path).read_text())
    result = SummerEngine().forecast(fixture["request"])
    for key in ["domain_ranking", "daily_domain_profiles", "raw_signals", "raw_windows"]:
        assert result[key] == fixture["baseline"][key]
    assert result["qualification_policy"] == fixture["baseline"]["qualification_policy"]
    assert load_policy() == fixture["policy"]
    rows = {r["domain"]: r for r in result["daily_event_expressions"][0]["domains"]}
    for d in fixture["expected_active_domains"]:
        assert rows[d]["evidence_ids"]
    assert rows["family"]["qualification_status"] == "no_daily_support"
    assert rows["withdrawal"]["internal_vs_external"] == "unknown"
    assert not any(r["detected_subtypes"] for r in rows.values())
