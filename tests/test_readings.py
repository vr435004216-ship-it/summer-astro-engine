from copy import deepcopy
from summer_astro.readings import build_reading, build_readings


def candidate():
    return dict(forecast_id='test', status='insufficient-data',
        primary_domain='education', domain_support={'education':.534,'travel_long':.534,'career_role':.09},
        trigger_interval={'start':'2026-10-12','end':'2026-11-08'},
        peak_interval={'start':'2026-10-15','end':'2026-10-15','precision':'daily'},
        activation_score=.534, input_stability=None, evidence_ids=['test-evidence'],
        abstention_reason='birth_time_uncertainty_unknown_or_sensitive', action_status='unknown',
        provenance='astrology', personal_relevance=.5)


def test_tied_domains_are_both_readable_without_qualification():
    e=candidate();r=build_reading(e)
    assert {d['domain'] for d in r['domains']}=={'education','travel_long'}
    assert 'التعليم' in r['summary'] and 'السفر البعيد' in r['summary']
    assert r['forecast_status']=='insufficient-data' and r['occurrence_probability'] is None
    assert any('هامش' in n for n in r['notes'])


def test_presentation_does_not_mutate_raw_evidence():
    e=candidate();before=deepcopy(e)
    build_reading(e)
    assert e==before


def test_context_is_not_presented_as_blind_inference():
    e=candidate();e['provenance']='context_assisted';e['primary_domain']='travel_long'
    r=build_reading(e)
    assert r['context_used'] and [d['domain'] for d in r['domains']]==['travel_long']
    assert any('معلومات واقعية' in n for n in r['notes'])


def test_display_limit_does_not_remove_candidates():
    events=[{**candidate(),'forecast_id':str(i)} for i in range(8)]
    assert len(build_readings(events,6))==6 and len(events)==8
    assert build_readings(events,0)==[]


def test_far_domain_not_promoted_to_equal_alternative():
    r=build_reading(candidate())
    assert 'career_role' not in [d['domain'] for d in r['domains']]
