"""The translators of live captions, Tencent Hy-MT3 (bench-report/translation-2026-11.md): which model «Качество»
and «Скорость» take, that a translator is never an analysis model, the repair of the 1.8B's broken chat
template, the prompt of its model card and the model offered by the video card."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    from app import live_translate, ollama_client
except ImportError:  # httpx/app dependencies are not installed (e.g. in the release CI job)
    live_translate = ollama_client = None

RAW_7B = "hf.co/tencent/Hy-MT3-7B-GGUF:Q4_K_M"
RAW_1_8B = "hf.co/tencent/Hy-MT3-1.8B-GGUF:Q4_K_M"
LOCAL_1_8B = "hy-mt3-1.8b:latest"


class _Resp:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}
        self.text = ""

    def json(self):
        return self._data

    def read(self):
        return b""


class _Ollama:
    """httpx.Client for /api/show, /api/create, /api/delete and /api/chat; records the requests."""

    def __init__(self, template="", chat="", tags=None, create_status=200):
        self.template, self.chat, self.tags, self.create_status = template, chat, tags, create_status
        self.posts, self.deleted = [], []

    def get(self, url, **k):
        if self.tags is None or not url.endswith("/api/tags"):
            raise ConnectionError("no list")  # the list given to the repair is used
        return _Resp(200, {"models": [{"name": n} for n in self.tags]})

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, json=None, **k):
        self.posts.append((url.rsplit("/api/", 1)[1], json))
        if url.endswith("/api/show"):
            return _Resp(200, {"template": self.template})
        if url.endswith("/api/chat"):
            return _Resp(200, {"message": {"content": self.chat}})
        if url.endswith("/api/create") and self.create_status != 200:
            return _Resp(self.create_status, {"error": "no space left"})
        return _Resp(200, {"status": "success"})

    def request(self, method, url, json=None, **k):
        self.deleted.append(json["model"])
        return _Resp(200)


@unittest.skipIf(live_translate is None, "app dependencies not installed")
class ModelChoicesTest(unittest.TestCase):
    def setUp(self):
        from app.database import init_db

        init_db()

    def _choices(self, installed, analysis="gemma4:e4b"):
        with mock.patch.object(live_translate, "installed_models", return_value=installed), \
                mock.patch("app.database.get_all_settings", return_value={"ollama_model": analysis}):
            c = live_translate.model_choices()
        return c["quality"], c["fast"]

    def test_without_a_translator_as_before(self):
        self.assertEqual(self._choices(["gemma4:e4b", "gemma4:e2b"]), ("gemma4:e4b", "gemma4:e2b"))
        # no small model: «Скорость» takes the model of «Качество»
        self.assertEqual(self._choices(["gemma4:e4b"]), ("gemma4:e4b", "gemma4:e4b"))

    def test_both_translators(self):
        self.assertEqual(self._choices(["gemma4:e4b", "gemma4:e2b", RAW_7B, LOCAL_1_8B]), (RAW_7B, LOCAL_1_8B))

    def test_only_the_small_translator(self):
        self.assertEqual(self._choices(["gemma4:e4b", "gemma4:e2b", LOCAL_1_8B]), (LOCAL_1_8B, LOCAL_1_8B))
        # the downloaded name, when its template was found right and it was kept
        self.assertEqual(self._choices(["gemma4:e4b", RAW_1_8B]), (RAW_1_8B, RAW_1_8B))

    def test_only_the_large_translator(self):
        self.assertEqual(self._choices(["gemma4:e4b", "gemma4:e2b", RAW_7B]), (RAW_7B, "gemma4:e2b"))
        self.assertEqual(self._choices([RAW_7B, "gemma4:e4b"]), (RAW_7B, RAW_7B))

    def test_the_analysis_model_is_never_a_translator(self):
        # only translators installed: the analysis model of the settings stays the quality fallback
        self.assertEqual(self._choices([LOCAL_1_8B], analysis="gemma4:e4b"), (LOCAL_1_8B, LOCAL_1_8B))

    def test_qwen_is_no_longer_offered(self):
        self.assertEqual(live_translate.FAST_MODEL_HINTS, ("gemma4:e2b",))

    def test_the_check_of_the_analysis_takes_no_translator(self):
        with mock.patch.object(live_translate, "installed_models", return_value=[LOCAL_1_8B]):
            self.assertIsNone(live_translate.small_chat_model())
        with mock.patch.object(live_translate, "installed_models", return_value=[LOCAL_1_8B, "gemma4:e2b"]):
            self.assertEqual(live_translate.small_chat_model(), "gemma4:e2b")


@unittest.skipIf(ollama_client is None, "app dependencies not installed")
class TranslateOnlyTest(unittest.TestCase):
    def setUp(self):
        from app.database import init_db

        init_db()

    def test_translators_are_not_analysis_models(self):
        models = ["gemma4:e4b", RAW_7B, LOCAL_1_8B, RAW_1_8B, "bge-m3:latest"]
        for m in (RAW_7B, LOCAL_1_8B, RAW_1_8B):
            self.assertTrue(ollama_client.is_translate_only_model(m))
        self.assertFalse(ollama_client.is_translate_only_model("gemma4:e4b"))
        self.assertEqual(ollama_client.chat_models(models), ["gemma4:e4b"])
        self.assertEqual(ollama_client.translate_models(models), ["gemma4:e4b", RAW_7B, LOCAL_1_8B, RAW_1_8B])

    def test_status_lists_translators_apart(self):
        on_disk = ["gemma4:e4b", RAW_7B, LOCAL_1_8B]
        with mock.patch.object(ollama_client, "_is_ollama_port_open", return_value=False), \
                mock.patch.object(ollama_client, "models_on_disk", return_value=on_disk), \
                mock.patch.object(ollama_client, "find_ollama_executable", return_value="ollama"), \
                mock.patch.object(ollama_client, "get_all_settings", return_value={"ollama_model": LOCAL_1_8B}), \
                mock.patch.object(ollama_client, "update_settings") as save:
            st = ollama_client.get_ollama_status()
        self.assertEqual(st["chat_models"], ["gemma4:e4b"])
        self.assertNotIn(RAW_7B, [m["id"] for m in st["catalog"]])
        self.assertNotIn(LOCAL_1_8B, [m["id"] for m in st["catalog"]])
        # a translator set as the analysis model gives its place to one that writes text
        self.assertEqual(st["active_model"], "gemma4:e4b")
        save.assert_called_once_with({"ollama_model": "gemma4:e4b"})
        tr = {m["id"]: m for m in st["translate_catalog"]}
        self.assertEqual(tr[ollama_client.HYMT_7B]["installed_as"], RAW_7B)
        self.assertEqual(tr[ollama_client.HYMT_1_8B]["installed_as"], LOCAL_1_8B)

    def test_display_names(self):
        for name, pretty in ((RAW_7B, "Hy-MT3 7B"), (RAW_1_8B, "Hy-MT3 1.8B"), (LOCAL_1_8B, "Hy-MT3 1.8B")):
            self.assertEqual(ollama_client.format_llm_model_name(name), pretty)

    def test_the_translators_share_the_card(self):
        from app import vram

        self.assertEqual(vram._sharing_size(RAW_7B), 5.3)
        self.assertEqual(vram._sharing_size(RAW_1_8B), 1.5)
        self.assertEqual(vram._sharing_size("hy-mt3-1.8b"), 1.5)


@unittest.skipIf(ollama_client is None, "app dependencies not installed")
class RepairTemplateTest(unittest.TestCase):
    BROKEN = "{{ if .System }}<|hy_begin|>{{ .System }}{{ end }}<|hy_User|>onse }}"

    def setUp(self):
        ollama_client._hymt_checked.clear()
        ollama_client._hymt_failed.clear()
        self.addCleanup(ollama_client._hymt_failed.clear)

    def _repair(self, models, template, strict=False, **kw):
        fake = _Ollama(template=template, **kw)
        with mock.patch.object(ollama_client.httpx, "Client", fake):
            out = ollama_client.repair_hymt_models("http://127.0.0.1:11434", models, strict=strict)
        return fake, out

    def test_a_failed_repair_waits_before_the_next_try(self):
        """The list is read often (status, the captions' choice of model): a repair that failed is not tried
        on every read, with its two requests, its 120 s timeout and a line in the log."""
        now = [1000.0]
        with mock.patch.object(ollama_client.time, "time", lambda: now[0]):
            fake, out = self._repair([RAW_1_8B], self.BROKEN, create_status=500)
            self.assertEqual([k for k, _ in fake.posts], ["show", "create"])
            self.assertEqual(out, [RAW_1_8B])  # stays as it is
            now[0] += 60
            fake, out = self._repair([RAW_1_8B], self.BROKEN, create_status=500)
            self.assertEqual((fake.posts, out), ([], [RAW_1_8B]))
            now[0] += ollama_client.HYMT_REPAIR_RETRY_SEC
            fake, out = self._repair([RAW_1_8B], self.BROKEN)
            self.assertEqual([k for k, _ in fake.posts], ["show", "create"])
            self.assertEqual(out, [LOCAL_1_8B])

    def test_after_a_download_the_repair_is_tried_at_once(self):
        with mock.patch.object(ollama_client.time, "time", return_value=1000.0):
            self._repair([RAW_1_8B], self.BROKEN, create_status=500)
            with self.assertRaises(RuntimeError):
                self._repair([RAW_1_8B], self.BROKEN, strict=True, create_status=500)

    def test_the_list_is_read_again_under_the_lock(self):
        """A caller with a list read before another one's repair finds the work done: nothing is created or
        deleted again, and the list it gets is Ollama's."""
        fake, out = self._repair(["gemma4:e4b", RAW_1_8B], self.BROKEN, tags=["gemma4:e4b", LOCAL_1_8B])
        self.assertEqual((fake.posts, fake.deleted), ([], []))
        self.assertEqual(out, ["gemma4:e4b", LOCAL_1_8B])

    def test_one_repair_at_a_time(self):
        import threading

        inside, peak = [0], [0]
        gate = threading.Lock()

        class Slow(_Ollama):
            def post(self, url, json=None, **k):
                with gate:
                    inside[0] += 1
                    peak[0] = max(peak[0], inside[0])
                threading.Event().wait(0.05)
                with gate:
                    inside[0] -= 1
                return super().post(url, json=json, **k)

        fake = Slow(template=self.BROKEN)
        with mock.patch.object(ollama_client.httpx, "Client", fake):
            threads = [threading.Thread(target=ollama_client.repair_hymt_models,
                                        args=("http://127.0.0.1:11434", [RAW_1_8B])) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
        self.assertEqual(peak[0], 1)

    def test_broken_template_is_detected(self):
        self.assertTrue(ollama_client.template_is_broken(self.BROKEN))
        self.assertTrue(ollama_client.template_is_broken(""))
        self.assertFalse(ollama_client.template_is_broken(ollama_client.HYMT_1_8B_TEMPLATE))
        self.assertFalse(ollama_client.template_is_broken("<|startoftext|>{{- .Prompt -}}<|extra_0|>"))

    def test_the_template_of_the_report(self):
        t = ollama_client.HYMT_1_8B_TEMPLATE
        self.assertIn("<｜hy_User｜>{{ .Prompt }}<｜hy_Assistant｜>{{ .Response }}", t)
        self.assertTrue(t.endswith("<｜hy_place▁holder▁no▁2｜>"))
        self.assertEqual(ollama_client.HYMT_1_8B_STOP, ["<｜hy_place▁holder▁no▁2｜>",
                                                        "<｜hy_place▁holder▁no▁8｜>"])

    def test_broken_model_is_made_again_and_the_download_removed(self):
        fake, out = self._repair(["gemma4:e4b", RAW_1_8B], self.BROKEN)
        create = [body for kind, body in fake.posts if kind == "create"]
        self.assertEqual(create, [{"model": "hy-mt3-1.8b", "from": RAW_1_8B, "template": ollama_client.HYMT_1_8B_TEMPLATE,
                                   "parameters": {"stop": ollama_client.HYMT_1_8B_STOP}, "stream": False}])
        self.assertEqual(fake.deleted, [RAW_1_8B])
        self.assertEqual(out, ["gemma4:e4b", LOCAL_1_8B])

    def test_a_right_template_is_kept_and_asked_once(self):
        right = "{{ .System }}<|hy_User|>{{ .Prompt }}<|hy_Assistant|>{{ .Response }}"
        fake, out = self._repair([RAW_1_8B], right)
        self.assertEqual([k for k, _ in fake.posts], ["show"])
        self.assertEqual((fake.deleted, out), ([], [RAW_1_8B]))
        fake, _ = self._repair([RAW_1_8B], right)
        self.assertEqual(fake.posts, [])

    def test_with_the_repaired_one_there_the_download_only_goes(self):
        fake, out = self._repair([LOCAL_1_8B, RAW_1_8B], self.BROKEN)
        self.assertEqual(fake.posts, [])
        self.assertEqual((fake.deleted, out), ([RAW_1_8B], [LOCAL_1_8B]))

    def test_the_7b_is_left_alone(self):
        fake, out = self._repair([RAW_7B], self.BROKEN)
        self.assertEqual((fake.posts, fake.deleted, out), ([], [], [RAW_7B]))


@unittest.skipIf(live_translate is None, "app dependencies not installed")
class HyMtPromptTest(unittest.TestCase):
    def _translator(self, model):
        t = live_translate.LiveTranslator.__new__(live_translate.LiveTranslator)
        t._source_lang = lambda: "en"
        t.target, t.pair, t.speed = "ru", ["en", "ru"], "quality"
        t._model, t.model_override = model, None
        t._fallback_model = lambda: None
        return t

    def _run(self, model, answer):
        fake = _Ollama(chat=answer)
        with mock.patch.object(live_translate.httpx, "Client", fake), \
                mock.patch.object(live_translate, "_base_url", return_value="http://127.0.0.1:11434"), \
                mock.patch("app.idle_unload.touch"), mock.patch("app.idle_unload.ollama_keep_alive", return_value="10m"):
            out = self._translator(model)._translate_clean("Let's move the meeting to Friday", "en", target="ru")
        return fake, out

    def test_the_card_prompt_and_sampling(self):
        fake, out = self._run(LOCAL_1_8B, "Давайте перенесём встречу на пятницу перенесём встречу на пятницу\nПояснение")
        (kind, body), = fake.posts
        self.assertEqual(kind, "chat")
        self.assertEqual(body["messages"], [{"role": "user", "content":
            "Translate the following text into Russian. Note that you should only output the translated result "
            "without any additional explanation:\n\nLet's move the meeting to Friday"}])
        self.assertEqual(body["options"], {"temperature": 0.7, "top_p": 0.6, "top_k": 20, "repeat_penalty": 1.05,
                                           "num_ctx": 2048, "num_predict": 200})
        self.assertNotIn("think", body)
        self.assertEqual(out, "Давайте перенесём встречу на пятницу")  # one line, the repeat collapsed

    def test_a_general_model_keeps_the_captions_prompt(self):
        fake, out = self._run("gemma4:e2b", "Давайте перенесём встречу на пятницу")
        body = fake.posts[-1][1]
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body["messages"][1], {"role": "user", "content": "Let's move the meeting to Friday"})


class _Show(_Ollama):
    """/api/show answering a modelfile; records the names asked."""

    def __init__(self, modelfile="", status=200):
        super().__init__()
        self.modelfile, self.status, self.asked = modelfile, status, []

    def post(self, url, json=None, **k):
        self.asked.append(json["model"])
        return _Resp(self.status, {"modelfile": self.modelfile})


@unittest.skipIf(ollama_client is None, "app dependencies not installed")
class ModelFileTest(unittest.TestCase):
    """Ollama pulls Hy-MT3 from the repository's main branch: the file it got is compared with the one checked."""

    BASE = "http://127.0.0.1:11434"

    def setUp(self):
        ollama_client._file_checks.clear()
        self.addCleanup(ollama_client._file_checks.clear)

    def _digest(self, modelfile, status=200, models_dir=None):
        import tempfile

        fake = _Show(modelfile, status)
        with mock.patch.object(ollama_client.httpx, "Client", fake):
            return ollama_client.model_file_digest(self.BASE, RAW_7B, models_dir=models_dir or tempfile.mkdtemp())

    def test_the_checked_files(self):
        self.assertEqual(set(ollama_client.HYMT_GGUF_SHA256), {RAW_7B, RAW_1_8B})
        for digest in ollama_client.HYMT_GGUF_SHA256.values():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_the_blob_of_the_from_line(self):
        d = "ab" * 32
        self.assertEqual(self._digest(f"# Modelfile\nFROM /home/u/.ollama/models/blobs/sha256-{d}\nTEMPLATE x"), d)
        self.assertEqual(self._digest(f"FROM C:\\Users\\u\\.ollama\\models\\blobs\\sha256-{d.upper()}"), d)
        self.assertIsNone(self._digest("FROM hf.co/tencent/Hy-MT3-7B-GGUF:Q4_K_M"))  # no blob named
        self.assertIsNone(self._digest("", status=404))

    def test_else_the_manifest_on_the_disk(self):
        import json
        import shutil
        import tempfile
        from pathlib import Path

        d = "cd" * 32
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        path = Path(root, "manifests", "hf.co", "tencent", "Hy-MT3-7B-GGUF", "Q4_K_M")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"layers": [
            {"mediaType": "application/vnd.ollama.image.template", "digest": "sha256:" + "ee" * 32},
            {"mediaType": "application/vnd.ollama.image.model", "digest": "sha256:" + d}]}), encoding="utf-8")
        self.assertEqual(self._digest("", status=500, models_dir=root), d)
        self.assertEqual(ollama_client._manifest_path("hy-mt3-1.8b:latest", root),
                         Path(root, "manifests", "registry.ollama.ai", "library", "hy-mt3-1.8b", "latest"))

    def _check(self, models, digest):
        with mock.patch.object(ollama_client, "model_file_digest", return_value=digest) as ask:
            ollama_client.check_translator_files(self.BASE, models)
        return ask

    def test_another_file_is_marked_and_kept(self):
        ask = self._check([RAW_7B, LOCAL_1_8B], "00" * 32)
        self.assertEqual(sorted(c.args[1] for c in ask.call_args_list), sorted([RAW_7B, LOCAL_1_8B]))
        with mock.patch("app.ollama_client.get_all_settings", return_value={}):
            catalog = ollama_client.translate_catalog([RAW_7B, LOCAL_1_8B])
        self.assertEqual([(c["installed"], c["file_differs"]) for c in catalog], [(True, True), (True, True)])

    def test_the_checked_file_is_not_marked_and_asked_once(self):
        expected = ollama_client.HYMT_GGUF_SHA256[RAW_7B]
        self._check([RAW_7B], expected)
        self.assertFalse(ollama_client.translator_file_differs(RAW_7B))
        self.assertFalse(self._check([RAW_7B], expected).called)  # the status is read often: asked once

    def test_unknown_is_no_warning(self):
        self._check([RAW_7B], None)
        self.assertFalse(ollama_client.translator_file_differs(RAW_7B))
        self.assertFalse(self._check([RAW_7B], None).called)  # not asked again at once
        with mock.patch.object(ollama_client.time, "time", return_value=ollama_client.time.time() + 601):
            self.assertTrue(self._check([RAW_7B], None).called)

    def test_a_model_not_installed_is_not_asked(self):
        self.assertFalse(self._check(["gemma4:e4b"], "00" * 32).called)


