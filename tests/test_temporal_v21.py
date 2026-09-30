from datetime import date
import pytest
from summer_astro.contracts import ForecastRequest
from summer_astro.engine import SummerEngine, load_policy
from summer_astro.signals import make_signal
from summer_astro.temporal import daily_views, daily_reading
from summer_astro.storage import ForecastStore
from summer_astro.historical import HistoricalTest, record_test, report_tests
from summer_astro.taxonomy import classify_events


@pytest.fixture
def req():
    return ForecastRequest.model_validate({"birth": {"date": "2000-01-01", "time": "12:00", "timezone": "UTC", "latitude": 40, "longitude": 0},
        "start": "2025-09-09", "end": "2025-09-09", "as_of": "2026-09-30T20:00:00Z"})


def test_background_does_not_become_daily_work(req):
    day = req.start
    bg = make_signal("dasha", "sidereal_lahiri", "d", ["moon"], "DASHA-1", day, day, 1, {"work_routine": 1}, metadata={"temporal_role": "background"})
    profiles, summary = daily_views([bg], req, load_policy(), {"stability": 1})
    row = next(r for r in profiles[0]["domains"] if r["domain"] == "work_routine")
    assert row["background_score"] == .16 and row["trigger_score"] == 0
    assert row["combined_score"] == .16 and not row["trigger_present"]
    assert row["signal_band"] == "background_only"
    assert daily_reading(profiles[0], req, load_policy(), 6) == []
    assert summary[0]["triggers"] == []


def test_request_clipped_sample_peak_not_exact_marker(req):
    s = make_signal("transit", "tropical", "t", ["p"], "TRANSIT-1", req.start, req.end, .8, {"self": .9},
                    metadata={"temporal_role": "trigger", "peak_day": req.start.isoformat(), "exact_times": []})
    profiles, summary = daily_views([s], req, load_policy(), {"stability": 1})
    row = next(r for r in profiles[0]["domains"] if r["domain"] == "self")
    assert row["trigger_present"] and not row["daily_marker_present"]
    assert summary[0]["triggers"][0]["sampled_peak_in_requested_interval"]
    assert summary[0]["daily_marker_count"] == 0


def test_baselines_reproducible_and_do_not_change_forecast(req, tmp_path):
    store = ForecastStore(tmp_path / "tests.sqlite")
    engine = SummerEngine(store)
    plain = engine.forecast(req)
    value = req.model_dump(mode="json"); value["negative_controls"] = {"sample_count": 4, "radius_days": 7, "seed": 17}
    controlled = engine.forecast(value)
    again = engine.forecast(value)
    assert controlled["run_id"] == plain["run_id"]
    assert controlled["negative_controls"] == again["negative_controls"]
    assert req.start.isoformat() not in controlled["negative_controls"]["baseline_days"]
    assert controlled["negative_controls"]["false_positive_rate"] is None
    assert store.counts() == {"forecast": 1, "negative_control": 1}
    for r in controlled["negative_controls"]["domains"]:
        if r["background_score"]["baseline_std"] == 0:
            assert r["background_score"]["z_score"] is None


def test_multi_day_negative_controls_rejected(req):
    value = req.model_dump(mode="json"); value.update(end="2025-09-10", negative_controls={})
    with pytest.raises(ValueError, match="one day"): ForecastRequest.model_validate(value)


def test_participants_do_not_infer_family_romance_or_loss(req):
    result = classify_events(req, [])
    assert result["primary_event_type"] == "unknown"
    assert result["astrology_only_event_types"] == []
    value = req.model_dump(mode="json")
    value.update(mode="context_assisted", context=[{"fact_id": "meeting", "known_at": "2025-09-08T00:00:00Z", "start": "2025-09-09", "end": "2025-09-09",
        "primary_domain": "networks", "subject_id": "meeting", "event_type": "social_gathering", "participant_roles": ["family_member", "romantic_acquaintance"]}])
    context = classify_events(ForecastRequest.model_validate(value), [])
    assert context["context_supplied_events"][0]["primary_domain"] == "networks"
    assert context["astrology_only_event_types"] == []


def test_historical_log_unknown_is_not_negative_and_no_double_count(req, tmp_path):
    store = ForecastStore(tmp_path / "history.sqlite")
    result = SummerEngine(store).forecast(req)
    value = {"run_id": result["run_id"], "case_id": "case-1", "day": "2025-09-09", "actual_domains": ["vehicle"], "actual_event_types": ["vehicle_delivery"]}
    first = record_test(store, HistoricalTest.model_validate(value))
    assert first["false_positive_domains"] is None
    report = report_tests(store)
    assert report["versions"][0]["complete_observation_case_count"] == 0
    second = record_test(store, HistoricalTest.model_validate({**value, "observation_complete": True, "notes": "complete day"}))
    assert second["test_id"] != first["test_id"] and store.counts()["historical_test"] == 2
    report = report_tests(store)
    assert report["case_count"] == 1
    assert report["versions"][0]["event_type_coverage"] == 0
    assert report["versions"][0]["event_type_metrics"]["vehicle_delivery"]["fn"] == 1
    assert report["versions"][0]["domain_profile_metrics"]["vehicle"]["fn"] == 1


def test_empty_log_does_not_invent_accuracy(tmp_path):
    report = report_tests(ForecastStore(tmp_path / "empty.sqlite"))
    assert report["versions"] == [] and report["no_data_means_no_accuracy"]


def test_historical_api_authorized_and_explicit_labels(req, tmp_path):
    from fastapi.testclient import TestClient
    from summer_astro.api import create_app
    client=TestClient(create_app(tmp_path/"api.sqlite",token="test-key"))
    headers={"Authorization":"Bearer test-key"}
    assert client.get("/historical-tests").status_code==401
    result=client.post("/forecast",json=req.model_dump(mode="json"),headers=headers).json()
    value={"run_id":result["run_id"],"case_id":"test-case","day":"2025-09-09","actual_domains":[],"actual_event_types":[],"observation_complete":True}
    assert client.post("/historical-tests",json=value,headers=headers).status_code==200
    assert client.get("/historical-tests",headers=headers).json()["case_count"]==1
    assert len(client.get("/historical-tests/export",headers=headers).json()["records"])==1


def test_exact_marker_survives_single_day_request(req):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    value=req.model_dump(mode="json");value.update(start="2025-01-01",end="2025-12-31",max_display=0)
    full=SummerEngine().forecast(value)
    times=[x for s in full["raw_signals"] if s["family"]=="transit" for x in s["metadata"]["exact_times"]]
    assert times
    day=datetime.fromisoformat(times[0]).astimezone(ZoneInfo(req.birth.timezone)).date().isoformat()
    value.update(start=day,end=day)
    one=SummerEngine().forecast(value)
    assert one["daily_trigger_summary"][0]["daily_marker_count"]>0
