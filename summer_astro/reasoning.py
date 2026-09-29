from __future__ import annotations
from datetime import date, timedelta
from .contracts import EventOutput, digest

def unique_signals(signals):
    out={}
    for s in signals:
        if s.signal_id in out and s.to_dict()!=out[s.signal_id].to_dict():
            raise ValueError("duplicate signal ID with conflicting content")
        out[s.signal_id]=s
    return list(out.values())

def strength_on(signal, day):
    return signal.metadata.get("daily_strength",{}).get(day.isoformat(),signal.strength)

def aggregate(signals, domain, day, policy):
    """Conservative max within source family; shared primitives cannot add twice.

    No independence claim. Missing weights are never renormalized.
    """
    active=[s for s in unique_signals(signals) if s.active(day)]
    components=[]
    for signal in active:
        primitives=set(signal.primitive_ids)
        touched=[g for g in components if primitives & g[0] or signal.dependency_group in g[1]]
        members=[signal]
        deps={signal.dependency_group}
        for g in touched:
            primitives|=g[0];deps|=g[1];members+=g[2];components.remove(g)
        components.append([primitives,deps,members])
    family_contributions={};family_penalties={};evidence=[];negative=[]
    for primitives,deps,members in components:
        choices=[]
        for s in members:
            pos=s.domain_support.get(domain,0)*strength_on(s,day)
            neg=(s.negative_support or {}).get(domain,0)*strength_on(s,day)
            weight=1. if s.family=="context" and s.metadata.get("role")=="core" else policy["family_weights"].get(s.family,0)
            choices.append((pos*weight,s.family,s.signal_id))
            family_penalties[s.family]=max(family_penalties.get(s.family,0),neg*weight)
            if pos: evidence.append(s.signal_id)
            if neg: negative.append(s.signal_id)
        if choices:
            value,family,signal_id=max(choices)
            family_contributions[family]=max(family_contributions.get(family,0),value)
    # Context observations must not masquerade as extra astrological corroboration.
    family_contributions={k:max(0,v-family_penalties.get(k,0)) for k,v in family_contributions.items()}
    context=family_contributions.get("context",0)
    astrological=sum(v for k,v in family_contributions.items() if k!="context")
    score=max(context,astrological)
    trigger=[s for s in active if s.metadata.get("temporal_role")=="trigger" and
        s.domain_support.get(domain,0)>0 and not (s.family=="context" and s.metadata.get("role")=="secondary")]
    return {"score":round(min(1,score),6),"families":family_contributions,
        "evidence_ids":sorted(set(evidence)),"counterevidence_ids":sorted(set(negative)),
        "trigger_ids":sorted(s.signal_id for s in trigger)}

def window_engine(signals, start, end, policy):
    signals=unique_signals(signals)
    domains=sorted({d for s in signals for d in s.domain_support})
    windows=[];timeline={}
    for domain in domains:
        rows=[];cur=start
        while cur<=end:
            row=aggregate(signals,domain,cur,policy);row["day"]=cur.isoformat()
            rows.append(row);cur+=timedelta(days=1)
        timeline[domain]=rows
        current=[]
        def emit(chunk):
            if not chunk: return
            peak=max(chunk,key=lambda x:x["score"])
            evidence=sorted({x for r in chunk for x in r["evidence_ids"]})
            triggers=sorted({x for r in chunk for x in r["trigger_ids"]})
            body={"domain":domain,"start":chunk[0]["day"],"end":chunk[-1]["day"],"triggers":triggers}
            windows.append({"window_id":digest(body)[:24],**body,"score":peak["score"],
                "peak_day":peak["day"],"evidence_ids":evidence,
                "counterevidence_ids":sorted({x for r in chunk for x in r["counterevidence_ids"]}),
                "families":sorted({k for r in chunk for k,v in r["families"].items() if v>0})})
        for row in rows:
            valid=bool(row["trigger_ids"])
            threshold=policy["threshold_exit"] if current else policy["threshold_enter"]
            if valid and row["score"]>=threshold:
                current.append(row)
                if len(current)>=policy["max_episode_days"]: emit(current);current=[]
            elif current: emit(current);current=[]
        emit(current)
    return sorted(windows,key=lambda w:(w["start"],w["window_id"])),timeline