class TranslateRecommendationTest(unittest.TestCase):
    def test_by_the_card(self):
        from app import hardware

        self.assertEqual(hardware.recommended_translate_model(24.0), RAW_7B)
        self.assertEqual(hardware.recommended_translate_model(9.8), RAW_7B)  # an RTX 3080 10 GB reports a little under 10
        self.assertEqual(hardware.recommended_translate_model(8.0), RAW_1_8B)
        with mock.patch.object(hardware, "_gpu_probe", return_value=("RTX 3080", 9.8, 8.0)):
            self.assertEqual(hardware.get_hardware_info()["recommended_translate_model"], RAW_7B)
        with mock.patch.object(hardware, "_gpu_probe", return_value=("RTX 3060", 6.0, 5.0)):
            self.assertEqual(hardware.get_hardware_info()["recommended_translate_model"], RAW_1_8B)
        with mock.patch.object(hardware, "_gpu_probe", return_value=None):
            self.assertEqual(hardware.get_hardware_info()["recommended_translate_model"], RAW_1_8B)

    @unittest.skipIf(ollama_client is None, "app dependencies not installed")
    def test_the_names_are_the_catalogs(self):
        from app import hardware

        self.assertEqual((hardware.TRANSLATE_LARGE, hardware.TRANSLATE_SMALL), (ollama_client.HYMT_7B, ollama_client.HYMT_1_8B))
        self.assertEqual(hardware.TRANSLATE_LARGE_MIN_VRAM_GB, ollama_client.TRANSLATE_MODELS[0]["min_vram_gb"])


