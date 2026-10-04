"""Immutable user-labeled development tests; unknown outcomes are not negatives."""
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from .contracts import Strict, DOMAINS, digest
from .taxonomy import EVENT_TYPES, ALL_SUBTYPES
from .validation import maximum_matching
from pydantic import Field, model_validator
from typing import Literal

ERROR_KINDS = {"domain_hit", "subtype_miss", "salience_underestimated", "false_positive", "false_negative", "interpretation_error"}


class ErrorAnnotation(Strict):
    kind: Literal["domain_hit", "subtype_miss", "salience_underestimated", "false_positive", "false_negative", "interpretation_error"]
    domain: str
    subtype: str | None = None
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid(self):
        if self.domain not in DOMAINS: raise ValueError("unknown annotation domain")
        if self.subtype is not None and self.subtype not in ALL_SUBTYPES: raise ValueError("unknown annotation subtype")
        return self


class HistoricalTest(Strict):
    run_id: str
    day: date
    case_id: str = Field(min_length=1, max_length=100)
    actual_domains: list[str] = Field(max_length=30)
    actual_event_types: list[str] = Field(max_length=30)
    actual_subtypes: list[str] = Field(default_factory=list, max_length=30)
    error_annotations: list[ErrorAnnotation] = Field(default_factory=list, max_length=30)
    observation_complete: bool = False
    actual_daily_trigger: bool | None = None
    top_k: int = Field(default=3, ge=1, le=10)
    notes: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def valid(self):
        if any(d not in DOMAINS for d in self.actual_domains): raise ValueError("unknown actual domain")
        if any(t not in EVENT_TYPES or t == "unknown" for t in self.actual_event_types): raise ValueError("unknown actual event type")
        if any(t not in ALL_SUBTYPES for t in self.actual_subtypes): raise ValueError("unknown actual subtype")
        if len(set(self.actual_domains)) != len(self.actual_domains) or len(set(self.actual_event_types)) != len(self.actual_event_types) or len(set(self.actual_subtypes)) != len(self.actual_subtypes):
            raise ValueError("duplicate truth labels")
        return self


def record_test(store, value):
    record = store.get(value.run_id)
    if record is None or record["kind"] != "forecast": raise ValueError("forecast run not found")
    source = record["payload"]
    if source["mode"] != "astrology_only": raise ValueError("historical tests require astrology_only forecasts")
    if value.day > datetime.now(ZoneInfo(source.get("evaluation_timezone", "UTC"))).date():
        raise ValueError("future outcomes cannot be recorded as observed")
    profile = next((p for p in source.get("daily_domain_profiles", []) if p["day"] == value.day.isoformat()), None)
    if profile is None: raise ValueError("selected day is not covered by this forecast's daily profiles")
    predicted = [r["domain"] for r in profile["domains"] if r["trigger_score"] > 0][:value.top_k]
    actual = set(value.actual_domains)
    hit = set(predicted) & actual
    expression_day = next((e for e in source.get("daily_event_expressions", []) if e["day"] == value.day.isoformat()), None)
    detected = sorted({t for r in (expression_day or {}).get("domains", []) for t in r["detected_subtypes"]})
    active_domains = {r["domain"] for r in profile["domains"] if r["trigger_score"] > 0}
    errors = [{"kind": "domain_hit", "domain": d, "basis": "top_k_profile", "provenance": "computed_comparison"} for d in sorted(hit)]
    errors += [{"kind": "false_negative", "domain": d, "basis": "top_k_profile", "provenance": "computed_comparison"} for d in sorted(actual - set(predicted))]
    errors += [{"kind": "subtype_miss", "subtype": t, "basis": "expression_layer", "provenance": "computed_comparison"} for t in sorted(set(value.actual_subtypes) - set(detected))]
    if value.observation_complete:
        errors += [{"kind": "false_positive", "domain": d, "basis": "top_k_profile", "provenance": "computed_comparison"} for d in sorted(set(predicted) - actual)]
    errors += [{**a.model_dump(), "basis": "user_assessment", "provenance": "user_annotation_not_automatic_measurement"} for a in value.error_annotations]
    result = "hit" if actual and actual <= set(predicted) else "partial" if hit else "miss" if actual else "false_positive_profile" if predicted and value.observation_complete else "ordinary_no_profile" if value.observation_complete else "insufficient_outcome_coverage"
    payload = {**value.model_dump(mode="json"), "engine_version": source["engine_version"], "policy_version": source["policy_version"],
        "predicted_top_domains": predicted, "predicted_domain_scores": profile["domains"],
        "predicted_event_types": source["event_type_classification"]["astrology_only_event_types"],
        "predicted_subtypes": detected, "subtype_detection_available": expression_day is not None,
        "expression_snapshot": expression_day, "evaluation_errors": errors,
        "active_domain_hits": sorted(active_domains & actual),
        "daily_support_misses": sorted(actual - active_domains),
        "subtype_misses": sorted(set(value.actual_subtypes) - set(detected)),
        "predicted_daily_trigger": any(r["daily_marker_present"] for r in profile["domains"]),
        "domain_result": result, "hit_domains": sorted(hit), "false_negative_domains": sorted(actual - set(predicted)),
        "false_positive_domains": sorted(set(predicted) - actual) if value.observation_complete else None,
        "candidate_windows": source["all_candidates"], "evaluation_kind": "historical-development-not-blind",
        "prediction_basis": "top-k trigger-only domain profile; not a qualified event prediction"}
    test_id = "historical-" + digest(payload)[:32]
    store.append(test_id, "historical_test", datetime.now(timezone.utc).isoformat(), payload)
    return {"test_id": test_id, **payload, "storage": "temporary trial SQLite; export for retention"}


