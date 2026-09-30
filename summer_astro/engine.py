from pathlib import Path
from datetime import datetime, timezone
import json
import importlib.metadata
from .contracts import ForecastRequest, digest
from .astronomy import birth_bundle
from .signals import build_signals
from .reasoning import window_engine, resolve
from . import __version__
from .readings import build_readings
from .diagnostics import diagnostic_views
from .temporal import daily_views, enrich_ranking, daily_reading
from .taxonomy import classify_events

POLICY_PATH=Path(__file__).parent/"policy.json"

def load_policy():
    return json.loads(POLICY_PATH.read_text())

class SummerEngine:
    def __init__(self,store=None,policy=None):
        self.store=store
        self.policy=policy or load_policy()
        self.code_hash=digest({p.name:p.read_text() for p in sorted(Path(__file__).parent.glob("*.py"))})

    def forecast(self,request):
        if not isinstance(request,ForecastRequest): request=ForecastRequest.model_validate(request)
        if self.policy["probability_enabled"] or self.policy["personal_ml_enabled"]:
            raise ValueError("this release has no validated probability/personal ML artifact")
        bundle=birth_bundle(request.birth,self.policy["dasha_year_days"])
        signals=build_signals(request,bundle,self.policy)
        windows,timeline=window_engine(signals,request.start,request.end,self.policy)
        candidates=resolve(windows,signals,bundle["sensitivity"],request,self.policy)
        raw_signals,domain_ranking=diagnostic_views(signals,timeline,windows,candidates,self.policy)
        profiles,trigger_summary=daily_views(signals,request,self.policy,bundle["sensitivity"])
        for profile in profiles:
            for row in profile["domains"]:
                row["qualified_event_present"]=any(c["status"]=="qualified" and c["primary_domain"]==row["domain"] and
                    c["trigger_interval"]["start"]<=profile["day"]<=c["trigger_interval"]["end"] for c in candidates)
                if row["signal_band"]=="strong_support" and not row["qualified_event_present"]:
                    row["signal_band"]="strong_support_but_unqualified"
        enrich_ranking(domain_ranking,profiles)
        event_types=classify_events(request,candidates)
        qualified=[c for c in candidates if c["status"]=="qualified"]
        ranked=sorted(qualified,key=lambda c:(-c["activation_score"],-c["personal_relevance"],c["forecast_id"]))
        displayed=ranked[:request.max_display]
        # Display preference is excluded from computational run identity.
        request_data=request.model_dump(mode="json")
        computation={k:v for k,v in request_data.items() if k not in {"max_display","personal_relevance","negative_controls"}}
        tz_version=importlib.metadata.version("tzdata")
        run_id=digest({"request":computation,"policy":self.policy,"engine":__version__,
            "ephemeris":bundle["ephemeris_manifest_hash"],"ephemeris_version":bundle["ephemeris_version"],
            "tzdata":tz_version,"code_hash":self.code_hash})[:32]
        core={"schema_version":"2.0","engine_version":__version__,"run_id":run_id,
            "as_of":request.as_of.isoformat(),"mode":request.mode,"input_hash":digest(computation),
            "evaluation_timezone":request.birth.timezone,
            "policy_version":self.policy["version"],"policy_hash":digest(self.policy),
            "code_hash":self.code_hash,
            "model_version":self.policy["model_version"],"timezone_database_version":tz_version,
            "status":"qualified-forecasts" if qualified else "no-qualified-forecast",
            "forecast_kind":"prospective" if request.start>=request.as_of.astimezone(request.birth.instant().tzinfo).date() else "retrospective-development",
            "release_status":"experimental-unvalidated","birth_calculations":bundle,
            "raw_signals":raw_signals,"domain_ranking":domain_ranking,"raw_windows":windows,
            "daily_domain_profiles":profiles,"daily_trigger_summary":trigger_summary,
            "event_type_classification":event_types,
            "all_candidates":[{**c,"personal_relevance":.5} for c in candidates],
            "daily_activation":timeline,
            "diagnostics":{"signal_count":len(signals),"window_count":len(windows),
                "candidate_count":len(candidates),"qualified_count":len(qualified),
                "abstention_count":sum(c["status"] in {"ambiguous","insufficient-data"} for c in candidates),
                "family_coverage":{f:f not in request.exclude_families for f in self.policy["family_weights"]},
                "excluded_families":request.exclude_families,"probability_available":False,
                "expected_layers":list(self.policy["family_weights"]),
                "missing_data_is_not_zero":True},
            "qualification_policy":{k:self.policy[k] for k in ["threshold_enter","threshold_exit","qualification_score","ambiguity_margin","min_input_stability"]}}
        readings=build_readings(candidates,request.max_display,self.policy['ambiguity_margin'],self.policy['qualification_score'])
        if request.start==request.end:
            readings=daily_reading(profiles[0],request,self.policy,request.max_display)
        # Immutable computational record is independent of presentation cap/relevance.
        if self.store: self.store.append(run_id,"forecast",request.as_of.isoformat(),core)
        controls=None
        if request.negative_controls:
            from .controls import controls_report
            controls=controls_report(SummerEngine(policy=self.policy),request,profiles[0])
            if self.store:
                self.store.append("controls-"+digest({"run_id":run_id,"options":request.negative_controls.model_dump()})[:32],
                    "negative_control",request.as_of.isoformat(),{"run_id":run_id,"report":controls})
        return {**core,"negative_controls":controls,"displayed_events":displayed,"display_count":len(displayed),
            "max_display":request.max_display,"reading_status":"readings-available" if readings else "no-active-windows",
            "displayed_readings":readings,"reading_count":len(readings),
            "text_output":[{"forecast_id":r["forecast_id"],"text":r["summary"]} for r in readings]}
