"""Offline regressions for the official DramaClaw contract; no model calls."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit

import requests

_spec = importlib.util.spec_from_file_location("zar_dramaclaw_client", Path(__file__).resolve().parents[1] / "app" / "dramaclaw_client.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
DramaClawClient, DramaClawError = _module.DramaClawClient, _module.DramaClawError
ROOT = "/api/v1/projects/p1"
EP = ROOT + "/episodes/1"
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"


class Response:
    def __init__(self, data=None, status=200, content=b"", headers=None):
        self.payload, self.status_code = data, status
        self.content = content
        self.headers = headers or {"Content-Type": "video/mp4"}
        self.closed = False

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload

    def iter_content(self, chunk_size):
        yield self.content[:5]
        yield self.content[5:]

    def close(self):
        self.closed = True


def ok(data=None, **extra):
    return Response({"ok": True, "data": data, **extra})


class ScriptedSession:
    def __init__(self, expected):
        self.expected = list(expected)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.expected:
            raise AssertionError("Unexpected request: " + method + " " + url)
        wanted_method, wanted_path, result = self.expected.pop(0)
        assert (method, urlsplit(url).path) == (wanted_method, wanted_path), self.calls[-1]
        assert kwargs["allow_redirects"] is False
        if isinstance(result, Exception):
            raise result
        return result


class PipelineAPI:
    """Minimal independent fake implementing the observed REST resources."""
    def __init__(self, saved):
        self.saved = saved
        self.calls = []
        self.tasks = []
        self.effects = {}
        self.config = {"video_backend": "video-model"}
        self.episodes, self.chars, self.beats = [], [], []
        self.identity_image = ""
        self.colors, self.narrator, self.final = False, False, False
        self.uploaded = None

    def enqueue(self, task_type, effect, episode=1, scope=None, beat_num=None):
        task = {"task_type": task_type, "task_id": "task-" + str(len(self.tasks) + 1),
                "episode": episode, "scope": scope, "beat_num": beat_num, "status": "running"}
        self.tasks.append(task)
        self.effects[task["task_id"]] = effect
        return task

    def request(self, method, url, **kw):
        path = urlsplit(url).path
        self.calls.append((method, path, kw))
        assert kw["allow_redirects"] is False
        if method != "GET":
            assert self.saved and self.saved[-1].get("pending"), "Mutation preceded durable intent"
        if path == "/api/v1/projects" and method == "POST":
            return ok({"id": "p1", "project_id": "p1"})
        if path == ROOT and method == "PATCH":
            self.config.update(kw["json"])
            return ok(self.config)
        if path == ROOT and method == "GET":
            return ok(self.config)
        if path == ROOT + "/ingest/upload":
            self.uploaded = kw["files"]["file"][1]
            return ok({"filename": kw["files"]["file"][0]})
        if path == ROOT + "/ingest/start":
            def effect():
                self.episodes = [{"number": 1, "identity_ids": []}]
                self.chars = [{"name": "Luna", "portrait_url": ""}]
            return ok(**self.enqueue("ingest_fast", effect, episode=0))
        if path == ROOT + "/tasks":
            for task in self.tasks:
                effect = self.effects.pop(task["task_id"], None)
                if effect:
                    effect()
                    task["status"] = "completed"
            return ok(copy.deepcopy(self.tasks))
        if path == ROOT + "/episodes":
            return ok(copy.deepcopy(self.episodes))
        if path == ROOT + "/characters":
            return ok(copy.deepcopy(self.chars))
        if path == EP + "/identities/plan":
            return ok(**self.enqueue("identity_planner", lambda: self.episodes[0].update(identity_ids=["i1"])))
        if path == ROOT + "/characters/Luna/portrait-async":
            return ok(**self.enqueue("character_portrait", lambda: self.chars[0].update(portrait_url="/portrait.png"), episode=0, scope="character:Luna:portrait"))
        if path == ROOT + "/characters/Luna/identities":
            return ok([{"identity_id": "i1", "identity_name": "viajera", "image_url": self.identity_image}])
        if path == ROOT + "/characters/Luna/identities/i1/generate-async":
            return ok(**self.enqueue("identity_image", lambda: setattr(self, "identity_image", "/identity.png"), episode=0, scope="character:Luna:identity:viajera"))
        if path == EP + "/beats":
            return ok(copy.deepcopy(self.beats))
        if path == EP + "/script/generate":
            def effect():
                self.beats = [{"beat_number": 1, "narration_segment": "Luna descubre el horizonte."}]
            return ok(**self.enqueue("script_writer", effect))
        if path == EP + "/script":
            return ok({"sketch_colors": {"i1": "red"} if self.colors else {}})
        if path == EP + "/sketches/assign-colors":
            self.colors = True
            return ok({"colors": {"i1": "red"}})
        if path == EP + "/sketches/generate":
            assert kw["json"]["grid_index"] == -1
            task = self.enqueue("sketch_grid_generation", lambda: self.beats[0].update(sketch_url="/sketch.png"), scope="grid_0")
            return ok({"tasks": [dict(task)], "rejected": []}, task_type="sketch_grid_generation")
        if path == EP + "/sketches/detect-identities":
            self.beats[0]["detected_identities"] = ["i1"]
            return ok({"detections": {"1": ["i1"]}})
        if path == EP + "/optimize/video-global":
            return ok(**self.enqueue("global_optimize_video", lambda: self.beats[0].update(video_mode="i2v", video_prompt="The traveler walks.")))
        if path == EP + "/beats/regenerate":
            scope = "1x1_2-3__" + hashlib.sha1(b"1").hexdigest()[:12]
            return ok(**self.enqueue("selected_regen", lambda: self.beats[0].update(frame_url="/frame.png"), scope=scope))
        if path == ROOT + "/narrator-voice":
            return ok({"reference_url": "/voice.mp3" if self.narrator else ""})
        if path == ROOT + "/narrator-voice/upload":
            assert kw["files"]["file"][1] == b"voice-reference"
            self.narrator = True
            return ok({"reference_url": "/voice.mp3"})
        if path == EP + "/audio/generate":
            return ok(**self.enqueue("audio_generation_indextts2", lambda: self.beats[0].update(audio_url="/audio.mp3")))
        if path == ROOT + "/video-backends":
            return ok([{"value": "video-model", "is_default": True, "dialogue_only": False}])
        if path == EP + "/beats/1/video":
            return ok(**self.enqueue("single_video", lambda: self.beats[0].update(video_url="/beat.mp4"), beat_num=1))
        if path == EP + "/videos/compose":
            return ok(**self.enqueue("compose_episode", lambda: setattr(self, "final", True)))
        if path == EP + "/final":
            return ok({"exists": self.final, "filename": "ep001_final.mp4", "video_url": "/static/projects/p1/videos/episodes/ep001_final.mp4"})
        if path == EP + "/export/video":
            return Response(content=MP4)
        raise AssertionError("Unexpected endpoint: " + method + " " + path)


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.saved = []

    def persist(self, cp):
        self.saved.append(copy.deepcopy(cp))

    def client(self, session, **kwargs):
        return DramaClawClient("https://api.example.test", session=session,
                               public_url="https://editor.example.test", **kwargs)

    def test_project_name_matches_provider_contract(self):
        session=ScriptedSession([('POST','/api/v1/projects',ok({'project_id':'p1'}))])
        cp=self.client(session).advance({},'brief',self.persist)
        self.assertRegex(session.calls[0][2]['json']['name'],r'^[a-zA-Z0-9_]+$')
        self.assertEqual(cp['submission_state'],'PROJECT_CREATED')

    def test_rejected_legacy_name_repaired_once(self):
        session=ScriptedSession([('POST','/api/v1/projects',ok({'id':'p1'}))])
        cp=self.client(session).advance({'stage':'project','project_name':'ZAR_old','last_submission_error':'http_400'},'brief',self.persist)
        self.assertEqual(cp['project_id'],'p1')
        legacy={'stage':'project','project_name':'ZAR-old','last_submission_error':'http_400','pending':{'stage':'project'}}
        api=ScriptedSession([('POST','/api/v1/projects',ok({'id':'p2'}))])
        result=self.client(api).advance(legacy,'brief',self.persist)
        self.assertEqual(result['project_name'],'ZAR_old')
        self.assertEqual(result['project_id'],'p2')
        self.assertEqual(len(api.calls),1)

    def test_async_creation_keeps_id_and_never_repeats_post(self):
        api=ScriptedSession([('POST','/api/v1/projects',ok({'submission_id':'accepted-1'}))])
        cp=self.client(api).advance({},'brief',self.persist)
        self.assertEqual(cp['submission_state'],'REQUEST_ACCEPTED')
        self.assertEqual(cp['submission_ids'],{'submission_id':'accepted-1'})
        for i in range(2):
            poll=ScriptedSession([('GET','/api/v1/projects',ok([]))])
            cp=self.client(poll).advance(json.loads(json.dumps(cp)),'brief',self.persist)
            self.assertEqual(cp['submission_state'],'PROCESSING')
            self.assertNotEqual(cp['status'],'blocked')
            self.assertEqual([c[0] for c in poll.calls],['GET'])
        poll=ScriptedSession([('GET','/api/v1/projects',ok([{'project_id':'p1','name':cp['project_name']}]))])
        cp=self.client(poll).advance(cp,'brief',self.persist)
        self.assertEqual(cp['project_id'],'p1')
        self.assertNotIn('pending',cp)

    def test_definitive_http400_is_specific_not_unknown(self):
        api=ScriptedSession([('POST','/api/v1/projects',Response({},400))])
        cp=self.client(api).advance({},'brief',self.persist)
        self.assertEqual(cp['error_code'],'http_400')
        self.assertNotIn('pending',cp)
        self.assertNotIn('video_url',cp)

    def test_full_pipeline_preserves_brief_and_resumes_after_every_call(self):
        api = PipelineAPI(self.saved)
        client = self.client(api)
        brief = "Historia completa áéíóú\n" + "Detalle importante. " * 4000 + "FIN INTEGRO"
        cp = {}
        voices = []
        def narrator():
            voices.append(True)
            return b"voice-reference", "audio/mpeg", "elevenlabs"
        for _ in range(100):
            before = len([c for c in api.calls if c[0] != "GET"])
            cp = client.advance(cp, brief, self.persist, narrator=narrator)
            after = len([c for c in api.calls if c[0] != "GET"])
            self.assertLessEqual(after - before, 1)
            self.assertNotEqual(cp["status"], "blocked", cp)
            cp = json.loads(json.dumps(self.saved[-1]))  # new process/refresh
            if cp["status"] == "done":
                break
        self.assertEqual(cp["status"], "done")
        self.assertEqual(api.uploaded.decode(), "第1章\n\n" + brief)
        self.assertEqual(voices, [True])
        self.assertEqual(cp["project_id"], "p1")
        self.assertEqual(cp["editor_url"], "https://editor.example.test/projects/p1/episodes")
        self.assertIn("/videos/episodes/ep001_final.mp4", cp["video_url"])
        self.assertTrue(any(t["task_type"] == "audio_generation_indextts2" for t in cp["tasks"]))
        self.assertFalse(any("/tts/generate" in c[1] for c in api.calls))
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "result.mp4"
            client.download_final(cp, target)
            self.assertEqual(target.read_bytes(), MP4)

    def test_timeout_after_create_recovers_same_project_without_post(self):
        session = ScriptedSession([("POST", "/api/v1/projects", requests.Timeout("secret-key"))])
        cp = self.client(session).advance({}, "brief", self.persist)
        self.assertEqual(cp["pending"]["stage"], "project")
        recovery = ScriptedSession([("GET", "/api/v1/projects", ok([{"id": "p1", "name": cp["project_name"]}]))])
        cp = self.client(recovery).advance(json.loads(json.dumps(cp)), "brief", self.persist)
        self.assertEqual(cp["stage"], "configure")
        self.assertEqual(cp["project_id"], "p1")
        self.assertTrue(all(c[0] == "GET" for c in recovery.calls))
        self.assertNotIn("secret-key", json.dumps(cp))

    def test_unknown_submission_never_repeats_paid_post(self):
        first = ScriptedSession([("GET", EP + "/beats", ok([])), ("GET", ROOT + "/tasks", ok([])),
                                 ("POST", EP + "/script/generate", requests.Timeout())])
        cp = self.client(first).advance({"stage": "script", "project_id": "p1"}, "brief", self.persist)
        for _ in range(2):
            session = ScriptedSession([("GET", EP + "/beats", ok([])), ("GET", ROOT + "/tasks", ok([]))])
            cp = self.client(session).advance(cp, "brief", self.persist)
            self.assertEqual(cp["error_code"], "submission_unknown")
            self.assertIn("pending", cp)
            self.assertTrue(all(c[0] == "GET" for c in session.calls))

    def test_task_recovery_polls_original_id_then_advances(self):
        first = ScriptedSession([("GET", EP + "/beats", ok([])), ("GET", ROOT + "/tasks", ok([])),
                                 ("POST", EP + "/script/generate", requests.Timeout())])
        cp = self.client(first).advance({"stage": "script", "project_id": "p1"}, "brief", self.persist)
        task = {"task_type": "script_writer", "task_id": "job-a", "episode": 1, "status": "running"}
        session = ScriptedSession([("GET", EP + "/beats", ok([])), ("GET", ROOT + "/tasks", ok([task])),
                                   ("GET", ROOT + "/tasks", ok([task])),
                                   ("GET", ROOT + "/tasks", ok([{**task, "status": "completed"}]))])
        client = self.client(session)
        cp = client.advance(cp, "brief", self.persist)
        self.assertEqual(cp["active_task"]["task_id"], "job-a")
        cp = client.advance(cp, "brief", self.persist)
        self.assertEqual(cp["stage"], "script")
        cp = client.advance(cp, "brief", self.persist)
        self.assertEqual(cp["stage"], "colors")
        self.assertEqual(len(cp["tasks"]), 1)
        self.assertTrue(all(c[0] == "GET" for c in session.calls))

    def test_explicit_episode_plan_uses_chapters_and_checks_result(self):
        task = {"task_id": "plan-1", "task_type": "build_episodes", "episode": 0, "status": "completed"}
        session = ScriptedSession([("GET", ROOT + "/episodes", ok([])), ("GET", ROOT + "/tasks", ok([])),
                                   ("POST", ROOT + "/episodes/plan", ok(**task)),
                                   ("GET", ROOT + "/tasks", ok([task])),
                                   ("GET", ROOT + "/episodes", ok([{"number": 1}]))])
        client = self.client(session)
        cp = client.advance({"stage": "episodes", "project_id": "p1"}, "brief", self.persist)
        self.assertEqual(session.calls[2][2]["json"], {"target_episodes": 1, "planning_mode": "chapters"})
        cp = client.advance(cp, "brief", self.persist)
        self.assertEqual(cp["stage"], "episodes")
        cp = client.advance(cp, "brief", self.persist)
        self.assertEqual(cp["stage"], "characters")

    def test_corrupt_stage_never_resets_to_create_project(self):
        session = ScriptedSession([])
        client = self.client(session)
        cp = {"stage": "unknown"}
        for _ in range(2):
            cp = client.advance(cp, "brief", self.persist)
            self.assertEqual(cp["error_code"], "checkpoint")
        self.assertEqual(session.calls, [])

    def test_expired_task_recovers_from_existing_final_resource(self):
        record = {"task_id": "compose-1", "task_type": "compose_episode", "stage": "compose", "episode": 1}
        cp = {"stage": "compose", "project_id": "p1", "active_task": record, "tasks": [dict(record)]}
        session = ScriptedSession([("GET", ROOT + "/tasks", ok([])), ("GET", EP + "/final", ok({"exists": True}))])
        cp = self.client(session).advance(cp, "brief", self.persist)
        self.assertEqual(cp["stage"], "export")
        self.assertNotIn("video_url", cp)

    def test_storyboard_tracks_fanout_and_blocks_partial_without_resubmission(self):
        tasks = [{"task_id": "s1", "task_type": "sketch_grid_generation", "episode": 1, "scope": "grid_0", "status": "completed"},
                 {"task_id": "s2", "task_type": "sketch_grid_generation", "episode": 1, "scope": "grid_1", "status": "completed"}]
        beats = [{"beat_number": 1, "sketch_url": "/one.png"}, {"beat_number": 2, "sketch_url": ""}]
        session = ScriptedSession([("GET", EP + "/beats", ok(beats)), ("GET", ROOT + "/tasks", ok([])),
            ("POST", EP + "/sketches/generate", ok({"tasks": tasks, "rejected": [{"scope": "grid_2"}]})),
            ("GET", ROOT + "/tasks", ok(tasks)), ("GET", EP + "/beats", ok(beats)),
            ("GET", ROOT + "/tasks", ok(tasks)), ("GET", EP + "/beats", ok(beats))])
        client = self.client(session)
        cp = client.advance({"stage": "storyboard", "project_id": "p1"}, "brief", self.persist)
        self.assertEqual(len(cp["active_tasks"]), 2)
        self.assertTrue(cp["partial_submission"])
        cp = client.advance(cp, "brief", self.persist)
        self.assertEqual(cp["error_code"], "storyboard_incomplete")
        cp = client.advance(cp, "brief", self.persist)
        self.assertEqual(cp["status"], "blocked")
        self.assertEqual(len([c for c in session.calls if c[0] == "POST"]), 1)

    def test_failed_provider_result_is_sanitized(self):
        task = {"task_id": "job-a", "task_type": "script_writer", "stage": "script", "episode": 1}
        session = ScriptedSession([("GET", ROOT + "/tasks", ok([{**task, "status": "failed", "error": "api_key=DO-NOT-LEAK"}])),
                                   ("GET", EP + "/beats", ok([]))])
        cp = self.client(session).advance({"stage": "script", "project_id": "p1", "active_task": task}, "brief", self.persist)
        self.assertEqual(cp["error_code"], "task_failed")
        self.assertNotIn("DO-NOT-LEAK", json.dumps(cp))

    def test_final_must_be_confirmed_and_on_configured_origin(self):
        for final in [
            {"exists": False, "filename": "ep001_final.mp4"},
            {"exists": True, "filename": "ep001_final.mp4", "video_url": "https://evil.test/static/projects/p1/videos/episodes/ep001_final.mp4"},
            {"exists": True, "filename": "ep001_final.mp4", "video_url": "/static/projects/p1/videos/beats/ep001/beat_01.mp4"},
        ]:
            with self.subTest(final=final):
                session = ScriptedSession([("GET", EP + "/final", ok(final))])
                cp = self.client(session, token="test-token").advance({"stage": "export", "project_id": "p1"}, "brief", self.persist)
                self.assertEqual(cp["status"], "blocked")
                self.assertNotIn("video_url", cp)
                self.assertEqual(len(session.calls), 1)

    def test_health_is_bounded_and_never_reports_model_calls(self):
        session = ScriptedSession([("GET", "/api/v1/auth/me", ok({"username": "local"})),
                                   ("GET", "/api/v1/projects", ok([]))])
        result = self.client(session).health()
        self.assertTrue(result["ready"])
        self.assertEqual(result["error"], "")
        self.assertTrue(all(call[2]["timeout"] == 3 for call in session.calls))
        failing = ScriptedSession([("GET", "/api/v1/auth/me", Response({"error": "token-secret"}, status=403))])
        result = self.client(failing).health()
        self.assertFalse(result["ready"])
        self.assertNotIn("token-secret", json.dumps(result))

    def test_save_failure_prevents_remote_mutation(self):
        session = ScriptedSession([])
        def disk_full(cp):
            raise OSError("disk full")
        with self.assertRaises(OSError):
            self.client(session).advance({}, "brief", disk_full)
        self.assertEqual(session.calls, [])

    def test_brief_change_blocks_before_network(self):
        cp = {"stage": "script", "project_id": "p1", "brief_sha256": "different"}
        session = ScriptedSession([])
        cp = self.client(session).advance(cp, "changed brief", self.persist)
        self.assertEqual(cp["error_code"], "checkpoint")
        self.assertEqual(session.calls, [])

    def test_narrator_failure_is_not_retried_and_manual_voice_can_resume(self):
        calls = []
        def voice():
            calls.append(True)
            raise requests.Timeout("provider secret")
        session = ScriptedSession([("GET", ROOT + "/narrator-voice", ok({})),
                                   ("GET", ROOT + "/narrator-voice", ok({})),
                                   ("GET", ROOT + "/narrator-voice", ok({"reference_url": "/uploaded.mp3"}))])
        client = self.client(session)
        cp = client.advance({"stage": "narrator", "project_id": "p1"}, "brief", self.persist, narrator=voice)
        cp = client.advance(cp, "brief", self.persist, narrator=voice)
        self.assertEqual(calls, [True])
        self.assertEqual(cp["error_code"], "narrator_unknown")
        self.assertNotIn("provider secret", json.dumps(cp))
        cp = client.advance(cp, "brief", self.persist, narrator=voice)
        self.assertEqual(cp["stage"], "audio")

    def test_download_never_follows_redirect_or_accepts_non_mp4_or_oversize(self):
        cp = {"stage": "done", "project_id": "p1", "video_url": "https://ignored.test/not-used",
              "origin_sha256": hashlib.sha256(b"https://api.example.test").hexdigest()}
        for response, limit in [(Response(status=302, headers={"Location": "https://evil.test"}), 1024),
                                 (Response(content=b"<html>not media</html>"), 1024),
                                 (Response(content=MP4), 8)]:
            with self.subTest(status=response.status_code, limit=limit), tempfile.TemporaryDirectory() as directory:
                session = ScriptedSession([("GET", EP + "/export/video", response)])
                destination = Path(directory) / "film.mp4"
                destination.write_bytes(b"preserve-existing")
                with self.assertRaises(DramaClawError):
                    self.client(session, token="test-token").download_final(cp, destination, max_bytes=limit)
                self.assertEqual(destination.read_bytes(), b"preserve-existing")
                self.assertFalse(list(Path(directory).glob("*.part")))
                self.assertEqual(len(session.calls), 1)
                self.assertTrue(session.calls[0][1].startswith("https://api.example.test/"))


if __name__ == "__main__":
    unittest.main()