def confusion(predicted, actual, universe):
    return {d: {"tp": int(d in predicted and d in actual), "fp": int(d in predicted and d not in actual),
                "fn": int(d not in predicted and d in actual), "tn": int(d not in predicted and d not in actual)} for d in universe}


def metrics(counts):
    tp, fp, fn, tn = (counts[k] for k in ["tp", "fp", "fn", "tn"])
    return {**counts, "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "false_positive_rate": fp / (fp + tn) if fp + tn else None,
            "false_negative_rate": fn / (fn + tp) if fn + tp else None}


def report_tests(store, engine_version=None):
    # A corrected label or rerun must not count the same case twice per version.
    latest = {}
    for record in store.list_kind("historical_test"):
        p = record["payload"]
        if engine_version and p["engine_version"] != engine_version: continue
        latest[(p["engine_version"], p["policy_version"], p["case_id"])] = record
    versions = {}
    for (_, _, _), record in latest.items():
        p = record["payload"]; key = (p["engine_version"], p["policy_version"])
        versions.setdefault(key, []).append(p)
    outputs = []
    for (version, policy), cases in versions.items():
        complete = [p for p in cases if p["observation_complete"]]
        counts = {d: {k: 0 for k in ["tp", "fp", "fn", "tn"]} for d in sorted(DOMAINS - {"unknown"})}
        type_counts = {d: {k: 0 for k in ["tp", "fp", "fn", "tn"]} for d in sorted(EVENT_TYPES - {"unknown"})}
        subtype_counts = {d: {k: 0 for k in ["tp", "fp", "fn", "tn"]} for d in sorted(ALL_SUBTYPES)}
        computed_errors = {k: 0 for k in sorted(ERROR_KINDS)}
        annotated_errors = {k: 0 for k in sorted(ERROR_KINDS)}
        for p in cases:
            for e in p.get("evaluation_errors", []):
                bucket = computed_errors if e["provenance"] == "computed_comparison" else annotated_errors
                bucket[e["kind"]] += 1
        trigger_counts = {k: 0 for k in ["tp", "fp", "fn", "tn"]}
        for p in complete:
            for d, c in confusion(set(p["predicted_top_domains"]), set(p["actual_domains"]), counts).items():
                for k, v in c.items(): counts[d][k] += v
            for d, c in confusion(set(p["predicted_event_types"]), set(p["actual_event_types"]), type_counts).items():
                for k, v in c.items(): type_counts[d][k] += v
            # A legacy forecast without this layer is a coverage gap, not a
            # negative prediction by a detector that did not exist.
            if p.get("subtype_detection_available", False):
                for d, c in confusion(set(p.get("predicted_subtypes", [])), set(p["actual_subtypes"]), subtype_counts).items():
                    for k, v in c.items(): subtype_counts[d][k] += v
        trigger_cases = [p for p in cases if p["actual_daily_trigger"] is not None]
        for p in trigger_cases:
            pred, actual = p["predicted_daily_trigger"], p["actual_daily_trigger"]
            trigger_counts["tp" if pred and actual else "fp" if pred else "fn" if actual else "tn"] += 1
        predictions = {c["forecast_id"]: c for p in cases for c in p["candidate_windows"] if c["status"] == "qualified"}
        eligible_cases = [p for p in cases if p["actual_domains"]]
        candidates = list(predictions.values())
        matched = maximum_matching(candidates, eligible_cases, lambda c, p: c["primary_domain"] in p["actual_domains"] and c["trigger_interval"]["start"] <= p["day"] <= c["trigger_interval"]["end"])
        errors = [abs((date.fromisoformat(candidates[i]["peak_interval"]["start"]) - date.fromisoformat(eligible_cases[j]["day"])).days) for i, j in matched]
        sweep=[]
        for threshold in [0.0, .2, .3, .38, .45, .52, .55, .65]:
            total={k:0 for k in ["tp","fp","fn","tn"]};covered=0
            for p in complete:
                selected={r["domain"] for r in p["predicted_domain_scores"] if r["trigger_present"] and r["combined_score"]>=threshold}
                covered+=bool(selected)
                for c in confusion(selected,set(p["actual_domains"]),counts).values():
                    for k,v in c.items():total[k]+=v
            sweep.append({"combined_score_threshold":threshold,"micro_domain_profile_metrics":metrics(total),
                          "case_coverage":covered/len(complete) if complete else None})
        outputs.append({"engine_version": version, "policy_version": policy, "case_count": len(cases),
            "complete_observation_case_count": len(complete), "partial_observation_case_count": len(cases) - len(complete),
            "domain_profile_metrics": {d: metrics(c) for d, c in counts.items()},
            "top_k_domain_hit_rate": sum(bool(p["hit_domains"]) for p in eligible_cases) / len(eligible_cases) if eligible_cases else None,
            "event_type_metrics": {d: metrics(c) for d, c in type_counts.items()},
            "event_type_coverage": sum(bool(p["predicted_event_types"]) for p in cases) / len(cases) if cases else None,
            "event_type_abstention_count": sum(not p["predicted_event_types"] for p in cases),
            "subtype_metrics": {d: metrics(c) for d, c in subtype_counts.items()},
            "subtype_complete_observation_cases": sum(p.get("subtype_detection_available", False) for p in complete),
            "subtype_miss_count": sum(len(p.get("subtype_misses", [])) for p in cases),
            "error_counts": {"computed_comparisons": computed_errors, "user_annotations": annotated_errors},
            "salience_policy": "user-assessed underestimation is separate from domain-score accuracy; no automatic tuning",
            "daily_marker_metrics": metrics(trigger_counts), "daily_marker_labeled_cases": len(trigger_cases),
            "threshold_sweep":sweep,"threshold_sweep_policy":"development analysis only; does not automatically change production thresholds",
            "timing": {"matching": "one-to-one, qualified candidate and matching domain, actual day inside interval",
                       "matched_case_count": len(matched), "mean_peak_error_days": sum(errors) / len(errors) if errors else None},
            "notes": "Profile metrics describe top-k domain support, not event forecasting accuracy. Unknown event types are abstentions; their recall/coverage remain visible."})
    return {"evaluation_kind": "historical-development-not-blind", "versions": outputs,
            "case_count": len(latest), "no_data_means_no_accuracy": not bool(latest),
            "storage": "temporary trial SQLite; export for retention"}