def overlap(a,b,gap=0):
    return not (date.fromisoformat(a["end"])+timedelta(days=gap)<date.fromisoformat(b["start"]) or
        date.fromisoformat(b["end"])+timedelta(days=gap)<date.fromisoformat(a["start"]))

def core_identity(window,lookup):
    identities={lookup[i].identity_key for i in window["triggers"] if lookup[i].identity_key is not None and
        lookup[i].metadata.get("role")=="core"}
    return next(iter(identities)) if len(identities)==1 else None

def merge_windows(windows,signals,policy):
    """Bounded complete-link grouping: all pairs must match, not just neighbors."""
    lookup={s.signal_id:s for s in signals}
    groups=[]
    for window in sorted(windows,key=lambda w:(w["start"],w["window_id"])):
        identity=core_identity(window,lookup)
        def compatible(group):
            lo=min([window["start"]]+[w["start"] for w in group]);hi=max([window["end"]]+[w["end"] for w in group])
            if (date.fromisoformat(hi)-date.fromisoformat(lo)).days+1>policy["max_episode_days"]: return False
            for other in group:
                if not overlap(window,other,policy["merge_gap_days"]): return False
                explicit=identity is not None and identity==core_identity(other,lookup)
                # Identical trigger set may carry competing domains of ONE signal.
                # Bundle as ambiguous hypotheses, never as a causal cross-domain event.
                same_trigger=bool(window["triggers"]) and window["triggers"]==other["triggers"]
                same_domain=window["domain"]==other["domain"] and bool(set(window["triggers"])&set(other["triggers"]))
                if not (explicit or same_trigger or same_domain): return False
            return True
        target=next((g for g in groups if compatible(g)),None)
        if target is None: groups.append([window])
        else: target.append(window)
    return groups

def infer_action(triggers):
    phases=[]
    for s in sorted(triggers,key=lambda x:(x.start,x.end,x.signal_id)):
        action=s.metadata.get("state_action","unknown")
        if action not in {"unknown","activation"} and s.identity_key:
            phases.append({"start":s.start,"end":s.end,"action":action,"subject_id":s.identity_key,"evidence_id":s.signal_id})
    if not phases: return ["activation"],"unknown",[]
    actions=sorted({p["action"] for p in phases})
    for a in phases:
        for b in phases:
            if a["action"]=="exit" and b["action"]=="entry" and a["end"]<b["start"] and a["subject_id"]==b["subject_id"]:
                return ["exit_then_entry"],"supported",phases
    if len(actions)>1: return actions,"mixed",phases
    return actions,"supported",phases

