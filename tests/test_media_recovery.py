import unittest
from contextlib import nullcontext
from copy import deepcopy
from unittest.mock import patch
from app.media_recovery import assess
from app.media_projects import controls


class RecoveryTests(unittest.TestCase):
    def test_uncertain_submission_never_becomes_safe_retry(self):
        r = assess({'status':'ERROR','checkpoint':{'project_id':'p','stage':'identities','error_code':'submission_unknown'}})
        self.assertEqual(r['classification'],'FAILED_EXTERNAL')
        self.assertFalse(r['automatic_retry'])

    def test_paused_assets_are_preserved_and_counted(self):
        record={'status':'PAUSED','script':'story','characters':[{'name':'Nico'}],
                'checkpoint':{'project_id':'p','stage':'frames'},'scenes':[{'frame_url':'existing.png'}]}
        before=deepcopy(record)
        r=assess(record)
        self.assertEqual(r['classification'],'RECOVERABLE')
        self.assertEqual(r['assets']['frame_url'],1)
        self.assertEqual(record,before)

    def test_archive_and_restore_keep_provider_checkpoint(self):
        record={'status':'PAUSED','checkpoint':{'stage':'frames','project_id':'p','tasks':[{'task_id':'existing'}]},'script':'original'}
        before=deepcopy(record['checkpoint'])
        with patch('app.media_projects.media._task',return_value={'id':'abc'}),patch('app.media_projects.media._job_lock',return_value=nullcontext(True)),patch('app.media_projects.media._read',return_value=record),patch('app.media_projects.media._save'),patch('app.media_projects.media._mirror'),patch('app.media_projects.media._result',side_effect=lambda t,r:assess(r)):
            self.assertTrue(controls('scope','abc','archive',{'confirmed':True,'is_test':True})['archived'])
            self.assertEqual(record['checkpoint'],before)
            self.assertFalse(controls('scope','abc','restore',{})['archived'])
            self.assertEqual(record['status'],'PAUSED')
            self.assertEqual(record['script'],'original')

    def test_active_work_cannot_be_archived(self):
        with patch('app.media_projects.media._task',return_value={'id':'abc'}),patch('app.media_projects.media._job_lock',return_value=nullcontext(True)),patch('app.media_projects.media._read',return_value={'status':'PUBLISHING'}):
            with self.assertRaises(ValueError):controls('scope','abc','archive',{'confirmed':True})
