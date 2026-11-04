import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import database as db

try:
    from app import llm
except ImportError:
    llm = None
needs_deps = unittest.skipIf(llm is None, "app dependencies not installed")


class LocalOnlyTest(unittest.TestCase):
    def setUp(self):
        db.init_db()
        self.parent = db.create_folder("Секретное")
        self.child = db.create_folder("Вложенная", self.parent["id"])
        self.inside = db.create_meeting("Внутри", "a.wav", "/tmp/a.wav")["id"]
        self.outside = db.create_meeting("Снаружи", "b.wav", "/tmp/b.wav")["id"]
        db.update_meeting_fields(self.inside, folder_id=self.child["id"])

    def tearDown(self):
        for mid in (self.inside, self.outside):
            db.delete_meeting(mid)
        db.delete_folder(self.child["id"])
        db.delete_folder(self.parent["id"])

    def test_folder_mark_covers_subfolders(self):
        self.assertFalse(db.is_local_only(db.get_meeting(self.inside)))
        db.update_folder(self.parent["id"], local_only=True)
        self.assertTrue(db.get_folder(self.parent["id"])["local_only"])
        self.assertTrue(db.is_local_only(db.get_meeting(self.inside)))
        self.assertFalse(db.is_local_only(db.get_meeting(self.outside)))
        self.assertIn(self.inside, db.local_only_ids())
        self.assertNotIn(self.outside, db.local_only_ids())

    def test_recording_mark(self):
        db.update_meeting_fields(self.outside, local_only=1)
        self.assertTrue(db.get_meeting(self.outside)["local_only"])
        self.assertIn(self.outside, db.local_only_ids())
        row = next(m for m in db.list_meetings() if m["id"] == self.outside)
        self.assertIs(row["local_only"], True)


@needs_deps
class LocalOnlyTargetTest(unittest.TestCase):
    def setUp(self):
        db.init_db()
        db.update_settings({"llm_provider": "cloud", "llm_cloud_consent": "true", "llm_cloud_provider": "anthropic"})

    def tearDown(self):
        db.update_settings({"llm_provider": "ollama"})

    def test_cloud_gives_way_to_ollama(self):
        with mock.patch("app.llm._ollama_target", return_value="ollama") as local, \
                mock.patch("app.llm._cloud_target", return_value="cloud"):
            self.assertEqual(llm.target(), "cloud")
            self.assertEqual(llm.target(local_only=True), "ollama")
            local.assert_called_once()
            with self.assertRaises(llm.LlmError):
                llm.target("cloud", local_only=True)

    def test_token_estimate(self):
        self.assertAlmostEqual(llm.estimate_tokens("а" * 1000), 401, delta=2)
        self.assertAlmostEqual(llm.estimate_tokens("a" * 1000), 251, delta=2)


