"""Separate active timing support from long-period context and day-local markers."""
from datetime import date, datetime, timedelta
from math import log
from .contracts import DOMAINS
from .reasoning import aggregate, strength_on
from .readings import NAMES


def marker(signal, day, tz):
    m = signal.metadata
    exact = [x for x in m.get("exact_times", []) if datetime.fromisoformat(x).astimezone(tz).date() == day]
    # Transit start/end and sampled peaks are clipped to a request: never call
    # these astronomical onsets or precise daily event markers.
    return {"exact_times_local_day": exact, "daily_marker_present": bool(exact),
            "sampled_peak_in_requested_interval": m.get("peak_day") == day.isoformat(),
            "interval_boundary_is_request_clipped": signal.family == "transit"}


def daily_views(signals, request, policy, sensitivity):
    backgrounds = [s for s in signals if s.metadata.get("temporal_role") == "background"]
    triggers = [s for s in signals if s.metadata.get("temporal_role") == "trigger"]
    profiles = []; summary = []; day = request.start
    tz = request.birth.instant().tzinfo
    domains = sorted(DOMAINS)
    while day <= request.end:
        active = [s for s in triggers if s.active(day)]
        day_summary = []
        for s in active:
            day_summary.append({"signal_id": s.signal_id, "family": s.family, "framework": s.framework,
                "strength": strength_on(s, day), "domain_support": s.domain_support,
                "planet": s.metadata.get("planet"), "target": s.metadata.get("target"),
                "aspect": s.metadata.get("aspect"), "orb_degrees": s.metadata.get("daily_orb_degrees", {}).get(day.isoformat()),
                "temporal_kind": "active_slow_transit" if s.family == "transit" else "user_context",
                **marker(s, day, tz), "not_an_observed_event": True})
        day_summary.sort(key=lambda s: (-int(s["daily_marker_present"]), -s["strength"], s["signal_id"]))
        summary.append({"day": day.isoformat(), "triggers": day_summary,
                        "daily_marker_count": sum(s["daily_marker_present"] for s in day_summary)})
        rows = []
        for domain in domains:
            b = aggregate(backgrounds, domain, day, policy)
            t = aggregate(triggers, domain, day, policy)
            c = aggregate(signals, domain, day, policy)
            relevant = [s for s in active if s.domain_support.get(domain, 0) > 0]
            marker_ids = [s.signal_id for s in relevant if marker(s, day, tz)["daily_marker_present"]]
            trigger_present = bool(t["trigger_ids"])
            band = "background_only" if not trigger_present else "strong_support" if c["score"] >= policy["qualification_score"] else "moderate_support" if c["score"] >= policy["threshold_exit"] else "weak_trigger_support"
            rows.append({"domain": domain, "background_score": b["score"], "trigger_score": t["score"],
                "combined_score": c["score"], "trigger_present": trigger_present,
                "daily_marker_present": bool(marker_ids), "daily_marker_signal_ids": marker_ids,
                "signal_band": band, "background_evidence_ids": b["evidence_ids"],
                "trigger_evidence_ids": t["evidence_ids"], "counterevidence_ids": c["counterevidence_ids"]})
        rows.sort(key=lambda r: (-r["trigger_score"], -r["combined_score"], r["domain"]))
        scores = sorted([r["trigger_score"] for r in rows if r["trigger_score"] > 0], reverse=True)
        gap = scores[0] - scores[1] if len(scores) > 1 else scores[0] if scores else 0.0
        total = sum(scores)
        entropy = -sum((s / total) * log(s / total) for s in scores) / log(len(scores)) if len(scores) > 1 else 0
        specificity = 1 - entropy if scores else 0.0
        confidence = "insufficient_data" if sensitivity.get("stability") is None else "no_trigger" if not scores else "ambiguous" if gap < policy["ambiguity_margin"] else "distinct_domain_support"
        profiles.append({"day": day.isoformat(), "domains": rows,
            "dominance_gap": round(gap, 6), "specificity_score": round(specificity, 6),
            "specificity_definition": "1 minus normalized entropy of nonzero trigger scores; not event-identification accuracy",
            "interpretation_confidence": confidence, "interpretation_probability": None})
        day += timedelta(days=1)
    return profiles, summary


def enrich_ranking(ranking, profiles):
    by_day = {p["day"]: {r["domain"]: r for r in p["domains"]} for p in profiles}
    for row in ranking:
        d = row["domain"]
        selected = by_day.get(row["score_comparison_day"], {}).get(d)
        values = [p["domains"] for p in profiles]
        trigger_peak = max((r for rs in values for r in rs if r["domain"] == d), key=lambda r: r["trigger_score"], default=None)
        row.update({k: selected[k] if selected else False if k.endswith("present") else 0.0
                    for k in ["background_score", "trigger_score", "combined_score", "trigger_present", "daily_marker_present"]})
        row["peak_trigger_score"] = trigger_peak["trigger_score"] if trigger_peak else 0.0
        row["trigger_score_basis"] = "active timing support, possibly a long slow transit; not evidence of an event that day"


def daily_reading(profile, request, policy, limit):
    if not limit: return []
    rows = [r for r in profile["domains"] if r["trigger_score"] > 0]
    if not rows: return []
    top = rows[0]["trigger_score"]
    near = [r for r in rows if top - r["trigger_score"] <= policy["ambiguity_margin"] + 1e-9]
    names = " / ".join(NAMES.get(r["domain"], r["domain"]) for r in near)
    return [{"forecast_id": "daily-profile-" + profile["day"], "kind": "interpretation_not_event_confirmation",
        "forecast_status": "insufficient-data" if profile["interpretation_confidence"] == "insufficient_data" else "ambiguous" if len(near) > 1 else "candidate",
        "title": names, "domains": [{"domain": r["domain"], "label": NAMES.get(r["domain"], r["domain"]),
                                     "support_score": r["trigger_score"], "example": None} for r in near],
        "trigger_interval": {"start": profile["day"], "end": profile["day"]}, "peak_interval": None,
        "summary": f"في {profile['day']}: التريغرز النشطة تميل إلى {names}. قد تمتد هذه الاتصالات أيامًا أو أسابيع؛ لا تستنتج القراءة حدثًا وقع في هذا اليوم أو نوعه.",
        "basis": "trigger_only; background excluded from narrative selection", "background_context": sorted(
            [{"domain": r["domain"], "background_score": r["background_score"], "context_only": True} for r in profile["domains"] if r["background_score"] > 0],
            key=lambda r: (-r["background_score"], r["domain"])),
        "notes": ["الخلفية سياق فقط.", "الدرجة ليست احتمال حدوث.", "غياب نوع الحدث لا يعني غياب الحدث الحقيقي."],
        "evidence_ids": sorted({s for r in near for s in r["trigger_evidence_ids"]}),
        "context_used": request.mode == "context_assisted", "occurrence_probability": None,
        "presentation_version": "arabic-daily-triggers-1", "dominance_gap": profile["dominance_gap"],
        "specificity_score": profile["specificity_score"], "interpretation_confidence": profile["interpretation_confidence"]}]
