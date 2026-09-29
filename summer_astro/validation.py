from __future__ import annotations
import random
from datetime import date, datetime, timedelta, timezone
from .contracts import DOMAINS, aware

def union_days(intervals):
    days=set()
    for interval in intervals:
        lo,hi=map(date.fromisoformat,(interval["start"],interval["end"]))
        while lo<=hi: days.add(lo);lo+=timedelta(days=1)
    return days

def overlap_days(a,b):
    lo=max(date.fromisoformat(a["start"]),date.fromisoformat(b["start"]))
    hi=min(date.fromisoformat(a["end"]),date.fromisoformat(b["end"]))
    return max(0,(hi-lo).days+1)

def maximum_matching(predictions,truth,eligible):
    edges={i:[j for j,t in enumerate(truth) if eligible(p,t)] for i,p in enumerate(predictions)}
    assigned={}
    def augment(i,visited):
        for j in edges[i]:
            if j in visited: continue
            visited.add(j)
            if j not in assigned or augment(assigned[j],visited):
                assigned[j]=i;return True
        return False
    for i in range(len(predictions)): augment(i,set())
    return sorted((i,j) for j,i in assigned.items())

def evaluate(records,truth,observed_intervals,evaluation_at,prospective_only=True,followup_days=7):
    evaluation_at=aware(datetime.fromisoformat(evaluation_at) if isinstance(evaluation_at,str) else evaluation_at)
    observed=union_days(observed_intervals)
    events=[];pending=0;excluded=0;all_candidates=0;abstained=0;earliest_issue=None
    seen=set()
    for record in records:
        payload=record["payload"]
        issued=aware(datetime.fromisoformat(record["recorded_at"]))
        if payload["mode"]!="astrology_only": excluded+=1;continue
        if issued>evaluation_at: excluded+=1;continue
        earliest_issue=min(earliest_issue,issued) if earliest_issue else issued
        for c in payload["all_candidates"]:
            all_candidates+=1
            if c["status"]!="qualified": abstained+=c["status"] in {"ambiguous","insufficient-data"};continue
            interval=c["trigger_interval"]
            if prospective_only and issued.date()>=date.fromisoformat(interval["start"]): excluded+=1;continue
            if date.fromisoformat(interval["end"])+timedelta(days=followup_days)>=evaluation_at.date(): pending+=1;continue
            if not union_days([interval])<=observed: excluded+=1;continue
            key=(c["primary_domain"],interval["start"],interval["end"],c["forecast_id"])
            if key not in seen: events.append(c);seen.add(key)
    eligible_truth=[]
    for t in truth:
        if t["primary_domain"] not in DOMAINS: raise ValueError("unknown truth domain")
        if date.fromisoformat(t["end"])<date.fromisoformat(t["start"]): raise ValueError("invalid truth interval")
        if not union_days([t])<=observed: continue
        if date.fromisoformat(t["end"])+timedelta(days=followup_days)>=evaluation_at.date(): continue
        if prospective_only and (t.get("development_only",False) or earliest_issue is None or earliest_issue.date()>=date.fromisoformat(t["start"])): continue
        eligible_truth.append(t)
    if len({t["event_id"] for t in eligible_truth})!=len(eligible_truth): raise ValueError("truth IDs must be unique")
    def eligible(p,t):
        return p["primary_domain"]==t["primary_domain"] and overlap_days(p["trigger_interval"],t)>0 and (
            t.get("event_class","domain_activation")==p["event_class"])
    matches=maximum_matching(events,eligible_truth,eligible)
    hits=len(matches);false=len(events)-hits;missed=len(eligible_truth)-hits
    durations=[(date.fromisoformat(e["trigger_interval"]["end"])-date.fromisoformat(e["trigger_interval"]["start"])).days+1 for e in events]
    errors=[];action_scored=0;action_hits=0
    for i,j in matches:
        t=eligible_truth[j];p=events[i]
        if t.get("peak_day"):
            errors.append(abs((date.fromisoformat(p["peak_interval"]["start"])-date.fromisoformat(t["peak_day"])).days))
        if t.get("action") and p["action_status"]=="supported":
            action_scored+=1;action_hits+=t["action"] in p["action_candidates"]
    return {"evaluation_kind":"prospective" if prospective_only else "development-only",
        "prediction_count":len(events),"truth_count":len(eligible_truth),"hits":hits,"false_alerts":false,"missed":missed,
        "precision":hits/len(events) if events else None,"recall":hits/len(eligible_truth) if eligible_truth else None,
        "false_alerts_per_30_observed_days":false*30/len(observed) if observed else None,
        "coverage_days":len(union_days([e["trigger_interval"] for e in events])),"observed_days":len(observed),
        "mean_window_days":sum(durations)/len(durations) if durations else None,
        "abstention_count":abstained,"candidate_count":all_candidates,
        "abstention_rate":abstained/all_candidates if all_candidates else None,
        "pending_count":pending,"excluded_count":excluded,
        "mean_peak_error_days":sum(errors)/len(errors) if errors else None,
        "action_scored_count":action_scored,"action_accuracy":action_hits/action_scored if action_scored else None,
        "calibration_metrics":None,"probability_status":"unvalidated; no probabilities emitted",
        "matches":[{"forecast_id":events[i]["forecast_id"],"event_id":eligible_truth[j]["event_id"]} for i,j in matches],
        "matching_policy":"maximum cardinality; one-to-one; exact primary domain and class; interval overlap",
        "observed_intervals_required":True}

