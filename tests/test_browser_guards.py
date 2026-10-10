import unittest
from unittest.mock import patch
from app.browser_network import public_url, public_addresses
from app.browser_worker import policy,human_gate,security_state


class BrowserGuards(unittest.TestCase):
    def dns(self, addresses):
        return [(2, 1, 6, '', (ip, 443)) for ip in addresses]

    def test_private_mixed_rebinding_and_credentials_denied(self):
        for addresses in (['127.0.0.1'], ['169.254.169.254'], ['10.0.0.1'], ['::1'], ['93.184.216.34', '192.168.1.1']):
            with patch('socket.getaddrinfo', return_value=self.dns(addresses)):
                with self.assertRaises(ValueError):
                    public_addresses('public.example')
        for url in ('file:///etc/passwd', 'http://example.com', 'https://user:secret@example.com', 'https://example.com:8080'):
            with self.assertRaises(ValueError):
                public_url(url)
        with patch('socket.getaddrinfo', return_value=self.dns(['93.184.216.34'])):
            self.assertEqual(public_url('https://example.com/path'), 'https://example.com/path')

    def test_no_agent_legal_financial_or_secret_actions(self):
        for label in ('Accept terms', 'Pagar', 'Subscribe', 'Delete account'):
            self.assertEqual(policy(label, 'click'), 'HUMAN_ACTION')
        for label in ('password', 'verification code', 'phone', 'tax id'):
            self.assertEqual(policy(label, 'fill'), 'HUMAN_ACTION')
        self.assertEqual(policy('Sell stock', 'click'), 'DENY')
        self.assertEqual(policy('Continue', 'click'), 'CONFIRM')
        self.assertEqual(policy('Email', 'fill'), 'ALLOW')

    def test_api_requires_session_csrf_google_and_confirmation(self):
        from flask import Flask
        from app.zar_browser import blueprint
        app = Flask(__name__)
        app.secret_key = 'fixture-only'
        app.register_blueprint(blueprint)
        client = app.test_client()
        other = app.test_client()
        csrf = client.get('/api/browser').json['csrf']
        with patch('app.cloud_auth.connected', return_value=True), \
             patch('app.jev_decision.evaluate', return_value={'decision':'ALLOW'}), \
             patch('app.zar_browser.operate', return_value={'ok':True,'status':'READY'}) as execute:
            self.assertEqual(client.post('/api/browser', json={'action':'read'}).status_code, 403)
            self.assertEqual(other.post('/api/browser', headers={'X-ZAR-Browser-CSRF':csrf}, json={'action':'read'}).status_code, 403)
            execute.assert_not_called()

            self.assertEqual(client.post('/api/browser', headers={'X-ZAR-Browser-CSRF':csrf}, json={'action':'read'}).status_code, 200)
        with patch('app.cloud_auth.connected', return_value=False), patch('app.zar_browser.operate') as execute:
            self.assertEqual(client.post('/api/browser', headers={'X-ZAR-Browser-CSRF':csrf}, json={'action':'read'}).status_code, 403)
            execute.assert_not_called()
        with patch('app.cloud_auth.connected', return_value=True), \
             patch('app.jev_decision.evaluate', return_value={'decision':'CONFIRM'}), patch('app.zar_browser.operate') as execute:
            self.assertEqual(client.post('/api/browser', headers={'X-ZAR-Browser-CSRF':csrf}, json={'action':'click','confirmed':'true'}).status_code, 409)
            execute.assert_not_called()


    def test_provider_challenges_are_not_ready(self):
        self.assertTrue(human_gate('Just a moment...','Checking browser security'))
        self.assertTrue(human_gate('Login','Verify you are human'))
        self.assertTrue(human_gate('Google','2-step verification'))
        self.assertFalse(human_gate('Example Domain','This domain is for use in documentation.'))

    def test_distinct_human_states(self):
        for title,text,status in [('Login','','LOGIN_REQUIRED'),('Google','2-step verification','2FA'),('Page','Verify you are human','CAPTCHA'),('Access denied','','BLOCKED'),('Checkout','','PAYMENT_REQUIRED')]:
            self.assertEqual(security_state(title,text),status)
            self.assertTrue(human_gate(title,text))


if __name__ == '__main__':
    unittest.main()
