import json
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask, session
from app import studio_music

class MusicProjects(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict('os.environ',{'ZAR_DATA_DIR':self.tmp.name});self.env.start()
        self.scope=patch.object(studio_music,'safe_slug',side_effect=lambda:session.get('scope','alice'));self.scope.start()
        self.app=Flask(__name__);self.app.secret_key='test-only';studio_music.register(self.app)
        self.a=self.app.test_client();self.b=self.app.test_client()
        with self.b.session_transaction() as s:s['scope']='bob'
        self.project={'schema':'ZarMusicProject','version':1,'id':'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','name':'Trap de prueba','tempo':140,'tracks':[]}
    def tearDown(self):self.scope.stop();self.env.stop();self.tmp.cleanup()
    def test_save_load_and_isolation(self):
        csrf=self.a.get('/api/studio/music/projects').json['csrf'];url='/api/studio/music/projects/'+self.project['id']
        self.assertEqual(self.a.put(url,json=self.project).status_code,403)
        self.assertEqual(self.a.put(url,json=self.project,headers={'X-ZAR-Business-CSRF':csrf}).status_code,200)
        self.assertEqual(self.a.get(url).json['project']['name'],'Trap de prueba')
        self.assertEqual(self.b.get(url).status_code,404)
        self.assertEqual(self.b.get('/api/studio/music/projects').json['projects'],[])
        self.assertEqual(len(self.a.get('/api/studio/music/projects').json['projects']),1)
    def test_path_schema_and_limit(self):
        for project in [dict(self.project,id='../bad'),dict(self.project,schema='Other'),dict(self.project,tracks=[{}]*25)]:
            with self.assertRaises(ValueError):studio_music.validate(project)
        with self.assertRaises(ValueError):studio_music.validate(dict(self.project,tempo=float('nan')))

if __name__=='__main__':unittest.main()
