from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from .astronomy import (ASPECTS, VIM_SEQ, VIM_YEARS, angle, house, jd, pos,
    from_jd, chart_at, dasha_anchor, solar_return)
from .contracts import digest

@dataclass
class Signal:
    signal_id: str
    family: str
    framework: str
    dependency_group: str
    primitive_ids: list[str]
    rule_ids: list[str]
    start: str
    end: str
    strength: float
    domain_support: dict[str,float]
    axes: dict[str,float]
    metadata: dict
    subject_id: str | None = None
    identity_key: str | None = None
    negative_support: dict[str,float] | None = None

    def active(self, day):
        return self.start <= day.isoformat() <= self.end

    def to_dict(self):
        return asdict(self)

def make_signal(family, framework, group, primitive, rule, start, end, strength, support,
                axes=None, metadata=None, subject_id=None, identity_key=None, negative=None):
    body={"family":family,"framework":framework,"group":group,"primitive":primitive,
        "rule":rule,"start":str(start),"end":str(end),"metadata":metadata or {}}
    return Signal(digest(body)[:24],family,framework,group,primitive,[rule],str(start),str(end),
        strength,dict(support),axes or {},metadata or {},subject_id,identity_key,negative or {})

def birthday(year, dob):
    try: return dob.replace(year=year)
    except ValueError: return date(year,2,28)

def support_for_houses(houses, policy):
    out={}
    for h in houses:
        for domain,value in policy["house_support"][str(h)].items():
            out[domain]=max(out.get(domain,0),value)
    return out

def profections(request, chart, policy):
    signals=[]
    for year in range(max(request.birth.date.year,request.start.year-1),request.end.year+1):
        start=birthday(year,request.birth.date)
        end=birthday(year+1,request.birth.date)-timedelta(days=1)
        if end<request.start or start>request.end: continue
        age=year-request.birth.date.year
        h=age%12+1
        lord=chart["rulers"][str(h)]
        related={h,chart["planets"][lord]["house"]}
        related|={int(hh) for hh,r in chart["rulers"].items() if r==lord}
        support=support_for_houses(related,policy)
        signals.append(make_signal("profection","tropical",f"profection:{year}",
            [f"birth:{chart['instant_utc']}",f"profection:{year}"],"PROFECTION-1",start,end,.82,support,
            metadata={"lord":lord,"activated_house":h,"age":age,"temporal_role":"background"}))
    return signals

def dasha_intervals(sidereal, instant, start, end, year_days):
    birth_lord,anchor=dasha_anchor(sidereal,instant,year_days)
    idx=VIM_SEQ.index(birth_lord)
    current=anchor
    requested_start=datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc)-timedelta(days=2)
    requested_end=datetime.combine(end+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc)+timedelta(days=2)
    i=0
    while current<requested_end:
        md=VIM_SEQ[(idx+i)%9]
        md_end=current+timedelta(days=VIM_YEARS[md]*year_days)
        if md_end>requested_start:
            yield "MD",[md],current,md_end
            ad_start=current
            for j in range(9):
                ad=VIM_SEQ[(VIM_SEQ.index(md)+j)%9]
                ad_days=VIM_YEARS[md]*year_days*VIM_YEARS[ad]/120
                ad_end=ad_start+timedelta(days=ad_days)
                if ad_end>requested_start and ad_start<requested_end:
                    yield "AD",[md,ad],ad_start,ad_end
                    pd_start=ad_start
                    for k in range(9):
                        pd=VIM_SEQ[(VIM_SEQ.index(ad)+k)%9]
                        pd_end=pd_start+timedelta(days=ad_days*VIM_YEARS[pd]/120)
                        if pd_end>requested_start and pd_start<requested_end:
                            yield "PD",[md,ad,pd],pd_start,pd_end
                        pd_start=pd_end
                ad_start=ad_end
        current=md_end;i+=1

def dashas(request, chart, policy):
    signals=[]
    for level,lords,start,end in dasha_intervals(chart,request.birth.instant(),request.start,request.end,policy["dasha_year_days"]):
        local_start=start.astimezone(request.birth.instant().tzinfo).date()
        local_end=(end-timedelta(microseconds=1)).astimezone(request.birth.instant().tzinfo).date()
        if local_end<request.start or local_start>request.end: continue
        houses={chart["planets"][lord]["house"] for lord in lords}
        houses|={int(h) for h,lord in chart["rulers"].items() if lord in lords}
        signals.append(make_signal("dasha","sidereal_lahiri","vimshottari-natal-moon",
            ["natal-moon:"+str(round(chart["planets"]["Moon"]["longitude"],8))],"DASHA-1",
            local_start,local_end,{"MD":.58,"AD":.76,"PD":.88}[level],support_for_houses(houses,policy),
            metadata={"level":level,"lords":lords,"start_exact":start.isoformat(),"end_exclusive":end.isoformat(),
                "year_days":policy["dasha_year_days"],"temporal_role":"background",
                "boundary_is_not_an_event":True}))
    return signals

