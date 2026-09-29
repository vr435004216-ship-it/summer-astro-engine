"""Deterministic Arabic interpretations of candidate evidence, separate from forecasts."""
from .contracts import Strict
from typing import Literal

NAMES = {
    'self':'الذات', 'cashflow':'التدفق النقدي', 'income':'الدخل', 'debt':'الديون',
    'property':'العقار', 'vehicle':'المركبات', 'travel_short':'السفر القصير',
    'travel_long':'السفر البعيد', 'relocation':'الانتقال السكني', 'education':'التعليم',
    'communication':'التواصل', 'family':'العائلة', 'home_residence':'السكن',
    'romance':'العلاقات العاطفية', 'children':'الأطفال', 'health':'الصحة',
    'work_routine':'روتين العمل', 'partnership':'الشراكات', 'marriage':'الزواج',
    'shared_resources':'الموارد المشتركة', 'career_role':'الدور المهني',
    'career_status':'المكانة المهنية', 'friendship':'الصداقات', 'networks':'شبكات العلاقات',
    'withdrawal':'العزلة والانسحاب', 'unknown':'مجال غير محدد'
}
EXAMPLES = {
    'education':'نشاط دراسي أو تدريبي، أو تحضير متعلق بالتعلم.',
    'travel_long':'رحلة بعيدة، أو تحضير وإجراءات مرتبطة بها.',
    'travel_short':'تنقلات أو رحلة قصيرة، أو التحضير لها.',
    'relocation':'مسائل متعلقة بالانتقال أو تغيير مكان السكن.',
    'career_role':'مسائل تخص مسؤولياتك أو دورك في العمل.',
    'career_status':'مسائل تخص موقعك أو وضعك المهني.',
    'work_routine':'مسائل تخص جدول العمل أو إجراءاته اليومية.',
    'home_residence':'مسائل تخص السكن أو ترتيب شؤونه.',
    'family':'مسائل تخص الأسرة أو التواصل معها.',
    'romance':'مسائل تخص التواصل العاطفي أو طبيعة العلاقة.',
    'partnership':'مسائل تخص الشراكات أو الاتفاقات بين طرفين.',
    'marriage':'مسائل مرتبطة بالزواج؛ وجود الإشارة لا يعني حدوث زواج.',
    'cashflow':'مسائل تخص حركة الأموال أو المصروفات.',
    'income':'مسائل تخص مصادر الدخل.',
    'property':'مسائل تخص العقار أو التعامل معه.',
    'vehicle':'مسائل تخص المركبة أو استخدامها.',
    'debt':'مسائل تخص التزامات مالية أو ديون.',
    'shared_resources':'مسائل تخص الموارد أو الالتزامات المشتركة.',
    'self':'مسائل تخص أولوياتك أو تنظيم شؤونك الشخصية.',
    'health':'مسائل تخص العناية بالنفس؛ هذه القراءة لا تستنتج مرضًا أو تشخيصًا.',
    'communication':'مسائل تخص التواصل أو تبادل المعلومات.',
    'friendship':'مسائل تخص الصداقات والتواصل الاجتماعي.',
    'networks':'مسائل تخص شبكة العلاقات والمجموعات.',
    'children':'مسائل متعلقة بالأطفال؛ لا تستنتج القراءة حملًا أو ولادة.',
    'withdrawal':'وقت أو اهتمام مرتبط بالخصوصية والابتعاد عن الانشغال.',
}

class DomainReading(Strict):
    domain: str
    label: str
    support_score: float
    example: str | None

class Reading(Strict):
    forecast_id: str
    kind: Literal['interpretation_not_event_confirmation'] = 'interpretation_not_event_confirmation'
    forecast_status: Literal['qualified','ambiguous','insufficient-data','candidate']
    title: str
    domains: list[DomainReading]
    trigger_interval: dict
    peak_interval: dict
    summary: str
    notes: list[str]
    evidence_ids: list[str]
    context_used: bool
    occurrence_probability: None = None
    presentation_version: str = 'arabic-readings-1'


def build_reading(event, ambiguity_margin=.06, qualification_score=.55):
    ranked=sorted(((d,float(v)) for d,v in event['domain_support'].items() if v>0),key=lambda p:(-p[1],p[0]))
    if event['provenance']=='context_assisted':
        # An explicit supplied domain is not relabeled as an independent inference.
        ranked=[(event['primary_domain'],event['domain_support'].get(event['primary_domain'],0))]
    near=[(d,v) for d,v in ranked if ranked[0][1]-v<=ambiguity_margin+1e-9] if ranked else [('unknown',0)]
    domains=[DomainReading(domain=d,label=NAMES.get(d,d),support_score=v,example=EXAMPLES.get(d)) for d,v in near]
    title=' / '.join(d.label for d in domains)
    interval=event['trigger_interval'];peak=event['peak_interval']['start']
    if len(domains)>1:
        statement=f'تظهر إشارات متقاربة في {title}. الحسابات لا تفصل بينها بما يكفي؛ من ظروفك تحددين التفسير الأقرب.'
    else:
        statement=f'تظهر إشارات في {title}. هذه قراءة للمجال المتفعّل، وليست تأكيدًا لوقوع حدث.'
    summary=f"من {interval['start']} إلى {interval['end']}، والذروة الحسابية حول {peak}: {statement}"
    notes=['الأمثلة توضح معنى المجال، ولا تصف أحداثًا استنتجها المحرك.', 'قوة الدعم ليست احتمال حدوث.']
    if event['input_stability'] is None:
        notes.append('هامش وقت الميلاد غير معلوم؛ لم يُختبر استقرار النتيجة عند تغييره. يمكنك قراءة الإشارات مع بقاء هذا القيد.')
    elif event['abstention_reason']=='birth_time_uncertainty_unknown_or_sensitive':
        notes.append('بعض الحسابات حساسة لتغيير وقت الميلاد ضمن الهامش المدخل.')
    if event['activation_score']<qualification_score:
        notes.append('المرشح لم يصل إلى عتبة تأهيل التوقع المحدد؛ تُعرض قراءته دون تغيير درجته.')
    if event['action_status']=='mixed':
        notes.append('إشارات الحركة متعارضة؛ لا يرجّح المحرك اتجاهًا واحدًا.')
    if event['provenance']=='context_assisted':
        notes.append('هذه القراءة استخدمت معلومات واقعية مدخلة، وليست استنتاجًا فلكيًا مستقلًا.')
    return Reading(forecast_id=event['forecast_id'],forecast_status=event['status'],title=title,
        domains=domains,trigger_interval=interval,peak_interval=event['peak_interval'],summary=summary,
        notes=notes,evidence_ids=event['evidence_ids'],context_used=event['provenance']=='context_assisted').model_dump()


def build_readings(events, limit=6, ambiguity_margin=.06, qualification_score=.55):
    ranked=sorted(events,key=lambda e:(-e['activation_score'],-e['personal_relevance'],e['forecast_id']))
    return [build_reading(e,ambiguity_margin,qualification_score) for e in ranked[:limit]]
