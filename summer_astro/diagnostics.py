"""Auditable numerical views. No event narrative or probability inference."""
from datetime import date
from .contracts import DOMAINS
from .reasoning import strength_on


def family_weight(signal, policy):
    return 1.0 if signal.family == "context" and signal.metadata.get("role") == "core" else policy["family_weights"].get(signal.family, 0.0)


def candidate_reasons(candidate, policy):
    reasons = []
    if candidate["activation_score"] < policy["qualification_score"]:
        reasons.append("below_qualification_threshold")
    if 1 - candidate["domain_ambiguity"] < policy["ambiguity_margin"]:
        reasons.append("competing_domains_not_separated")
    if candidate["input_stability"] is None:
        reasons.append("birth_time_uncertainty_unknown")
    elif candidate["input_stability"] < policy["min_input_stability"]:
        reasons.append("birth_time_sensitive")
    return reasons


def diagnostic_views(signals, timeline, windows, candidates, policy):
    raw = []
    for s in signals:
        linked = [c for c in candidates if s.signal_id in c["evidence_ids"] or s.signal_id in c["counterevidence_ids"]]
        eligible = any(c["status"] == "qualified" for c in linked)
        signal_windows = [w for w in windows if s.signal_id in w["evidence_ids"] or s.signal_id in w["counterevidence_ids"]]
        reasons = sorted({r for c in linked for r in candidate_reasons(c, policy)})
        if not signal_windows:
            supported_rows = [r for d in set(s.domain_support) | set(s.negative_support or {}) for r in timeline.get(d, []) if s.active(date.fromisoformat(r["day"]))]
            if not any(r["trigger_ids"] for r in supported_rows):
                reasons.append("no_trigger_for_supported_domains")
            if not any(r["score"] >= policy["threshold_enter"] for r in supported_rows):
                reasons.append("below_window_entry_threshold")
        m = s.metadata
        attribution = []
        for domain in sorted(set(s.domain_support) | set(s.negative_support or {})):
            positive = s.domain_support.get(domain, 0)
            negative = (s.negative_support or {}).get(domain, 0)
            attribution.append({"domain": domain, "subdomain": None,
                "support": positive, "opposition": negative,
                "direction": "mixed" if positive and negative else "supports" if positive else "opposes",
                "weighted_support_at_signal_peak": round(positive * s.strength * family_weight(s, policy), 6),
                "weighted_opposition_at_signal_peak": round(negative * s.strength * family_weight(s, policy), 6)})
        raw.append({**s.to_dict(), "rule_name": s.rule_ids[0] if len(s.rule_ids) == 1 else None,
            "rule_version": policy["version"],
            "lineage": {"family": s.family, "framework": s.framework, "dependency_group": s.dependency_group,
                "primitive_ids": s.primitive_ids, "rule_ids": s.rule_ids},
            "domain": None, "subdomain": None, "domain_attribution": attribution,
            "weight": family_weight(s, policy), "direction": "per_domain_attribution",
            "exactness": {"orb_limit_degrees": m.get("orb"), "minimum_sampled_orb_degrees": m.get("minimum_sampled_orb_degrees"),
                "exact_times_utc": m.get("exact_times", []), "sampling_time_utc": "12:00" if s.family == "transit" else None,
                "precision": m.get("precision"), "daily_orb_degrees": m.get("daily_orb_degrees")},
            "trigger_date": s.start if m.get("temporal_role") == "trigger" else None,
            "peak_date": m.get("peak_day"), "temporal_role": m.get("temporal_role"),
            "evidence": {"technique": s.family, "framework": s.framework, "metadata": m},
            "qualification_status": "contributes_to_qualified_candidate" if eligible else "included_not_in_qualified_candidate",
            "signal_threshold": None, "signal_threshold_note": "No standalone signal threshold; qualification applies to aggregated candidates.",
            "reason_not_qualified": None if eligible else sorted(set(reasons)) or ["no_qualified_candidate"],
            "window_ids": [w["window_id"] for w in signal_windows],
            "candidate_qualification": [{"forecast_id": c["forecast_id"], "status": c["status"], "reasons": candidate_reasons(c, policy)} for c in linked]})
    ranking = []
    for domain in sorted(DOMAINS):
        rows = timeline.get(domain, [])
        if rows:
            peak = max(rows, key=lambda r: r["score"])
            day = date.fromisoformat(peak["day"])
            active = [s for s in signals if s.active(day)]
            before = sum((s.domain_support.get(domain, 0) - (s.negative_support or {}).get(domain, 0)) * strength_on(s, day) * family_weight(s, policy) for s in active)
            score = peak["score"]
        else:
            peak = None
            before = score = 0.0
        linked = [c for c in candidates if domain in c["domain_support"]]
        domain_windows = [w for w in windows if w["domain"] == domain]
        reasons = sorted({r for c in linked for r in candidate_reasons(c, policy)})
        if not domain_windows:
            if not any(r["trigger_ids"] for r in rows): reasons.append("no_trigger_for_domain")
            if score < policy["threshold_enter"]: reasons.append("below_window_entry_threshold")
        qualified = any(c["status"] == "qualified" and c["primary_domain"] == domain for c in linked)
        ranking.append({"domain": domain, "score": score, "detection_status": "no_astrological_detector" if domain in {"vehicle", "loss"} else "heuristic_domain_rules",
            "score_before_dependence_correction": round(max(0, before), 6),
            "score_after_dependence_correction": score, "score_comparison_day": peak["day"] if peak else None,
            "score_basis": "maximum daily adjusted support within requested interval; unadjusted sum on the same day",
            "contributing_signal_ids": peak["evidence_ids"] if peak else [],
            "counterevidence_ids": peak["counterevidence_ids"] if peak else [],
            "family_contributions": peak["families"] if peak else {},
            "qualification_status": "qualified_primary_domain" if qualified else "not_qualified_as_primary_domain",
            "reason_not_qualified": None if qualified else sorted(set(reasons)) or ["not_selected_as_qualified_primary_domain"],
            "window_ids": [w["window_id"] for w in domain_windows],
            "candidate_qualification": [{"forecast_id": c["forecast_id"], "status": c["status"], "reasons": candidate_reasons(c, policy)} for c in linked],
            "occurrence_probability": None})
    ranking.sort(key=lambda r: (-r["score"], r["domain"]))
    rank = 0
    last = None
    for i, row in enumerate(ranking, 1):
        if row["score"] != last: rank = i
        row["rank"] = rank
        last = row["score"]
    return raw, ranking