def returns(request, natal, policy):
    signals=[]
    for year in range(request.start.year-1,request.end.year+1):
        value=solar_return(natal,year,request.birth)
        next_value=solar_return(natal,year+1,request.birth)
        start=from_jd(value).astimezone(request.birth.instant().tzinfo).date()
        end=(from_jd(next_value)-timedelta(microseconds=1)).astimezone(request.birth.instant().tzinfo).date()
        if end<request.start or start>request.end: continue
        c=chart_at(from_jd(value),request.birth)
        houses={c["planets"]["Sun"]["house"],c["planets"]["Moon"]["house"],
            house(c["asc"],natal["asc"]),house(c["mc"],natal["asc"])}
        signals.append(make_signal("solar_return","tropical",f"solar-return:{year}",
            [f"solar-return:{year}","natal-sun:"+str(natal["planets"]["Sun"]["longitude"])],"SR-1",
            start,end,.72,support_for_houses(houses,policy),metadata={"year":year,
                "return_exact":from_jd(value).isoformat(),"location":"birth_location",
                "temporal_role":"background","house_evidence":sorted(houses)}))
    return signals

def transit_axes(planet, aspect):
    # Interpretive dimensions, not literal actions or calibrated valence.
    axes={"activity":.7,"resource_change":0.,"constraint":0.,"stability_change":0.}
    if planet=="Jupiter": axes["resource_change"]=.5
    if planet=="Saturn": axes["constraint"]=.65
    if planet in {"Uranus","Pluto"}: axes["stability_change"]=-.6
    if planet=="Neptune": axes["stability_change"]=-.4
    if aspect in {"square","opposition"}: axes["constraint"]+=.2
    return axes

def transits(request, natal, policy):
    targets={n:p["longitude"] for n,p in natal["planets"].items() if n not in {"Rahu","Ketu"}}
    targets.update(Ascendant=natal["asc"],Midheaven=natal["mc"])
    active={}
    cur=request.start
    while cur<=request.end:
        value=jd(datetime.combine(cur,datetime.min.time(),tzinfo=timezone.utc)+timedelta(hours=12))
        p=pos(value)
        for planet,orb in policy["transit_orbs"].items():
            for target,lon in targets.items():
                separation=angle(p[planet][0],lon)
                for aspect,deg in ASPECTS.items():
                    error=abs(separation-deg)
                    if error<=orb:
                        active.setdefault((planet,target,aspect),[]).append((cur,error,value,p[planet][0]))
        cur+=timedelta(days=1)
    result=[]
    for (planet,target,aspect),samples in sorted(active.items()):
        groups=[]
        for sample in samples:
            if not groups or (sample[0]-groups[-1][-1][0]).days>1: groups.append([])
            groups[-1].append(sample)
        if target=="Midheaven": support={"career_status":.95,"career_role":.75}
        elif target=="Ascendant": support={"self":.9}
        else:
            houses={natal["planets"][target]["house"]}
            houses|={int(h) for h,lord in natal["rulers"].items() if lord==target}
            support=support_for_houses(houses,policy)
        for group in groups:
            peak=min(group,key=lambda x:x[1])
            orb=policy["transit_orbs"][planet]
            daily={d.isoformat():round(policy["transit_base"][planet]*(.75+.25*(1-error/orb)),6) for d,error,_,_ in group}
            exact=[]
            for left,right in zip(group,group[1:]):
                deg=ASPECTS[aspect]
                exact_lon=min([(targets[target]+deg)%360,(targets[target]-deg)%360],key=lambda x:angle(x,left[3]))
                def residual(value): return (pos(value)[planet][0]-exact_lon+180)%360-180
                lo,hi=left[2],right[2];a,b=residual(lo),residual(hi)
                if a*b<=0 and abs(a-b)<180:
                    for _ in range(30):
                        mid=(lo+hi)/2;c=residual(mid)
                        if a*c<=0: hi=mid
                        else: lo=mid;a=c
                    exact.append(from_jd((lo+hi)/2).isoformat())
            primitive=f"transit:{planet}:{target}:{aspect}"
            result.append(make_signal("transit","tropical",primitive,[primitive],"TRANSIT-1",
                group[0][0],group[-1][0],max(daily.values()),support,transit_axes(planet,aspect),
                metadata={"planet":planet,"target":target,"aspect":aspect,"orb":orb,
                    "daily_strength":daily,"peak_day":peak[0].isoformat(),"exact_times":sorted(set(exact)),
                    "temporal_role":"trigger","precision":"daily-sampled orb; exact root when bracketed",
                    "state_action":"unknown"}))
    return result

def context_signals(request):
    result=[]
    for fact in request.context:
        if fact.end<request.start or fact.start>request.end: continue
        result.append(make_signal("context","context_assisted","context:"+fact.fact_id,["fact:"+fact.fact_id],
            "IDENTITY-1",fact.start,fact.end,1,{fact.primary_domain:1},metadata={
                "known_at":fact.known_at.isoformat(),"state":fact.state,"role":fact.role,
                "temporal_role":"trigger","state_action":fact.action,"provided_not_predicted":True},
            subject_id=fact.subject_id,identity_key=fact.subject_id))
    return result

def build_signals(request, bundle, policy):
    out=[]
    generators={"profection":lambda:profections(request,bundle["tropical"],policy),
        "dasha":lambda:dashas(request,bundle["sidereal_lahiri"],policy),
        "solar_return":lambda:returns(request,bundle["tropical"],policy),
        "transit":lambda:transits(request,bundle["tropical"],policy)}
    for family,fn in generators.items():
        if family not in request.exclude_families: out.extend(fn())
    if request.mode=="context_assisted": out.extend(context_signals(request))
    # IDs with contradictory payloads are rejected; exact repeats are idempotent.
    unique={}
    for s in out:
        if s.signal_id in unique and s.to_dict()!=unique[s.signal_id].to_dict():
            raise ValueError("conflicting evidence IDs")
        unique[s.signal_id]=s
    return sorted(unique.values(),key=lambda s:(s.start,s.signal_id))
