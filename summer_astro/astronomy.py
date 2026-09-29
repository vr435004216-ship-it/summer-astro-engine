from __future__ import annotations
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from functools import lru_cache
import hashlib
import json
import swisseph as swe
from .contracts import Birth, digest

LOCK = RLock()
EPHE = Path(__file__).parent / "ephe"
PLANETS = {"Sun": swe.SUN, "Moon": swe.MOON, "Mercury": swe.MERCURY,
    "Venus": swe.VENUS, "Mars": swe.MARS, "Jupiter": swe.JUPITER,
    "Saturn": swe.SATURN, "Uranus": swe.URANUS, "Neptune": swe.NEPTUNE,
    "Pluto": swe.PLUTO, "Rahu": swe.MEAN_NODE}
RULERS = ["Mars", "Venus", "Mercury", "Moon", "Sun", "Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Saturn", "Jupiter"]
ASPECTS = {"conjunction": 0, "sextile": 60, "square": 90, "trine": 120, "opposition": 180}
ORBS = {"conjunction": 8, "sextile": 5, "square": 7, "trine": 7, "opposition": 8}
VIM_SEQ = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
VIM_YEARS = dict(zip(VIM_SEQ, [7,20,6,10,7,18,16,19,17]))

def angle(a, b):
    return abs((a - b + 180) % 360 - 180)