@needs_deps
class DiskApiTest(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient

            from app import main
        except ImportError:
            self.skipTest("fastapi not installed")
        self.main, self.TestClient = main, TestClient

    def test_recording_refused_when_disk_is_full(self):
        main = self.main
        full = mock.Mock(free=100 * 1024 * 1024)
        with mock.patch.object(main, "enqueue_meeting_job"), \
                self.TestClient(main.app, base_url="http://127.0.0.1:8793") as c:
            c.get(f"/?token={main.SESSION_TOKEN}")
            self.assertFalse(c.get("/api/disk").json()["critical"])
            with mock.patch("app.main.shutil.disk_usage", return_value=full):
                st = c.get("/api/disk").json()
                self.assertTrue(st["critical"] and st["low"])
                self.assertEqual(c.post("/api/record/page/start").status_code, 507)


@needs_deps
class GpuSharingTest(unittest.TestCase):
    def test_caption_model(self):
        from app.live import caption_model

        installed = {"large-v3-turbo", "large-v3"}
        with mock.patch("app.model_manager.is_whisper_model_installed", side_effect=lambda m: m in installed):
            hw = {"vram_total_gb": 8, "recommended_device": "cuda"}
            s = {"whisper_model": "large-v3", "device": "cuda"}
            self.assertEqual(caption_model(s, hw), "large-v3-turbo")
            self.assertEqual(caption_model({**s, "live_whisper_model": "large-v3"}, hw), "large-v3")
            self.assertEqual(caption_model({**s, "live_whisper_model": "gigaam-v3"}, hw), "large-v3-turbo")
            installed.discard("large-v3-turbo")
            self.assertEqual(caption_model(s, hw), "large-v3")

    def test_job_waits_while_captions_hold_the_gpu(self):
        from app import transcriber

        calls = {"n": 0}

        def sessions():
            calls["n"] += 1
            return 1 if calls["n"] <= 2 else 0  # the recording ends after two checks

        with mock.patch("app.live.active_session_count", side_effect=sessions), \
                mock.patch.object(transcriber, "_free_vram_gb", return_value=1.0), \
                mock.patch.object(transcriber, "update_meeting_progress") as progress, \
                mock.patch.object(transcriber, "_check_cancel"), \
                mock.patch.object(transcriber.time, "sleep") as sleep:
            transcriber._wait_for_vram_after_live(1, "large-v3")
        self.assertEqual(sleep.call_count, 2)
        self.assertIn("субтитрами", progress.call_args_list[0].kwargs["stage_text"])
        with mock.patch("app.live.active_session_count", return_value=1), \
                mock.patch.object(transcriber, "_free_vram_gb", return_value=20.0), \
                mock.patch.object(transcriber.time, "sleep") as sleep:
            transcriber._wait_for_vram_after_live(1, "large-v3")
        sleep.assert_not_called()


class ModelDownloadForJobTest(unittest.TestCase):
    """A recording processed with a Whisper model that is not downloaded yet downloads it first."""

    def setUp(self):
        from app import model_manager

        self.mm = model_manager
        self.addCleanup(self.mm._setup_state.update, {"active": False, "error": ""})

    def test_downloads_into_the_app_folder_with_progress(self):
        seen = []

        def download(repo_id, revision, target_dir, label, base_pct, span_pct, on_progress=None):
            self.assertTrue(self.mm._setup_state["active"])  # the settings show this download
            on_progress(10.0, 100.0)

        with mock.patch.object(self.mm, "is_whisper_model_installed", return_value=False), \
                mock.patch.object(self.mm, "_download_hf_repo_with_progress", side_effect=download) as dl:
            self.mm.ensure_whisper_model("large-v3", lambda mb, total: seen.append((mb, total)))
        self.assertEqual(dl.call_args.kwargs["repo_id"], "Systran/faster-whisper-large-v3")
        self.assertRegex(dl.call_args.kwargs["revision"], r"^[0-9a-f]{40}$")  # a fixed commit, not main
        self.assertEqual(seen, [(10.0, 100.0)])
        self.assertFalse(self.mm._setup_state["active"])

    def test_a_failure_frees_the_downloader(self):
        with mock.patch.object(self.mm, "is_whisper_model_installed", return_value=False), \
                mock.patch.object(self.mm, "_download_hf_repo_with_progress", side_effect=OSError("no network")):
            with self.assertRaises(OSError):
                self.mm.ensure_whisper_model("large-v3")
        self.assertFalse(self.mm._setup_state["active"])
        self.assertIn("no network", self.mm._setup_state["error"])

    def test_waits_for_a_download_already_running(self):
        self.mm._setup_state["active"] = True
        checks = {"n": 0}

        def installed(model_id):
            checks["n"] += 1
            return checks["n"] > 2  # the other download (the same model) ends meanwhile

        with mock.patch.object(self.mm, "is_whisper_model_installed", side_effect=installed), \
                mock.patch.object(self.mm.time, "sleep"), \
                mock.patch.object(self.mm, "_download_hf_repo_with_progress") as dl:
            self.mm.ensure_whisper_model("large-v3")
        dl.assert_not_called()

    def test_a_downloaded_model_is_left_alone(self):
        with mock.patch.object(self.mm, "is_whisper_model_installed", return_value=True), \
                mock.patch.object(self.mm, "_download_hf_repo_with_progress") as dl:
            self.mm.ensure_whisper_model("large-v3")
        dl.assert_not_called()


class ScreenCaptureTest(unittest.TestCase):
    def test_capture_command(self):
        from pathlib import Path

        from app.screen_capture import capture_command

        cmd = capture_command("ffmpeg", "desktop", Path("out.mkv"))
        self.assertEqual(cmd[cmd.index("-i") + 1], "desktop")
        self.assertIn("gdigrab", cmd)
        cmd = capture_command("ffmpeg", "Zoom Meeting", Path("out.mkv"))
        self.assertEqual(cmd[cmd.index("-i") + 1], "title=Zoom Meeting")

    @unittest.skipUnless(__import__("shutil").which("ffmpeg"), "no ffmpeg on PATH")
    def test_screen_is_joined_with_both_sounds(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path

        try:
            from app.main import screen_mix_command
        except ImportError:
            self.skipTest("fastapi not installed")
        d = Path(tempfile.mkdtemp())
        run = lambda *a: subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *a], check=True)
        run("-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(d / "s.mkv"))
        run("-f", "lavfi", "-i", "sine=frequency=440", "-t", "2", str(d / "mic.webm"))
        run("-f", "lavfi", "-i", "sine=frequency=880", "-t", "2", str(d / "sys.wav"))
        for audio in ([], [d / "sys.wav"], [d / "mic.webm", d / "sys.wav"]):
            dest = d / f"out{len(audio)}.mp4"
            subprocess.run(screen_mix_command("ffmpeg", d / "s.mkv", audio, dest), check=True)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(dest)],
                                   capture_output=True, text=True, check=True)
            kinds = sorted(st["codec_type"] for st in json.loads(probe.stdout)["streams"])
            self.assertEqual(kinds, ["audio", "video"] if audio else ["video"])