def purged_temporal_split(rows,train_end,validation_end,calibration_end,test_end,gap_days=0):
    boundaries=list(map(date.fromisoformat,[train_end,validation_end,calibration_end,test_end]))
    if boundaries!=sorted(set(boundaries)): raise ValueError("split boundaries must strictly increase")
    partitions={k:[] for k in ["train","validation","calibration","test","purged"]}
    first=date.min
    for row in rows:
        lo,hi=map(date.fromisoformat,[row["start"],row["end"]])
        if hi<lo: raise ValueError("invalid row interval")
        lower=first;placed=False
        for name,upper in zip(["train","validation","calibration","test"],boundaries):
            if lo>=lower and hi<=upper:
                partitions[name].append(row);placed=True;break
            lower=upper+timedelta(days=gap_days+1)
        if not placed: partitions["purged"].append(row)
    # All rows of one real event remain in at most one partition.
    location={};conflict=set()
    for name in ["train","validation","calibration","test","purged"]:
        for row in partitions[name]:
            event=row.get("event_id")
            if event is not None and event in location and location[event]!=name: conflict.add(event)
            if event is not None: location[event]=name
    for name in ["train","validation","calibration","test"]:
        keep=[]
        for row in partitions[name]:
            if row.get("event_id") in conflict: partitions["purged"].append(row)
            else: keep.append(row)
        partitions[name]=keep
    return partitions

def matched_random_baseline(events,start,end,seed=17,seasonal=True):
    """Preserve count, primary label and exact length; constrain start to same month.
    Long windows outside the requested horizon are rejected, never shortened.
    """
    start,end=map(date.fromisoformat,[start,end]);rng=random.Random(seed);result=[]
    for event in events:
        a=event["trigger_interval"]
        n=(date.fromisoformat(a["end"])-date.fromisoformat(a["start"])).days
        options=[];day=start
        while day+timedelta(days=n)<=end:
            if not seasonal or day.month==date.fromisoformat(a["start"]).month: options.append(day)
            day+=timedelta(days=1)
        if not options: raise ValueError("baseline horizon cannot preserve this window and season")
        day=rng.choice(options)
        result.append({**event,"trigger_interval":{"start":day.isoformat(),"end":(day+timedelta(days=n)).isoformat()},
            "forecast_id":f"baseline-{seed}-{len(result)}"})
    return result

def ablation(engine,request):
    from .contracts import ForecastRequest
    req=ForecastRequest.model_validate(request)
    runs={"full":engine.forecast(req)}
    for family in engine.policy["family_weights"]:
        value=req.model_dump(mode="json")
        value["exclude_families"]=sorted(set(req.exclude_families+[family]))
        runs["without_"+family]=engine.forecast(value)
    return {name:{"run_id":r["run_id"],"all_candidates":r["all_candidates"],"diagnostics":r["diagnostics"]} for name,r in runs.items()}
