import unittest
from unittest.mock import patch
from app.media_fallback import frame_path,queue


class FallbackGuards(unittest.TestCase):
    def test_assets_scoped_to_existing_project(self):
        cp={'project_id':'p1'}
        self.assertEqual(frame_path(cp,'/static/projects/p1/frames/beat.png?v=1'),'frames/beat.png')
        self.assertEqual(frame_path(cp,'/static/projects/p1/assets/narrator/voice.wav',audio=True),'assets/narrator/voice.wav')
        for url in ['/static/projects/p2/frames/a.png','/static/projects/p1/%2e%2e/a.png','/static/projects/p1/frames/a.html']:
            with self.assertRaises(ValueError):frame_path(cp,url)

    def test_no_unconfirmed_render_or_live_stop_bypass(self):
        with self.assertRaises(ValueError):queue('scope','task',False)
        with patch('app.media_fallback.media._task',return_value={'id':'task'}),patch('app.media_fallback.holdings.read',return_value={'global_stop':True}):
            with self.assertRaises(ValueError):queue('scope','task',True)

    def test_unknown_provider_task_cannot_start_fallback(self):
        from contextlib import nullcontext
        record={'checkpoint':{'stage':'audio','active_task':{'task_id':'audio1'}}}
        with patch('app.media_fallback.media._task',return_value={'id':'task'}),patch('app.media_fallback.holdings.read',return_value={}),patch('app.media_fallback.media._job_lock',return_value=nullcontext(True)),patch('app.media_fallback.media._read',return_value=record),patch('app.media_fallback.media._client') as client,patch('app.media_fallback.media._save') as save:
            client.return_value._tasks.return_value=[{'task_id':'audio1','status':'running','error':'ORG_EGRESS_DENIED'}]
            with self.assertRaises(ValueError):queue('scope','task',True)
            client.return_value.advance.assert_not_called()
            save.assert_not_called()


if __name__=='__main__':unittest.main()
