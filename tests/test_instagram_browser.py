import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from app import instagram_browser as ig
from app.browser_worker import instagram_host, instagram_login_post, policy


class InstagramProfileTests(unittest.TestCase):
    def test_dedicated_profile_and_no_shared_user_scope(self):
        with patch('app.zar_browser.actor') as actor:
            ig.browser()
        actor.assert_called_once_with('zar-instagram-operational', instagram_profile=True)

    def test_network_does_not_allow_other_modules_or_mutations(self):
        self.assertTrue(instagram_host('https://www.instagram.com/reel/abc/'))
        self.assertTrue(instagram_login_post('https://www.instagram.com/api/v1/web/accounts/login/ajax/'))
        for url in ('https://facebook.com/login', 'https://instagram.com.attacker.org/accounts/login/', 'https://www.instagram.com/api/v1/media/configure/', 'https://www.instagram.com/api/v1/direct_v2/threads/broadcast/text/'):
            self.assertFalse(instagram_login_post(url))
        self.assertTrue(instagram_login_post('https://www.instagram.com/api/graphql','fb_api_req_friendly_name=usePolarisLoginMutation'))
        self.assertFalse(instagram_login_post('https://www.instagram.com/api/graphql','fb_api_req_friendly_name=PolarisPublishMutation'))
        self.assertFalse(instagram_login_post('https://www.instagram.com/api/graphql','fb_api_req_friendly_name=PolarisSendMessageMutation'))
        self.assertFalse(instagram_host('https://facebook.com/'))
        self.assertEqual(policy('password', 'fill'), 'HUMAN_ACTION')

    def test_wrong_identity_never_verifies(self):
        with tempfile.TemporaryDirectory() as root:
            marker=Path(root)/'identity';marker.write_text('fixture')
            with patch.object(ig,'marker',return_value=marker), patch.object(ig,'browser',return_value=Mock(run=Mock(return_value={'authenticated':True,'account':'personal'}))), patch('app.oauth_vault.persist') as persist:
                ig.verify()
            persist.assert_not_called();self.assertFalse(marker.exists())

    def test_missing_session_never_opens_authenticated_reel(self):
        with patch.object(ig,'marker',return_value=Mock(exists=Mock(return_value=False))),patch.object(ig,'browser') as actor:
            self.assertEqual(ig.discovery('https://www.instagram.com/reel/Dec6NIauAZB/')['status'],'LOGIN_REQUIRED')
        actor.assert_not_called()

    def test_login_resolves_live_controls_without_cached_indices(self):
        from app.browser_worker import instagram_control
        page=Mock()
        instagram_control(page,{'tag':'INPUT','name':'pass','index':999})
        page.locator.assert_called_once_with('input[name="pass"]')
        instagram_control(page,{'label':'Log In','index':999})
        page.get_by_role.assert_called_once_with('button',name='Log In',exact=True)
        with self.assertRaises(ValueError):instagram_control(page,{'label':'Publish'})

    def test_owner_and_csrf_required(self):
        from flask import Flask
        from app.zar_browser import blueprint
        app=Flask(__name__);app.secret_key='fixture';app.register_blueprint(blueprint)
        client=app.test_client()
        with patch.object(ig,'allowed_owner',return_value=False):
            self.assertEqual(client.get('/instagram-browser').status_code,403)
        with patch.object(ig,'allowed_owner',return_value=True),patch.object(ig,'browser') as actor:
            self.assertEqual(client.post('/api/browser/instagram',json={'action':'fill','value':'fixture'}).status_code,403)
        actor.assert_not_called()

if __name__=='__main__':unittest.main()
