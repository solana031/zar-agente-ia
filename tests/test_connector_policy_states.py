import unittest
from contextlib import nullcontext
from unittest.mock import patch
from app import business_connectors, jev_decision, holdings


class PolicyStatesTest(unittest.TestCase):
    def test_server_policy_is_ready_without_hosted_key(self):
        with patch.dict('os.environ', {}, clear=True):
            rows = {row['name']: row for row in business_connectors.inventory({})}
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


if __name__ == '__main__':
    unittest.main()