TG_12B = "translategemma:12b"


@unittest.skipIf(live_translate is None, "app dependencies not installed")
class ChosenModelsTest(unittest.TestCase):
    """Settings → ИИ-анализ → «Модели перевода»: the lists «Качество» and «Скорость» (empty: «Авто»)."""

    def setUp(self):
        from app.database import init_db

        init_db()

    def _choose(self, installed, **chosen):
        settings = {"ollama_model": "gemma4:e4b", **{f"live_translate_model_{k}": v for k, v in chosen.items()}}
        return live_translate.choose_models(installed, settings)

    def test_empty_is_auto(self):
        c = self._choose(["gemma4:e4b", "gemma4:e2b", RAW_7B, LOCAL_1_8B], quality="", fast="")
        self.assertEqual((c["quality"], c["fast"]), (RAW_7B, LOCAL_1_8B))
        self.assertEqual(c["auto"], {"quality": RAW_7B, "fast": LOCAL_1_8B})

    def test_a_chosen_installed_model_comes_first(self):
        installed = ["gemma4:e4b", "gemma4:e2b", RAW_7B, LOCAL_1_8B, TG_12B]
        c = self._choose(installed, quality="gemma4:e4b", fast=TG_12B)
        self.assertEqual((c["quality"], c["fast"]), ("gemma4:e4b", TG_12B))
        self.assertEqual(c["auto"], {"quality": RAW_7B, "fast": LOCAL_1_8B})  # what «Авто» would take, for the lists
        # the name as Ollama lists it: any case, «:latest» left out
        c = self._choose(installed, quality=RAW_7B.lower(), fast="hy-mt3-1.8b")
        self.assertEqual((c["quality"], c["fast"]), (RAW_7B, LOCAL_1_8B))

    def test_a_chosen_model_not_installed_gives_its_place_to_auto(self):
        c = self._choose(["gemma4:e4b", "gemma4:e2b", LOCAL_1_8B], quality=RAW_7B, fast="bge-m3:latest")
        self.assertEqual((c["quality"], c["fast"]), (LOCAL_1_8B, LOCAL_1_8B))
        c = self._choose([], quality=RAW_7B)
        self.assertEqual(c["quality"], "gemma4:e4b")  # Ollama not answering: the analysis model, as before

    def test_model_choices_reads_the_settings(self):
        with mock.patch.object(live_translate, "installed_models", return_value=["gemma4:e4b", "gemma4:e2b", RAW_7B]), \
                mock.patch("app.database.get_all_settings", return_value={
                    "ollama_model": "gemma4:e4b", "live_translate_model_quality": "gemma4:e2b"}):
            c = live_translate.model_choices()
        self.assertEqual((c["quality"], c["fast"]), ("gemma4:e2b", "gemma4:e2b"))

    def test_the_studio_choice_still_wins(self):
        t = live_translate.LiveTranslator.__new__(live_translate.LiveTranslator)
        t.model_override, t.speed = "gemma4:e2b", "quality"
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch.object(live_translate, "model_choices") as choices:
            self.assertEqual(t._resolve_model(), "gemma4:e2b")
        choices.assert_not_called()

    def test_the_settings_keys_are_checked(self):
        from app.settings_schema import clean

        self.assertEqual(clean("live_translate_model_quality", ""), "")
        self.assertEqual(clean("live_translate_model_fast", RAW_1_8B), RAW_1_8B)
        self.assertEqual(clean("live_translate_model_quality", " translategemma:4b "), "translategemma:4b")
        for bad in ("gemma4:e4b; rm -rf", "../x", "a" * 300, "<b>"):
            with self.assertRaises(ValueError):
                clean("live_translate_model_quality", bad)


