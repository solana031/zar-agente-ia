import unittest
from contextlib import nullcontext
from unittest.mock import patch
from app import business_connectors, jev_decision, holdings


class PolicyStatesTest(unittest.TestCase):
    def test_server_policy_is_ready_without_hosted_key(self):
        with patch.dict('os.environ', {}, clear=True):
            rows = {row['name']: row for row in business_connectors.inventory({})}
            self.assertEqual(jev_decision.status()['state'], 'READY')
            self.assertEqual(jev_decision.status()['hosted_state'], 'OPTIONAL')
        self.assertEqual(rows['JEV']['status'], 'READY')
        self.assertEqual(rows['JEV']['configuration'], [])
        for name in ('F5-TTS', 'faster-whisper'):
            self.assertEqual(rows[name]['status'], 'OPTIONAL')

    def test_actual_policy_decisions_and_stop(self):
        state = {'global_stop': False}
        with patch.object(holdings, 'read', return_value=state), \
             patch.object(holdings, 'write'), \
             patch.object(holdings, 'transaction', side_effect=lambda scope: nullcontext()):
            for action in ('RESEARCH', 'REPORT', 'DRAFT_EMAIL'):
                self.assertEqual(jev_decision.evaluate('fixture', {'action': action})['decision'], 'ALLOW')
            for action in ('SEND_EMAIL', 'MEDIA_PUBLISH', 'PAYMENT'):
                self.assertEqual(jev_decision.evaluate('fixture', {'action': action})['decision'], 'CONFIRM')
            self.assertEqual(jev_decision.evaluate('fixture', {'action': 'TRADING_LIVE'})['decision'], 'DENY')
            state['global_stop'] = True
            self.assertEqual(jev_decision.evaluate('fixture', {'action': 'RESEARCH'})['decision'], 'DENY')

    def test_dramaclaw_health_does_not_claim_mp4(self):
        from app import media_company
        proof={'api_ready':True,'verified_at':'2026-10-09T21:00:00+00:00'}
        with patch.dict('os.environ', {'DRAMACLAW_API_URL':'https://provider.example'}, clear=True), patch.object(media_company,'status',return_value=proof):
            row=next(r for r in business_connectors.inventory({}) if r['name']=='DramaClaw DIRECT')
        self.assertEqual(row['status'],'VERIFIED')
        self.assertIn('por proyecto',row['verification_scope'])

    def test_storage_presence_does_not_close_render_blocker(self):
        from app import identity_center,media_company
        state={'identity_center':{'google':{},'human_actions':[{'id':'fixture','service':'CLOUDINARY','action':'OBSERVED_BLOCKER','status':'ACTION_REQUIRED'}]}}
        with patch.object(holdings,'read',return_value=state),patch.object(holdings,'write'),patch.object(holdings,'transaction',side_effect=lambda scope:nullcontext()),patch.object(media_company,'status',return_value={'api_ready':True,'capabilities':{'media_storage':{'configured':True,'provider':'cloudinary'}}}):
            result=identity_center.operate('fixture','continue',{'id':'fixture'})
        self.assertEqual(result['status'],'ACTION_REQUIRED')


if __name__ == '__main__':
    unittest.main()