@needs_deps
class UpdateSourceTest(unittest.TestCase):
    def test_only_this_repository_and_digests_must_agree(self):
        import httpx

        from app import updater

        base = updater.DOWNLOAD_PREFIX + "v9.0.0/"
        release = {"tag_name": "v9.0.0", "assets": [
            {"name": "Verbaliox-v9.0.0.zip", "browser_download_url": base + "Verbaliox-v9.0.0.zip", "digest": "sha256:" + "a" * 64},
            {"name": "SHA256SUMS.txt", "browser_download_url": "https://evil.example/SHA256SUMS.txt"},
        ]}
        real = httpx.Client
        transport = httpx.MockTransport(lambda req: httpx.Response(200, json=release))
        db.init_db()
        with mock.patch("httpx.Client", side_effect=lambda **kw: real(transport=transport, **kw)):
            latest = updater.check(force=True)["latest"]
        self.assertEqual(latest["zip_url"], base + "Verbaliox-v9.0.0.zip")
        self.assertIsNone(latest["sums_url"])  # a file from another host is ignored
        self.assertEqual(latest["zip_digest"], "a" * 64)

        sums = f"{'b' * 64}  Verbaliox-v9.0.0.zip\n"
        transport = httpx.MockTransport(lambda req: httpx.Response(200, text=sums))
        # the checksums are compared here; the signature has its tests in tests/test_updater.py
        with mock.patch("httpx.Client", side_effect=lambda **kw: real(transport=transport, **kw)), \
                mock.patch.object(updater, "check_signature"):
            updater._download({**latest, "sums_url": base + "SHA256SUMS.txt"})
        self.assertIn("не совпадают", updater.status()["download"]["error"])


if __name__ == "__main__":
    unittest.main()


class PinnedDownloadsTest(unittest.TestCase):
    """What the app downloads is fixed: the GPU wheel by a hash, Hugging Face models by a commit."""

    def test_the_gpu_wheel_has_a_hash_for_the_pinned_onnxruntime(self):
        import re
        from pathlib import Path

        from app.onnx_gpu import WHEEL_HASHES

        req = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
        version = re.search(r"^onnxruntime==([\w.]+)", req, flags=re.M).group(1)
        self.assertIn((version, "cp311"), WHEEL_HASHES)  # setup.bat and the release build use Python 3.11

    def test_hugging_face_downloads_name_a_revision(self):
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app"
        # Not pinned yet: the commit has to be read on the PC (Hugging Face is closed to the cloud session)
        known = set()
        loose = []
        for f in sorted(root.glob("*.py")):
            for m in re.finditer(r"\b(?:hf_hub_download|snapshot_download)\(([^()]*(?:\([^()]*\)[^()]*)*)\)", f.read_text(encoding="utf-8")):
                args = m.group(1)
                if "revision=" not in args and "*args" not in args and (f.name, args.strip()) not in known:
                    loose.append(f"{f.name}: {args.strip()[:80]}")
        self.assertEqual(loose, [])