def house(lon, asc):
    return (int((lon % 360) // 30) - int((asc % 360) // 30)) % 12 + 1

def configure():
    swe.set_ephe_path(str(EPHE))
    swe.set_sid_mode(swe.SIDM_LAHIRI)

def verify_ephemeris():
    manifest = json.loads((EPHE / "manifest.json").read_text())
    for name, item in manifest.items():
        if hashlib.sha256((EPHE / name).read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError("ephemeris integrity check failed: " + name)
    return digest(manifest)

def jd(instant):
    utc = instant.astimezone(timezone.utc)
    with LOCK:
        configure()
        return swe.utc_to_jd(utc.year, utc.month, utc.day, utc.hour, utc.minute,
            utc.second + utc.microsecond/1e6, swe.GREG_CAL)[1]

def from_jd(value):
    with LOCK:
        y,m,d,h,minute,seconds = swe.jdut1_to_utc(value, swe.GREG_CAL)
    return datetime(y,m,d,h,minute,tzinfo=timezone.utc) + timedelta(seconds=seconds)

@lru_cache(maxsize=16384)
def positions(value, sidereal=False):
    with LOCK:
        configure()
        flags = swe.FLG_SWIEPH | swe.FLG_SPEED | (swe.FLG_SIDEREAL if sidereal else 0)
        out = {}
        for name, pid in PLANETS.items():
            xx, used = swe.calc_ut(value, pid, flags)
            if not used & swe.FLG_SWIEPH:
                raise RuntimeError("Swiss files unavailable: fallback refused")
            out[name] = (float(xx[0]), float(xx[3]))
        out["Ketu"] = ((out["Rahu"][0]+180)%360, out["Rahu"][1])
        return tuple((name, *values) for name,values in out.items())

def pos(value, sidereal=False):
    return {name: (lon, speed) for name,lon,speed in positions(value, sidereal)}

def angles(value, latitude, longitude, sidereal=False):
    with LOCK:
        configure()
        cusps, axes = swe.houses_ex(value, latitude, longitude, b"W", swe.FLG_SIDEREAL if sidereal else 0)
    return float(axes[0]), float(axes[1]), list(cusps)

def varga_sign(lon, division):
    lon %= 360
    sign, deg = int(lon//30), lon%30
    if division == 4:
        return (sign+3*min(3,int(deg/7.5)))%12
    if division == 9:
        start = {0: sign, 1: sign+8, 2: sign+4}[sign%3]
        return (start+min(8,int(deg/(30/9))))%12
    if division == 10:
        return ((sign if sign%2==0 else sign+8)+min(9,int(deg/3)))%12
    if division == 16:
        return ({0:0,1:4,2:8}[sign%3]+min(15,int(deg/1.875)))%12
    raise ValueError("unsupported division")

def chart_at(instant, birth, sidereal=False):
    value = jd(instant)
    planets = pos(value, sidereal)
    asc,mc,cusps = angles(value,birth.latitude,birth.longitude,sidereal)
    cells = {n:{"longitude":lon, "speed":speed, "retrograde":speed<0,
        "sign_index":int(lon//30), "house":house(lon,asc)} for n,(lon,speed) in planets.items()}
    aspects=[]
    names=[n for n in cells if n not in {"Rahu","Ketu"}]
    for i,a in enumerate(names):
        for b in names[i+1:]:
            sep=angle(cells[a]["longitude"],cells[b]["longitude"])
            candidates=[(abs(sep-deg),name,deg) for name,deg in ASPECTS.items() if abs(sep-deg)<=ORBS[name]]
            if not candidates: continue
            orb,name,deg=min(candidates)
            later=angle(cells[a]["longitude"]+cells[a]["speed"]*.001,
                cells[b]["longitude"]+cells[b]["speed"]*.001)
            aspects.append({"a":a,"b":b,"aspect":name,"orb":orb,"applying":abs(later-deg)<orb})
    return {"julian_day_ut1":value,"instant_utc":instant.astimezone(timezone.utc).isoformat(),
        "framework":"sidereal_lahiri" if sidereal else "tropical", "asc":asc,"mc":mc,
        "cusps":cusps,"house_system":"Whole Sign","node_type":"mean",
        "rulers":{str(h):RULERS[(int(asc//30)+h-1)%12] for h in range(1,13)},
        "planets":cells,"aspects":aspects,"backend":"Swiss Ephemeris files"}

def vargas(chart, divisions=(4,9,10,16)):
    result={}
    for div in divisions:
        asc=varga_sign(chart["asc"],div)
        result[str(div)]={n:{"sign_index":varga_sign(p["longitude"],div),
            "house":(varga_sign(p["longitude"],div)-asc)%12+1} for n,p in chart["planets"].items()}
        result[str(div)]["Ascendant"]={"sign_index":asc,"house":1}
    return result

def dasha_anchor(chart, instant, year_days):
    moon=chart["planets"]["Moon"]["longitude"]
    width=360/27
    idx=int(moon/width)
    lord=VIM_SEQ[idx%9]
    elapsed=(moon%width)/width*VIM_YEARS[lord]*year_days
    return lord, instant.astimezone(timezone.utc)-timedelta(days=elapsed)

def birth_bundle(birth: Birth, year_days=365.2425):
    instant=birth.instant()
    trop=chart_at(instant,birth,False)
    sid=chart_at(instant,birth,True)
    vc=vargas(sid)
    margin=birth.uncertainty_minutes
    sensitivity={"margin_minutes":margin,"method":"deterministic sensitivity grid; not an event probability",
        "stability":None,"samples":[],"unstable_features":[],"dasha_anchor_span_days":None}
    if margin is not None:
        samples=[]
        offsets=[0] if margin==0 else [-margin,-margin/2,0,margin/2,margin]
        central={"tropical_asc_sign":int(trop["asc"]//30),"sidereal_asc_sign":int(sid["asc"]//30)}
        for div,v in vc.items():
            central["D"+div+"_asc_sign"]=v["Ascendant"]["sign_index"]
            for n,p in v.items(): central["D"+div+"_"+n+"_sign"]=p["sign_index"]
        for n,p in trop["planets"].items(): central["tropical_"+n+"_house"]=p["house"]
        for n,p in sid["planets"].items(): central["sidereal_"+n+"_house"]=p["house"]
        anchors=[]
        matches=0
        for offset in offsets:
            dt=instant+timedelta(minutes=offset)
            a=chart_at(dt,birth,False);b=chart_at(dt,birth,True);v=vargas(b)
            state={"tropical_asc_sign":int(a["asc"]//30),"sidereal_asc_sign":int(b["asc"]//30)}
            for div,c in v.items():
                state["D"+div+"_asc_sign"]=c["Ascendant"]["sign_index"]
                for n,p in c.items(): state["D"+div+"_"+n+"_sign"]=p["sign_index"]
            for n,p in a["planets"].items(): state["tropical_"+n+"_house"]=p["house"]
            for n,p in b["planets"].items(): state["sidereal_"+n+"_house"]=p["house"]
            lord,anchor=dasha_anchor(b,dt,year_days);anchors.append(anchor)
            changed=[k for k in central if central[k]!=state[k]]
            matches+=not changed
            samples.append({"offset_minutes":offset,"changed_features":changed,"dasha_birth_lord":lord,
                "dasha_anchor":anchor.isoformat()})
        sensitivity.update(stability=matches/len(offsets),samples=samples,
            unstable_features=sorted({k for x in samples for k in x["changed_features"]}),
            dasha_anchor_span_days=(max(anchors)-min(anchors)).total_seconds()/86400)
    return {"tropical":trop,"sidereal_lahiri":sid,"varga_context":vc,"sensitivity":sensitivity,
        "ephemeris_version":swe.version,"ephemeris_manifest_hash":verify_ephemeris()}

def solar_return(chart, year, birth):
    # Search from January 1, unlike v1's hard-coded December 1 anchor.
    start=jd(datetime(year,1,1,tzinfo=timezone.utc))
    with LOCK:
        configure()
        result=swe.solcross_ut(chart["planets"]["Sun"]["longitude"],start,swe.FLG_SWIEPH)
    # Check actual solar longitude and file-backed backend at the result.
    if angle(pos(result)["Sun"][0],chart["planets"]["Sun"]["longitude"]) > 1e-5:
        raise RuntimeError("solar return root failed")
    return result