@unittest.skipIf(ollama_client is None, "app dependencies not installed")
class TranslateGemmaTest(unittest.TestCase):
    """TranslateGemma (Gemma Terms of Use): a translator the user may install by hand. Never offered, never an
    analysis model; listed with the translators, its license to check."""

    def setUp(self):
        from app.database import init_db

        init_db()

    def test_it_is_a_translator(self):
        for m in (TG_12B, "translategemma:4b", "TranslateGemma:27b"):
            self.assertTrue(ollama_client.is_translate_only_model(m), m)
            self.assertTrue(ollama_client.is_translategemma(m), m)
        self.assertFalse(ollama_client.is_translategemma(RAW_7B))
        models = ["gemma4:e4b", "gemma4:e2b", TG_12B, "translategemma:4b"]
        self.assertEqual(ollama_client.chat_models(models), ["gemma4:e4b", "gemma4:e2b"])
        self.assertEqual(ollama_client.translate_models(models), models)

    def test_it_is_listed_with_the_translators_never_offered(self):
        cat = ollama_client.translate_catalog([TG_12B, "gemma4:e4b", LOCAL_1_8B])
        self.assertEqual([m["id"] for m in cat], [ollama_client.HYMT_7B, ollama_client.HYMT_1_8B, TG_12B])
        tg = cat[-1]
        self.assertEqual((tg["installed"], tg["installed_as"], tg["offered"]), (True, TG_12B, False))
        self.assertEqual(tg["license"], "Gemma Terms")
        self.assertTrue(tg["license_check"])
        self.assertIn("коммерческим", tg["desc_ru"])
        self.assertIn("commercial", tg["desc_en"])
        self.assertTrue(all(m["offered"] for m in cat[:2]))
        # it is not offered when it is not installed
        self.assertNotIn(TG_12B, [m["id"] for m in ollama_client.translate_catalog(["gemma4:e4b"])])

    def test_status_keeps_it_out_of_the_analysis_list(self):
        on_disk = ["gemma4:e4b", "gemma4:e2b", TG_12B, RAW_7B]
        with mock.patch.object(ollama_client, "_is_ollama_port_open", return_value=False), \
                mock.patch.object(ollama_client, "models_on_disk", return_value=on_disk), \
                mock.patch.object(ollama_client, "find_ollama_executable", return_value="ollama"), \
                mock.patch.object(ollama_client, "get_all_settings", return_value={
                    "ollama_model": TG_12B, "live_translate_model_fast": TG_12B}), \
                mock.patch.object(ollama_client, "update_settings") as save:
            st = ollama_client.get_ollama_status()
        self.assertEqual(st["chat_models"], ["gemma4:e4b", "gemma4:e2b"])
        self.assertNotIn(TG_12B, [m["id"] for m in st["catalog"]])
        self.assertIn(TG_12B, [m["id"] for m in st["translate_catalog"]])
        save.assert_called_once_with({"ollama_model": "gemma4:e4b"})  # never the analysis model
        # what the lists of the settings show: «Авто · Hy-MT3 7B» and the chosen one of «Скорость»
        self.assertEqual(st["live_translate"]["auto"], {"quality": RAW_7B, "fast": "gemma4:e2b"})
        self.assertEqual(st["live_translate"]["fast"], TG_12B)


