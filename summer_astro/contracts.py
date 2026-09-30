from __future__ import annotations
import hashlib
import json
import math
from datetime import date, datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, reset_tzpath
from importlib.resources import files
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

UTC = timezone.utc
# Pin historical conversion to the bundled tzdata release, not host OS tzfiles.
reset_tzpath([str(files("tzdata").joinpath("zoneinfo"))])

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False, default=str)

def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()

def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone offset")
    return value.astimezone(UTC)

def localize(value: datetime, zone: str, fold: int | None = None) -> datetime:
    tz = ZoneInfo(zone)
    if value.tzinfo is not None:
        return value.astimezone(tz)
    possible = []
    for f in (0, 1):
        a = value.replace(tzinfo=tz, fold=f)
        if a.astimezone(UTC).astimezone(tz).replace(tzinfo=None) == value:
            possible.append(a)
    if not possible:
        raise ValueError("birth time does not exist in this historical timezone")
    if possible[0].utcoffset() != possible[-1].utcoffset() and fold is None:
        raise ValueError("ambiguous birth time: supply fold=0 or fold=1")
    return value.replace(tzinfo=tz, fold=fold or 0)

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Birth(Strict):
    date: date
    time: str = Field(pattern=r"^\d{2}:\d{2}(:\d{2})?$")
    timezone: str
    latitude: float = Field(ge=-89.5, le=89.5)
    longitude: float = Field(ge=-180, le=180)
    time_source: str = "user_reported"
    uncertainty_minutes: float | None = Field(default=None, ge=0, le=120)
    fold: Literal[0, 1] | None = None

    @model_validator(mode="after")
    def check_time(self):
        self.instant()
        if not 1801 <= self.date.year <= 2098:
            raise ValueError("bundled runtime supports birth years 1801..2098")
        return self

    def instant(self):
        return localize(datetime.fromisoformat(f"{self.date}T{self.time}"), self.timezone, self.fold)

DOMAINS = {
    "self", "cashflow", "income", "debt", "property", "vehicle",
    "travel_short", "travel_long", "relocation", "education",
    "communication", "family", "home_residence", "romance", "children",
    "health", "work_routine", "partnership", "marriage", "shared_resources",
    "career_role", "career_status", "friendship", "networks", "withdrawal", "loss", "unknown"
}

class ContextFact(Strict):
    fact_id: str = Field(min_length=1, max_length=100)
    known_at: datetime
    start: date
    end: date
    primary_domain: str
    subject_id: str = Field(min_length=1, max_length=100)
    role: Literal["core", "secondary"] = "core"
    state: Literal["planned", "ongoing", "observed"] = "planned"
    action: Literal["activation", "entry", "exit", "transfer", "restriction", "unknown"] = "unknown"
    event_type: str = "unknown"
    subtypes: list[str] = Field(default_factory=list, max_length=20)
    participant_roles: list[str] = Field(default_factory=list, max_length=20)
    family_is_subject: bool = False

    @field_validator("known_at")
    @classmethod
    def utc_time(cls, v):
        return aware(v)

    @model_validator(mode="after")
    def valid(self):
        from .taxonomy import EVENT_TYPES, ALL_SUBTYPES
        if self.event_type not in EVENT_TYPES or any(s not in ALL_SUBTYPES for s in self.subtypes):
            raise ValueError("unknown event type or subtype")
        if self.primary_domain not in DOMAINS or self.end < self.start:
            raise ValueError("invalid context domain or interval")
        return self

class NegativeControls(Strict):
    sample_count: int = Field(default=12, ge=4, le=30)
    radius_days: int = Field(default=30, ge=7, le=180)
    seed: int = Field(default=17, ge=0, le=2147483647)

class ForecastRequest(Strict):
    birth: Birth
    start: date
    end: date
    as_of: datetime
    subject_key: str = Field(default="personal", min_length=1, max_length=100)
    mode: Literal["astrology_only", "context_assisted"] = "astrology_only"
    max_display: int = Field(default=6, ge=0, le=100)
    exclude_families: list[Literal["profection", "dasha", "solar_return", "transit"]] = Field(default_factory=list)
    context: list[ContextFact] = Field(default_factory=list, max_length=100)
    personal_relevance: dict[str, float] = Field(default_factory=dict)
    negative_controls: NegativeControls | None = None

    @field_validator("as_of")
    @classmethod
    def utc_time(cls, v):
        return aware(v)

    @model_validator(mode="after")
    def valid(self):
        if self.negative_controls and (self.start != self.end or self.mode != "astrology_only"):
            raise ValueError("negative controls require one day in astrology_only mode")
        if self.end < self.start or (self.end - self.start).days > 1095:
            raise ValueError("forecast interval must span 0..1095 days")
        if self.start < self.birth.date or self.end.year > 2098:
            raise ValueError("forecast range outside supported interval")
        if self.mode == "astrology_only" and self.context:
            raise ValueError("context must be empty in astrology_only mode")
        if any(f.known_at > self.as_of for f in self.context):
            raise ValueError("context leakage: known_at is later than as_of")
        if len({f.fact_id for f in self.context}) != len(self.context):
            raise ValueError("context fact IDs must be unique")
        if any(d not in DOMAINS or not math.isfinite(v) or not 0 <= v <= 1 for d,v in self.personal_relevance.items()):
            raise ValueError("personal relevance must use known domains and values 0..1")
        return self

class EventOutput(Strict):
    forecast_id: str
    status: Literal["qualified", "ambiguous", "insufficient-data", "candidate"]
    event_class: str
    core_process: str
    primary_domain: str
    secondary_domains: list[str]
    action_candidates: list[str]
    action_status: Literal["supported", "mixed", "unknown"]
    axes: dict[str, float]
    background_interval: dict | None
    trigger_interval: dict
    peak_interval: dict
    activation_score: float
    occurrence_probability: float | None
    calibration_status: Literal["unvalidated"]
    domain_support: dict[str, float]
    domain_ambiguity: float
    input_stability: float | None
    data_quality: str
    evidence_ids: list[str]
    counterevidence_ids: list[str]
    alternative_hypotheses: list[dict]
    hypothesis_comparisons: list[dict]
    phases: list[dict]
    abstention_reason: str | None
    personal_relevance: float
    provenance: Literal["astrology", "context_assisted"]
    why: list[str]
