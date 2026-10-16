import json
import unittest
from app.browser_diagnostics import event,classify,safe_path


class SafeNetworkDiagnostics(unittest.TestCase):
    def test_actual_route_callback_keeps_bounded_diagnostics_without_breaking_requests(self):
        import ast,inspect
        from urllib.parse import urlsplit
        from unittest.mock import Mock
        from app import browser_worker as worker
        tree=ast.parse(inspect.getsource(worker))
        run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
        callback=next(n for n in run.body if isinstance(n,ast.FunctionDef) and n.name=='route')
        source='def harness():\n    callback_errors=[]\n    request_events={}\n    network_events=[]\n    blocked_posts=[]\n    permit=[False]\n    instagram_profile=True\n'
        source+='\n'.join('    '+line for line in ast.unparse(callback).splitlines())+'\n    return route,network_events,callback_errors\n'
        env={'instagram_host':worker.instagram_host,'instagram_login_post':worker.instagram_login_post,'request_body':worker.request_body,'network_event':event,'urlsplit':urlsplit}
        exec(source,env)
        route,events,errors=env['harness']()
        for i in range(65):
            request=Mock(url='https://www.instagram.com/accounts/login/',method='GET',resource_type='document')
            target=Mock(request=request);route(target);target.continue_.assert_called_once()
        self.assertEqual(len(events),60);self.assertEqual(errors,[])

    def test_sensitive_url_parts_never_appear(self):
        row=event('https://www.instagram.com/api/v1/accounts/secret-fixture-value/?token=private','POST','fetch','BLOCK_METHOD_OR_OPERATION')
        text=json.dumps(row)
        self.assertNotIn('secret-fixture-value',text);self.assertNotIn('private',text);self.assertNotIn('token',text)
        self.assertEqual(set(row),{'hostname','method','resource_type','path','network_rule','http_status','redirect_hostname','classification'})

    def test_classification_does_not_confuse_similar_hosts(self):
        self.assertEqual(classify('https://www.instagram.com/accounts/login/'),'INSTAGRAM_AUTH')
        self.assertEqual(classify('https://www.instagram.com/api/graphql'),'INSTAGRAM_API')
        self.assertEqual(classify('https://www.instagram.com/challenge/abc'),'CHALLENGE')
        self.assertEqual(classify('https://www.instagram.com.attacker.example/accounts/login/'),'UNKNOWN_SAFE')
        self.assertEqual(classify('https://media.cdninstagram.com/a.mp4','media'),'INSTAGRAM_MEDIA')
        self.assertEqual(classify('https://static.xx.fbcdn.net/a.js','script'),'META_CDN')

    def test_redirect_does_not_retain_query_or_userinfo(self):
        row=event('https://www.instagram.com/accounts/login/','GET','document','ALLOW_PROFILE_REQUEST',302,'https://www.facebook.com/login/?code=fixture')
        self.assertEqual(row['redirect_hostname'],'www.facebook.com');self.assertEqual(row['classification'],'REDIRECT')
        self.assertNotIn('fixture',json.dumps(row))

if __name__=='__main__':unittest.main()