@unittest.skipIf(live_translate is None, "app dependencies not installed")
class TranslateGemmaPromptTest(HyMtPromptTest):
    def test_the_card_prompt_and_options(self):
        fake, out = self._run(TG_12B, "Давайте перенесём встречу на пятницу\nПояснение")
        (kind, body), = fake.posts
        self.assertEqual(kind, "chat")
        self.assertEqual(body["messages"], [{"role": "user", "content":
            "You are a professional English (en) to Russian (ru) translator. Your goal is to accurately convey the "
            "meaning and nuances of the original English text while adhering to Russian grammar, vocabulary, and "
            "cultural sensitivities. Produce only the Russian translation, without any additional explanations or "
            "commentary. Please translate the following English text into Russian:\n\n\nLet's move the meeting to Friday"}])
        self.assertEqual(body["options"], {"temperature": 0.1, "num_ctx": 2048, "num_predict": 200})
        self.assertNotIn("think", body)
        self.assertEqual(out, "Давайте перенесём встречу на пятницу")

    def test_an_unknown_source_is_left_out(self):
        p = live_translate.translategemma_prompt("Hola", None, "ru")
        self.assertTrue(p.startswith("You are a professional translator into Russian (ru)."))
        self.assertTrue(p.endswith("Please translate the following text into Russian:\n\n\nHola"))


if __name__ == "__main__":
    unittest.main()
