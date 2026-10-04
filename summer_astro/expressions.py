"""Read-only expression diagnostics. Generic axes cannot identify literal events.

No outcome labels, dates, subjects or learned case-specific weights enter this
layer. Candidate vocabulary is never reported as a detected subtype.
"""
from datetime import date
from .taxonomy import SUBTYPES

VERSION = "expressions-1"
GROUP = {"partnership": "relationship", "marriage": "relationship", "romance": "relationship",
         "withdrawal": "withdrawal", "self": "self", "work_routine": "work",
         "family": "family", "communication": "communication"}
MEANING = {
    "self": "موقف شخصي أو قرار أو حدود أو استقلال أو مراجعة للهوية؛ نوع التعبير غير محسوم.",
    "withdrawal": "قد يكون معالجة داخلية أو تحفظًا أو تقليل انفتاح، وقد يكون ابتعادًا خارجيًا؛ الحسابات لا تميز بينهما هنا.",
    "partnership": "تفعيل علاقة أو شراكة؛ نوع التواصل أو القرب أو الخلاف غير محسوم.",
    "marriage": "تفعيل محور ارتباط؛ لا يحدد شكل الحدث.",
    "romance": "تفعيل محور عاطفي؛ لا يثبت تواصلًا رومانسيًا أو حميميًا بعينه.",
    "shared_resources": "موارد مشتركة أو التزام مالي أو تبادل ملموس؛ لا يُستنتج منه اتصال حميمي وحده.",
    "work_routine": "دعم عملي للروتين وسير العمل؛ العودة للدوام أو نوع التعطل يحتاج دليلًا أخص.",
    "communication": "لا يميز هذا الدعم وحده بين الكلام كوسيلة والكلام الذي يمثل الحدث نفسه.",
    "family": "محور الأسرة؛ التجمع أو الوجبة أو إعادة التواصل أنواع تحتاج دليلًا أخص."
}


def expression_views(profiles, signals, request):
    """Return a separate layer without mutating scores, signals or qualification.

    Constraint/activity are inherited generic axes, not new subtype scores.
    Even simultaneous relationship/resources support cannot select intimacy:
    current primitives lack expression-specific evidence. Context stays separate.
    """
    by_id = {s.signal_id: s for s in signals}
    output = []
    for profile in profiles:
        rows = []
        for r in profile["domains"]:
            d = r["domain"]
            if d not in MEANING: continue
            relevant = [by_id[i] for i in r["trigger_evidence_ids"] if i in by_id]
            active = bool(relevant)
            group = GROUP.get(d)
            alternatives = list(SUBTYPES.get(group, []))
            # A resource domain can retain its primary meaning but cannot supply
            # relationship expressions or automatically create a carrier link.
            unknown = "unknown_relationship_expression" if group == "relationship" else "unknown_expression"
            axes = {k: max((s.axes.get(k, 0) for s in relevant), default=0)
                    for k in ["constraint", "activity"]}
            modifiers = []
            if d == "work_routine" and active and axes["constraint"] > 0:
                modifiers.append({"modifier": "constraint", "rule_id": "EXPR-WORK-CONSTRAINT-1",
                    "status": "generic_axis_support_not_event_detection",
                    "evidence_ids": sorted(s.signal_id for s in relevant if s.axes.get("constraint", 0) > 0),
                    "summary": "يوجد دعم عملي مع محور تقييد؛ قد يظهر كاحتكاك في سير الروتين، لكن نوع التعطل غير محدد."})
            rows.append({"domain": d, "expression_type": unknown,
                "qualification_status": "insufficient_specific_evidence" if active else "no_daily_support",
                "internal_vs_external": "unknown", "interpersonal_vs_practical": "unknown",
                "domain_context": "practical" if d == "work_routine" else "interpersonal" if group == "relationship" else "unknown",
                "event_salience": None, "event_salience_status": "not_inferred_from_domain_score",
                "carrier_domain": None, "carrier_status": "not_identified",
                "candidate_expressions": alternatives,
                "candidate_expression_status": "vocabulary_only_not_predictions",
                "detected_subtypes": [], "interpretation_confidence": "insufficient_specific_evidence",
                "evidence_ids": sorted(r["trigger_evidence_ids"]),
                "source_dependency_groups": sorted({s.dependency_group for s in relevant}),
                "generic_axes": axes, "supported_modifiers": modifiers,
                "reason": "Generic domain/axis evidence does not discriminate these literal expressions.",
                "summary": MEANING[d] if active else "لا يوجد دعم يومي لهذا المجال؛ لا يُختلق نوع حدث لتعويض الغياب."})
        facts = [{"fact_id": f.fact_id, "primary_domain": f.primary_domain,
                  "expression_types": f.subtypes, "provenance": "user_context_not_blind_prediction"}
                 for f in request.context if f.start <= date.fromisoformat(profile["day"]) <= f.end and f.subtypes]
        output.append({"day": profile["day"], "version": VERSION, "domains": rows,
                       "context_supplied_expressions": facts,
                       "score_mutation": False, "occurrence_probability": None,
                       "intimacy_guard": {"status": "insufficient_expression_specific_evidence",
                           "requires": ["relationship_specific_evidence", "intimacy_specific_evidence",
                                        "independent_primitives", "same_subject_and_timing"],
                           "resources_alone_are_insufficient": True,
                           "coactivation_alone_is_insufficient": True},
                       "communication_policy": "carrier presence does not activate communication; a shift/decision/conflict needs specific evidence",
                       "coverage_status": "literal subtypes not yet discriminated by existing astronomical primitives"})
    return output


def attach_reading_expressions(readings, views):
    """Presentation-only enrichment; retain top domains, scores and evidence."""
    by_day = {v["day"]: v for v in views}
    for reading in readings:
        start, end = reading["trigger_interval"]["start"], reading["trigger_interval"]["end"]
        chosen = [v for day, v in by_day.items() if start <= day <= end]
        reading["event_expression"] = chosen
        if reading.get("kind") != "interpretation_not_event_confirmation": continue
        selected = {r["domain"] for r in reading["domains"]}
        notes = [r["summary"] for v in chosen for r in v["domains"] if r["domain"] in selected and r["evidence_ids"]]
        reading["expression_notes"] = list(dict.fromkeys(notes))
        practical = [r for v in chosen for r in v["domains"] if r["domain"] == "work_routine" and r["evidence_ids"]]
        reading["practical_parallel_support"] = practical
        reading["summary"] += " " + " ".join(reading["expression_notes"])
        if practical and "work_routine" not in selected:
            work = practical[0]
            reading["summary"] += " ويوجد دعم موازٍ للروتين العملي: " + (
                work["supported_modifiers"][0]["summary"] if work["supported_modifiers"] else work["summary"])
        reading["presentation_version"] = "arabic-expressions-1"
