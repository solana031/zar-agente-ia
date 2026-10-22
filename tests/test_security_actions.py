from copy import deepcopy
from app.identity_center import human_action_groups


def test_security_actions_take_priority_without_losing_or_duplicating_original_records():
    old={'id':'old','service':'RELAYCLAW','action':'OBSERVED_BLOCKER','status':'ACTION_REQUIRED','created_at':'2026-10-20','instructions':['Old usage observation']}
    def action(id,provider,priority,status='ACTION_REQUIRED'):
        return {'id':id,'service':provider,'action':'SECURITY_ROTATION_2026_10','status':status,'created_at':'2026-10-22','instructions':['Exact provider screen'],
                'security_rotation_2026_10':True,'security_priority':priority}
    state={'google':{},'human_actions':[old,action('relay','RELAYCLAW','MEDIUM'),action('router','OPENROUTER','CRITICAL'),action('google','GOOGLE_OAUTH','HIGH'),action('retired','OLD','CRITICAL','DONE')]}
    before=deepcopy(state);groups=human_action_groups(state)
    assert [x['id'] for x in groups]==['router','google','relay']
    assert [x['priority'] for x in groups]==['CRITICAL','HIGH','MEDIUM']
    assert set(groups[2]['related_ids'])=={'old','relay'}
    assert state==before
