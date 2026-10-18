import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch
from app import reposnews as rn, reposnews_inbox as inbox, reposnews_discovery as discovery


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'ZAR_DATA_DIR': self.tmp.name, 'INSTAGRAM_IG_USER_ID': 'account', 'INSTAGRAM_REPOSNEWS_SENDERS': 'sender'})
        self.env.start(); rn.write({'owner': 'owner', 'articles': []})

    def tearDown(self): self.env.stop(); self.tmp.cleanup()

    def event(self, text='Bland AI', mid='fixture'):
        return {'object': 'instagram', 'entry': [{'id': 'account', 'messaging': [{'sender': {'id': 'sender'},
                'recipient': {'id': 'account'}, 'message': {'mid': mid, 'text': text,
                'attachments': [{'type': 'share', 'payload': {'url': 'https://www.instagram.com/reel/fixture/'}}]}}]}]}

    def pages(self):
        return [{'url': 'https://www.bland.ai/', 'title': 'Bland AI', 'description': 'Voice agents and tools',
                 'text': 'Bland AI https://docs.bland.ai/integrations/mcp/overview', 'metadata': {}},
                {'url': 'https://docs.bland.ai/integrations/mcp/overview', 'title': 'Bland MCP', 'description': 'Official documentation',
                 'text': 'Bland MCP https://www.bland.ai/', 'metadata': {}}]

    def page_fetch(self,url):
        page=next((p for p in self.pages() if p['url']==url),None)
        if page is None:raise ValueError('OFFICIAL_SOURCE_UNAVAILABLE')
        return page

    def test_large_html_keeps_metadata_without_accumulating_body(self):
        chunks = [b'<head><title>Bland AI</title><meta property="og:description" content="Agent Phone Plan">',
                  b'<!--' + b'x' * 600000 + b'-->', b'<meta property="og:video" content="https://example.fbcdn.net/v.mp4"></head>']
        result = discovery.parse_chunks(chunks)
        self.assertEqual(result['title'], 'Bland AI'); self.assertIn('Agent Phone Plan', result['text'])
        self.assertIn('og:video', result); self.assertNotIn('SOURCE_TOO_LARGE', json.dumps(result))
        self.assertLess(len(json.dumps(result)), 30000)

    def test_json_ld_and_unknown_metadata_do_not_preserve_credentials(self):
        result = discovery.parse_chunks([b'<script type="application/ld+json">{"name":"Bland AI","access_token":"private-fixture","contentUrl":"https://example.org/video?token=private-fixture"}</script>'])
        self.assertNotIn('private-fixture', json.dumps(discovery.sanitize(result))); self.assertIn('Bland AI', result['text'])

    def test_hydration_reads_only_the_requested_public_shortcode(self):
        value = {'data': [{'shortcode': 'other', 'caption': 'Unrelated tool'},
                          {'shortcode': 'target', 'caption': 'Bland AI', 'api_key': 'private-fixture'}]}
        html = '<script type="application/json">' + json.dumps(value) + '</script>'
        result = discovery.parse_chunks([html.encode()], shortcode='target')
        self.assertIn('Bland AI', result['text']); self.assertNotIn('Unrelated tool', result['text'])
        self.assertNotIn('private-fixture', json.dumps(result))

    def test_nested_carousel_references_stay_private(self):
        refs = discovery.attachment_refs([{'type': 'carousel', 'payload': {'elements': [
            {'image_url': 'https://example.fbcdn.net/image.jpg?token=fixture', 'api_key': 'do-not-store'}]}}])
        self.assertEqual(len(refs), 1); self.assertNotIn('api_key', json.dumps(refs))

    def test_bland_resolves_from_spoken_or_visible_evidence_without_llm(self):
        for text in ('Bland AI', 'bland.ai', 'Agent Phone Plan with Claude Code'):
            with patch.object(discovery, 'fetch_official', side_effect=self.pages()), patch.object(inbox, 'generate_json') as ai:
                result = discovery.service_resolution({'text': text, 'outbound_links': []})
            self.assertEqual(result['name'], 'Bland AI'); self.assertEqual(result['type'], 'SERVICE'); ai.assert_not_called()

    def test_named_hint_without_crosslinks_is_not_official(self):
        pages = self.pages(); pages[1]['text'] = 'https://www.bland.ai.attacker.example/'
        with patch.object(discovery, 'fetch_official', side_effect=pages):
            self.assertIsNone(discovery.service_resolution({'text': 'Bland AI', 'outbound_links': []}))

    def test_non_github_service_accepts_coherent_site_and_docs_links(self):
        pages = [{'url': 'https://example.org/', 'title': 'Example Service', 'text': 'https://docs.example.org/', 'metadata': {}},
                 {'url': 'https://docs.example.org/', 'title': 'Example Docs', 'text': 'https://example.org/', 'metadata': {}}]
        with patch.object(discovery, 'fetch_official', side_effect=pages):
            result = discovery.service_resolution({'text': 'Example Service', 'outbound_links': ['https://example.org/', 'https://docs.example.org/']})
        self.assertEqual(result['type'], 'SERVICE'); self.assertNotIn('repo', result)

    def test_direct_fork_is_not_mislabeled_as_official_upstream(self):
        with patch.object(rn, 'github', return_value={'fork': True, 'private': False}):
            with self.assertRaisesRegex(ValueError, 'UPSTREAM_REPOSITORY_REQUIRED'): inbox.research('fork/tool')

    def test_real_pipeline_shape_permalink_to_ready_service_with_503(self):
        item = inbox.receive(self.event())[0]
        inbox.update(item, local_worker_done=True, analysis={'transcript':'Bland AI Agent Phone Plan'})
        before = rn.read()['instagram_inbox'][0].copy()
        with patch('app.jev_decision.proposal', return_value={'decision': 'ALLOW'}), patch.object(inbox.holdings, 'read', return_value={}), \
             patch.object(inbox, 'analyze_media', return_value={}), patch.object(inbox, 'public_discovery', return_value={'status': 'PUBLIC_TEXT_AVAILABLE', 'text': 'Bland AI Agent Phone Plan'}), \
             patch.object(inbox, 'public_metadata', return_value={'status': 'PUBLIC_METADATA_AVAILABLE', 'text': 'Bland AI'}), \
             patch.object(discovery, 'fetch_official', side_effect=self.page_fetch), patch.object(inbox, 'build', side_effect=ValueError('AI_PROVIDER_503')):
            inbox.process(item)
        data = rn.read(); row = data['instagram_inbox'][0]; article = data['articles'][0]
        self.assertEqual(row['status'], 'READY'); self.assertFalse(article['published']); self.assertEqual(article['repository_url'], '')
        self.assertEqual(article['review_kind'], 'DETERMINISTIC_LIMITED_SOURCE_NOTE')
        self.assertEqual(row['external_id'], before['external_id']); self.assertEqual(row['source_url'], before['source_url'])
        self.assertNotIn('VIDEO_ANALYZED', json.dumps(row)); self.assertEqual(row['discovery_evidence']['media_coverage'], [])

    def test_existing_bland_article_is_never_modified(self):
        item = inbox.receive(self.event())[0]
        inbox.update(item, local_worker_done=True, analysis={'transcript':'Bland AI'})
        data = rn.read(); existing = {'id': 'existing-bland', 'website': 'https://www.bland.ai/', 'state': 'READY', 'published': False, 'body_es': 'Original preserved'}
        data['articles'].append(existing); rn.write(data)
        with patch('app.jev_decision.proposal', return_value={'decision': 'ALLOW'}), patch.object(inbox.holdings, 'read', return_value={}), \
             patch.object(inbox, 'analyze_media', return_value={}), patch.object(inbox, 'public_discovery', return_value={'text': 'Bland AI'}), \
             patch.object(inbox, 'public_metadata', return_value={}), patch.object(discovery, 'fetch_official', side_effect=self.pages()):
            inbox.process(item)
        self.assertEqual(rn.read()['articles'], [existing]); self.assertEqual(rn.read()['instagram_inbox'][0]['status'], 'READY')

    def test_inaccessible_content_requires_clarification_and_still_deduplicates(self):
        item = inbox.receive(self.event(text=''))[0]
        with patch('app.jev_decision.proposal', return_value={'decision': 'ALLOW'}), patch.object(inbox, 'analyze_media', return_value={}), \
             patch.object(inbox, 'public_discovery', return_value={'status': 'LOGIN_REQUIRED'}), patch.object(inbox, 'public_metadata', return_value={'status': 'PUBLIC_CONTENT_BLOCKED'}):
            inbox.process(item)
        self.assertEqual(rn.read()['instagram_inbox'][0]['status'], 'WAITING_LOCAL_WORKER')
        self.assertEqual(inbox.receive(self.event(text='')), []); self.assertEqual(len(rn.read()['instagram_inbox']), 1)

    def test_native_video_frame_fallback_is_honest_when_ffmpeg_missing(self):
        with patch('shutil.which', return_value=None):
            parts, state = discovery.video_parts(b'fixture', 1000)
        self.assertEqual(parts, []); self.assertEqual(state['frames'], 0); self.assertEqual(state['audio'], 'NATIVE_VIDEO_INPUT')

    def test_frame_and_audio_extraction_is_bounded_and_in_memory(self):
        responses = [Mock(stdout=b'{"format":{"duration":"12"}}'),
                     Mock(stdout=(b'\xff\xd8fixture\xff\xd9' * 9), returncode=0),
                     Mock(stdout=b'RIFF' + b'x' * 80, returncode=0)]
        with patch('shutil.which', return_value='/fixture/ffmpeg'), patch('subprocess.run', side_effect=responses) as run:
            parts, state = discovery.video_parts(b'fixture-video', 2000)
        self.assertEqual(state['frames'], 6); self.assertEqual(state['audio'], 'EXTRACTED_FULL_BOUNDED_AUDIO')
        self.assertEqual(len(parts), 7)
        self.assertIn('pipe:0', run.call_args.args[0]); self.assertEqual(run.call_args.kwargs['input'], b'fixture-video')

    def test_transient_llm_failure_uses_only_existing_flash_fallback(self):
        failed = Mock(ok=False, status_code=503)
        success = Mock(ok=True, json=lambda: {'candidates': [{'content': {'parts': [{'text': '{"name":"Bland AI"}'}]}}]})
        with patch('app.web_search._gemini_key', return_value='fixture-not-real'), patch('app.web_search._model', return_value='gemini-fixture-flash'), \
             patch('app.model_router.model_for', return_value='gemini-primary-flash'), patch.object(inbox.requests, 'post', side_effect=[failed, success]) as post:
            result = inbox.generate_json('fixture discovery')
        self.assertEqual(result['name'], 'Bland AI'); self.assertEqual(post.call_count, 2)
        self.assertIn('gemini-fixture-flash', post.call_args.args[0])

    def test_audio_visual_project_name_resolves_without_second_llm(self):
        candidate = {'name': 'Example', 'full_name': 'official/Example', 'homepage': 'https://example.org'}
        with patch.object(rn, 'github', return_value={'items': [candidate], 'total_count': 1}), \
             patch.object(inbox, 'homepage_confirms_repository', return_value=True), patch.object(inbox, 'generate_json') as ai:
            result = inbox.resolve_entity('Transcript and OCR clues', 'Example', deterministic_only=True)
        self.assertEqual(result['status'], 'RESOLVED'); ai.assert_not_called()

    def test_media_project_hint_drives_the_pipeline_without_name_prompt(self):
        event = self.event(text=''); event['entry'][0]['messaging'][0]['message']['attachments'] = [
            {'type': 'audio', 'payload': {'url': 'https://example.fbcdn.net/audio.wav'}}]
        item = inbox.receive(event)[0]
        candidate = {'name': 'Example', 'full_name': 'official/Example', 'homepage': 'https://example.org'}
        article = {'id': 'official-example', 'repo': 'official/Example', 'state': 'READY', 'published': False}
        with patch('app.jev_decision.proposal', return_value={'decision': 'ALLOW'}), \
             patch.object(inbox, 'analyze_media', return_value={'project_names': ['Example'], 'transcript': 'Example', 'coverage': 'DIRECT_AUDIO'}), \
             patch.object(inbox, 'public_discovery', return_value={}), patch.object(inbox, 'public_metadata', return_value={}), \
             patch.object(rn, 'github', return_value={'items': [candidate], 'total_count': 1}), \
             patch.object(inbox, 'homepage_confirms_repository', return_value=True), patch.object(inbox, 'research', return_value={'repo':'official/Example'}), \
             patch.object(inbox, 'build', return_value=article), patch.object(inbox, 'generate_json') as ai:
            inbox.process(item)
        ai.assert_not_called(); self.assertEqual(rn.read()['instagram_inbox'][0]['status'], 'READY')

    def test_unknown_sender_metadata_is_not_ingested(self):
        event = self.event(); event['entry'][0]['messaging'][0]['sender']['id'] = 'unknown'
        event['entry'][0]['messaging'][0]['message']['extra'] = {'password': 'private-fixture'}
        self.assertEqual(inbox.receive(event), []); self.assertNotIn('private-fixture', json.dumps(rn.read()))


if __name__ == '__main__': unittest.main()
