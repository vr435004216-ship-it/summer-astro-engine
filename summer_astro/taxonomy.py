"""Event labels are independent targets, never synonyms for house activations."""
EVENT_TYPES = {
    "purchase", "vehicle_event", "vehicle_purchase", "vehicle_delivery", "vehicle_maintenance",
    "vehicle_accident", "vehicle_registration_insurance", "property_event", "travel_departure",
    "travel_return", "social_gathering", "bereavement", "funeral", "condolence", "loss",
    "job_start", "work_milestone", "relationship_contact", "relationship_withdrawal",
    "medical_event", "family_event", "financial_transaction", "unknown"
}
SUBTYPES = {
    "withdrawal": ["social_withdrawal", "emotional_withdrawal", "physical_retreat", "communication_reduction", "relational_distance"],
    "self": ["self_focus", "identity_reassessment", "personal_decision", "boundary_setting", "self_presentation", "autonomy"],
    "financial": ["financial_intent", "purchase_commitment", "actual_transaction", "cash_outflow", "income_inflow"],
    "travel": ["travel_long", "border_crossing", "flight", "road_trip", "travel_short", "local_movement"],
    "relationship": ["renewed_contact", "ordinary_contact", "emotional_contact", "sexual_contact", "romantic_contact", "conflict", "distancing", "reconciliation"]
}
ALL_SUBTYPES = {s for values in SUBTYPES.values() for s in values}
TYPE_DOMAINS = {
    "purchase": ["cashflow"], "financial_transaction": ["cashflow"],
    "vehicle_event": ["vehicle"], "vehicle_purchase": ["vehicle"], "vehicle_delivery": ["vehicle"],
    "vehicle_maintenance": ["vehicle"], "vehicle_accident": ["vehicle"], "vehicle_registration_insurance": ["vehicle"],
    "property_event": ["property"], "travel_departure": ["travel_short", "travel_long"],
    "travel_return": ["travel_short", "travel_long"], "social_gathering": ["networks", "friendship"],
    "job_start": ["career_role"], "work_milestone": ["career_role", "career_status"],
    "relationship_contact": ["communication"], "relationship_withdrawal": ["withdrawal"],
    "medical_event": ["health"], "family_event": ["family"],
    "bereavement": ["loss"], "funeral": ["loss"], "condolence": ["loss"], "loss": ["loss"]
}


def classify_events(request, candidates):
    supplied = [{"fact_id": f.fact_id, "subject_id": f.subject_id, "event_type": f.event_type,
                 "subtypes": f.subtypes, "primary_domain": f.primary_domain,
                 "participant_roles": f.participant_roles, "family_is_subject": f.family_is_subject,
                 "provenance": "user_context_not_blind_prediction", "status": "supplied",
                 "start": f.start.isoformat(), "end": f.end.isoformat()}
                for f in request.context if (f.event_type != "unknown" or f.subtypes) and f.start <= request.end and f.end >= request.start]
    return {"status": "context_supplied" if supplied else "insufficient_specific_evidence",
            "primary_event_type": "unknown", "astrology_only_event_types": [],
            "context_supplied_events": supplied, "occurrence_probability": None,
            "reason": "No validated event-type rules exist in this release; domain activation does not identify an event subtype.",
            "taxonomy": sorted(EVENT_TYPES), "subtype_taxonomy": SUBTYPES,
            "candidate_event_types": [{"forecast_id": c["forecast_id"], "event_type": "unknown",
                                       "qualification_status": "insufficient_specific_evidence"} for c in candidates],
            "detection_coverage": {"vehicle": "context_labels_only; no validated astrological detector",
                                   "loss": "context_labels_only; no astrological death prediction",
                                   "financial_stage": "unknown_without_explicit_stage_evidence"}}
