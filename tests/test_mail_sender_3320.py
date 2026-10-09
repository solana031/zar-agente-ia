"""No provider writes: explicit identity, changed connection and plan ordering."""
import unittest
from unittest.mock import patch
from app import mail_identity, gmail, identity_mail, semantic_planner, semantic_tasks

class SenderTests(unittest.TestCase):
    def test_only_verified_account_is_offered(self):
        with patch.object(gmail,'is_connected',return_value=True),patch.object(gmail,'gmail_status',return_value={'email':'personal@example.test'}):
            accounts=mail_identity.available()
            self.assertEqual([a['email'] for a in accounts],['personal@example.test'])
            self.assertNotEqual(accounts[0]['label'],'ZAR')
            with self.assertRaises(ValueError):mail_identity.validate(mail_identity.ZAR_EMAIL)

    def test_missing_and_changed_sender_never_send(self):
        with patch.object(gmail,'is_connected',return_value=True),patch.object(gmail,'gmail_status',return_value={'email':'personal@example.test'}),patch.object(gmail,'send_with_attachments') as send:
            for sender in [None,mail_identity.ZAR_EMAIL]:
                with self.assertRaises(ValueError):identity_mail.operate('mock','send',{'confirmed':True,'sender_identity':sender})
            send.assert_not_called()

    def test_no_connection_is_not_a_fake_zar_identity(self):
        with patch.object(gmail,'is_connected',return_value=False):
            self.assertEqual(mail_identity.available(),[])
            with self.assertRaises(ValueError):mail_identity.validate(mail_identity.ZAR_EMAIL)

    def test_sender_selection_precedes_final_confirmation(self):
        with patch.object(semantic_planner.holdings,'read',return_value={}):
            plan=semantic_planner.build('mock','Investiga energía, crea un informe y envíamelo a mi propio email',semantic_tasks.plan,allow_model=False)
        kinds=[s['kind'] for s in plan['subtasks']]
        self.assertLess(kinds.index('DRAFT_EMAIL'),kinds.index('SENDER_SELECTION'))
        self.assertLess(kinds.index('SENDER_SELECTION'),kinds.index('FINAL_CONFIRMATION'))
        self.assertLess(kinds.index('FINAL_CONFIRMATION'),kinds.index('SEND_EMAIL'))
        self.assertIsNone(plan['entities']['sender_identity'])

    def test_explicit_zar_request_is_recorded_without_sending(self):
        with patch.object(semantic_planner.holdings,'read',return_value={}):
            plan=semantic_planner.build('mock','Investiga energía y envíamelo desde ZAR',semantic_tasks.plan,allow_model=False)
        self.assertEqual(plan['entities']['sender_identity'],mail_identity.ZAR_EMAIL)

if __name__=='__main__':unittest.main()