class FfmpegOnStartTest(unittest.TestCase):
    """FFmpeg is fetched by itself at the start when there is none (Windows)."""

    def test_downloads_only_when_missing_on_windows(self):
        from app import ffmpeg_manager as fm

        with mock.patch.object(fm.sys, "platform", "win32"), mock.patch.object(fm, "start_ffmpeg_download") as start, \
                mock.patch.dict(fm.os.environ, {"VERBALIOX_NO_FFMPEG_AUTO": ""}):
            with mock.patch.object(fm, "find_tool", return_value=None):
                self.assertTrue(fm.ensure_on_start())
            with mock.patch.object(fm, "find_tool", return_value="C:/bin/ffmpeg.exe"):
                self.assertFalse(fm.ensure_on_start())
        self.assertEqual(start.call_count, 1)
        with mock.patch.object(fm.sys, "platform", "linux"), mock.patch.object(fm, "find_tool", return_value=None), \
                mock.patch.object(fm, "start_ffmpeg_download") as start:
            self.assertFalse(fm.ensure_on_start())
            start.assert_not_called()


class SetupWindowTest(unittest.TestCase):
    """The setup window of the launcher (build_exe.py) reads the steps setup.bat writes."""

    def test_setup_bat_speaks_to_the_window(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        bat = (root / "setup.bat").read_bytes()
        self.assertNotIn(b"\n", bat.replace(b"\r\n", b""))  # cmd needs CRLF for its labels
        text = bat.decode("ascii")
        for step in ("uv", "venv", "packages"):
            self.assertIn(f"echo ##STEP {step}", text)
            self.assertIn(f'"##STEP {step}"', (root / "build_exe.py").read_text(encoding="utf-8"))
        self.assertIn('if not defined QUIET pause', text)

    def test_ollama_window_is_closed_after_its_install(self):
        from app import ollama_client as oc

        with mock.patch.object(oc.sys, "platform", "win32"), mock.patch.object(oc.subprocess, "run") as run, \
                mock.patch.object(oc.time, "sleep"):
            oc._close_ollama_app(seconds=0.01)
        self.assertTrue(run.called)
        self.assertEqual(run.call_args[0][0], ["taskkill", "/F", "/IM", "ollama app.exe"])


class InstallerTest(unittest.TestCase):
    """installer/verbaliox.iss: per user, and its file goes out with the release and its checksums."""

    def test_installer_is_per_user_and_released(self):
        from pathlib import Path

        root = Path(__file__).resolve().parent.parent
        iss = (root / "installer" / "verbaliox.iss").read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", iss)  # no administrator rights; the app updates itself
        self.assertNotIn("PrivilegesRequiredOverridesAllowed", iss)  # and no switch to Program Files
        self.assertTrue((root / "installer" / "verbaliox.iss").read_bytes().startswith(b"\xef\xbb\xbf"))  # Russian texts as UTF-8
        from app.autostart import FORMER_VALUE_NAME, VALUE_NAME

        for name in (VALUE_NAME, FORMER_VALUE_NAME):  # "Start with Windows" goes with the program
            self.assertIn(f'ValueName: "{name}"; Flags: uninsdeletevalue', iss)
        self.assertIn("AppMutex=Local\\Verbaliox.Desktop.Window", iss)
        self.assertIn('"Local\\\\Verbaliox.Desktop.Window"', (root / "run.py").read_text(encoding="utf-8"))
        self.assertIn("OutputBaseFilename=Verbaliox-Setup-v{#AppVersion}", iss)
        wf = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("installer\\verbaliox.iss", wf)
        self.assertIn("Verbaliox-Setup-*.exe", wf)
        self.assertIn('$setup.FullName -Algorithm SHA256', wf)  # in SHA256SUMS.txt, so signed


class DisplaySanitizeTest(unittest.TestCase):
    """Colours, times and ids from the database reach markup only as #rrggbb and numbers (a backup
    restored from elsewhere could carry markup in them)."""

    def test_hostile_values_are_neutralized(self):
        from app.database import _sanitize_display

        d = {"speakers": {"S1": {"name": "A", "color": '"><button data-click="fetch">'}, "S2": {"color": "#30D158"}},
             "segments": [{"id": "1 onclick", "start": '"><b>', "end": "12.5", "text": "x"}]}
        _sanitize_display(d)
        self.assertEqual(d["speakers"]["S1"]["color"], "#0A84FF")
        self.assertEqual(d["speakers"]["S2"]["color"], "#30D158")
        self.assertEqual((d["segments"][0]["id"], d["segments"][0]["start"], d["segments"][0]["end"]), (0, 0.0, 12.5))


class ModelSetupSelectTest(unittest.TestCase):
    """A Whisper model downloaded as the Russian model (select=False) does not replace the main one."""

    def _run(self, select):
        from app import model_manager as mm

        class _Now:
            def __init__(self, target, daemon=None):
                self.target = target

            def start(self):
                self.target()

        with mock.patch.object(mm, "_download_hf_repo_with_progress"), \
                mock.patch.object(mm, "update_settings") as upd, \
                mock.patch.object(mm.threading, "Thread", _Now):
            mm._setup_state["active"] = False
            mm.start_models_setup(mm.WHISPER_CATALOG[0]["id"], install_diarizer=False, select=select)
        return upd

    def test_select_flag(self):
        self.assertTrue(self._run(True).called)
        self.assertFalse(self._run(False).called)


class RequirementsMarkTest(unittest.TestCase):
    """.venv records the requirements.txt it was installed from; the launcher updates it on a mismatch."""

    def test_mark_written_and_kept(self):
        import tempfile
        from pathlib import Path

        from app.pyenv import REQUIREMENTS_MARK, mark_requirements, requirements_hash

        with tempfile.TemporaryDirectory() as d:
            app = Path(d)
            (app / "requirements.txt").write_text("a==1\n", encoding="utf-8")
            mark_requirements(app)  # no .venv: nothing to mark
            self.assertFalse((app / REQUIREMENTS_MARK).exists())
            (app / ".venv").mkdir()
            mark_requirements(app, only_if_missing=True)
            first = (app / REQUIREMENTS_MARK).read_text(encoding="ascii")
            self.assertEqual(first, requirements_hash(app))
            (app / "requirements.txt").write_text("a==2\n", encoding="utf-8")
            mark_requirements(app, only_if_missing=True)  # a mark from an older install stays as it is
            self.assertEqual((app / REQUIREMENTS_MARK).read_text(encoding="ascii"), first)
            mark_requirements(app)
            self.assertNotEqual((app / REQUIREMENTS_MARK).read_text(encoding="ascii"), first)

    def test_setup_and_launcher_use_the_same_mark(self):
        from pathlib import Path

        import build_exe
        from app.pyenv import REQUIREMENTS_MARK

        root = Path(__file__).resolve().parent.parent
        bat = (root / "setup.bat").read_text(encoding="utf-8")
        self.assertIn(REQUIREMENTS_MARK.name, bat)
        self.assertIn("if not defined UPDATE rmdir /s /q .venv", bat)  # an update never removes .venv
        self.assertIn('"' + REQUIREMENTS_MARK.name + '"', build_exe.CS_SOURCE)
        self.assertIn("RequirementsChanged(baseDir)", build_exe.CS_SOURCE)


class SpeechModelSettingTest(unittest.TestCase):
    """The speech model settings take only models of the catalog (D3)."""

    def test_only_catalog_models(self):
        from app.settings_schema import clean as validate_setting

        self.assertEqual(validate_setting("whisper_model", "large-v3-turbo"), "large-v3-turbo")
        self.assertEqual(validate_setting("speech_model_ru", "gigaam-v3"), "gigaam-v3")
        self.assertEqual(validate_setting("speech_model_ru", ""), "")
        self.assertEqual(validate_setting("live_whisper_model", "auto"), "auto")
        for key in ("whisper_model", "speech_model_ru", "live_whisper_model"):
            with self.assertRaises(ValueError):
                validate_setting(key, "someone/evil-repo")
