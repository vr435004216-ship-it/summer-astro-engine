"""Nearby-day controls measure numerical unusualness, not event accuracy."""
from datetime import timedelta
import random
from statistics import mean, pstdev


def controls_report(engine, request, selected_profile):
    options = request.negative_controls
    days = [request.start + timedelta(days=i) for i in range(-options.radius_days, options.radius_days + 1)
            if i != 0 and request.birth.date <= request.start + timedelta(days=i) and (request.start + timedelta(days=i)).year <= 2098]
    if len(days) < options.sample_count: raise ValueError("not enough eligible baseline days")
    days = sorted(random.Random(options.seed).sample(days, options.sample_count))
    rows = []
    for day in days:
        value = request.model_dump(mode="json")
        value.update(start=day.isoformat(), end=day.isoformat(), negative_controls=None, max_display=0)
        result = engine.forecast(value)
        rows.append({"day": day.isoformat(), "run_id": result["run_id"], "profile": result["daily_domain_profiles"][0]})
    by_day = [{r["domain"]: r for r in x["profile"]["domains"]} for x in rows]
    output = []
    for selected in selected_profile["domains"]:
        comparisons = {}
        for key in ["background_score", "trigger_score", "combined_score"]:
            values = [r[selected["domain"]][key] for r in by_day]
            avg = mean(values); std = pstdev(values); score = selected[key]
            percentile = (sum(v < score for v in values) + .5 * sum(v == score for v in values)) / len(values) * 100
            comparisons[key] = {"selected_score": score, "baseline_mean": round(avg, 6), "baseline_std": round(std, 6),
                "z_score": round((score - avg) / std, 6) if std > 1e-9 else None,
                "percentile": round(percentile, 3), "numerically_unusual": std > 1e-9 and percentile >= 95}
        output.append({"domain": selected["domain"], **comparisons})
    return {"selected_day": request.start.isoformat(), "sample_count": len(days), "seed": options.seed,
        "radius_days": options.radius_days, "baseline_days": [r["day"] for r in rows],
        "baseline_run_ids": [r["run_id"] for r in rows], "domains": output,
        "baseline_event_labels": "unknown; these days have not been certified ordinary",
        "status": "exploratory_nearby_day_controls", "false_positive_rate": None,
        "interpretation": "Unusual numerical support is not evidence that an event occurred. Nearby slow transits are autocorrelated; percentiles are exploratory and not calibrated probabilities."}