def resolve(windows,signals,sensitivity,request,policy):
    lookup={s.signal_id:s for s in signals}
    groups=merge_windows(windows,signals,policy)
    events=[]
    for group in groups:
        lo=min(w["start"] for w in group);hi=max(w["end"] for w in group)
        best=max(group,key=lambda w:w["score"])
        evidence_ids=sorted({i for w in group for i in w["evidence_ids"]})
        trigger_ids=sorted({i for w in group for i in w["triggers"]})
        triggers=[lookup[i] for i in trigger_ids]
        support={}
        # Compare competing domains at the same peak, before any single-domain selection.
        day=date.fromisoformat(best["peak_day"])
        for domain in sorted({d for i in evidence_ids for d in lookup[i].domain_support}):
            support[domain]=aggregate([lookup[i] for i in evidence_ids],domain,day,policy)["score"]
        ranked=sorted(support,key=lambda d:(-support[d],d))
        primary=ranked[0] if ranked else "unknown"
        margin=support[primary]-support[ranked[1]] if len(ranked)>1 else support.get(primary,0)
        explicit=[s for s in triggers if s.family=="context" and s.metadata.get("role")=="core"]
        if explicit:
            domains={next(iter(s.domain_support)) for s in explicit}
            if len(domains)==1: primary=next(iter(domains));margin=1.
        secondary=[]
        identities={s.identity_key for s in explicit}
        for s in signals:
            if s.family=="context" and s.metadata.get("role")=="secondary" and s.identity_key in identities and overlap({"start":s.start,"end":s.end},{"start":lo,"end":hi}):
                secondary.extend(s.domain_support)
                evidence_ids.append(s.signal_id)
        secondary=sorted(set(secondary)-{primary})
        actions,action_status,phases=infer_action(triggers)
        axis_keys={k for s in triggers for k in s.axes}
        axes={k:round(sum(s.axes.get(k,0)*s.strength for s in triggers)/max(1,sum(s.strength for s in triggers)),6) for k in axis_keys}
        counter=sorted({i for w in group for i in w["counterevidence_ids"]})
        # Axis conflict is recorded, not silently voted away.
        for k in axis_keys:
            positive=[s for s in triggers if s.axes.get(k,0)>.15]
            negative=[s for s in triggers if s.axes.get(k,0)<-.15]
            if positive and negative:
                counter+=sorted({s.signal_id for s in positive+negative});action_status="mixed"
        background=[lookup[i] for i in evidence_ids if lookup[i].metadata.get("temporal_role")=="background"]
        bg={"start":min(s.start for s in background),"end":max(s.end for s in background)} if background else None
        stability=sensitivity.get("stability")
        status="qualified";reason=None
        if best["score"]<policy["qualification_score"]:
            status="candidate";reason="below_qualification_threshold"
        if margin<policy["ambiguity_margin"]:
            status="ambiguous";reason="competing_domains_not_separated"
        if stability is None or stability<policy["min_input_stability"]:
            status="insufficient-data";reason="birth_time_uncertainty_unknown_or_sensitive"
        related=[]
        for other in windows:
            if other in group or not overlap(best,other): continue
            other_identity=core_identity(other,lookup)
            identity=core_identity(best,lookup)
            related.append({"window_id":other["window_id"],"merge":False,"separate":True,
                "reason":"no_shared_event_identity" if not identity or identity!=other_identity else "complete_link_or_span_guardrail"})
        alternatives=[{"primary_domain":d,"support_score":support[d],"probability":None} for d in ranked if d!=primary][:5]
        body={"window_ids":sorted(w["window_id"] for w in group),"policy":policy["version"],
            "subject":request.subject_key,"as_of":request.as_of.isoformat()}
        event=EventOutput(forecast_id=digest(body)[:32],status=status,event_class="domain_activation",
            core_process="context_supplied_event" if explicit else "unspecified_activity",
            primary_domain=primary,secondary_domains=secondary,action_candidates=actions,action_status=action_status,
            axes=axes,background_interval=bg,trigger_interval={"start":lo,"end":hi},
            peak_interval={"start":best["peak_day"],"end":best["peak_day"],"precision":"daily"},
            activation_score=best["score"],occurrence_probability=None,calibration_status="unvalidated",
            domain_support=support,domain_ambiguity=round(1-margin,6),input_stability=stability,
            data_quality="sensitivity_checked" if stability is not None else "uncertainty_missing",
            evidence_ids=sorted(set(evidence_ids)),counterevidence_ids=sorted(set(counter)),
            alternative_hypotheses=alternatives,hypothesis_comparisons=related,phases=phases,
            abstention_reason=reason,personal_relevance=request.personal_relevance.get(primary,.5),
            provenance="context_assisted" if explicit else "astrology",
            why=["Support is aggregated with capped dependent families; not an occurrence probability.",
                "Simultaneous domains remain alternatives unless event identity is explicit.",
                "Context supplied by the user is labeled and is not a blind prediction." if explicit else
                "Literal event subtype and action are withheld when unsupported."])
        events.append(event.model_dump())
    return sorted(events,key=lambda e:(e["trigger_interval"]["start"],e["forecast_id"]))

def render(events):
    # Deterministic template; no LLM can invent a subtype or action.
    return [{"forecast_id":e["forecast_id"],"text":f"{e['primary_domain']}: {e['trigger_interval']['start']} → {e['trigger_interval']['end']}; action={','.join(e['action_candidates'])}; status={e['status']}"} for e in events]
