import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

import numpy as np

from app import dictation, llm
from app.database import init_db, update_settings


class _Target:
    def __init__(self, answer=None, error=None, wait=0.0):
        self.answer, self.error, self.wait, self.asked = answer, error, wait, []

    def chat(self, system, user, short=False):
        import time

        self.asked.append((system, user))
        time.sleep(self.wait)
        if self.error:
            raise self.error
        return self.answer


class DictationBusyTest(unittest.TestCase):
    def test_a_press_while_the_last_one_is_recognized_starts_nothing(self):
        with dictation._lock:
            saved = dict(dictation._state)
            dictation._state.update(active=False, busy=True, translate_to="de")
        try:
            with mock.patch.object(dictation, "_start") as start:
                self.assertEqual(dictation.toggle(translate=True), "busy")
            start.assert_not_called()
            self.assertEqual(dictation.status()["translate_to"], "de")
        finally:
            with dictation._lock:
                dictation._state.clear()
                dictation._state.update(saved)


class DictationTranslateTest(unittest.TestCase):
    def setUp(self):
        init_db()
        update_settings({"dictation_translate_to": "en"})
        # the model of «Качество» of live captions: here the analysis model (no translator installed)
        patcher = mock.patch("app.live_translate.translation_model", return_value="gemma4:e4b")
        self.chosen = patcher.start()
        self.addCleanup(patcher.stop)

    def test_text_is_translated_by_the_local_model(self):
        tgt = _Target(answer="<think>x</think> «Hello, I will send the report tomorrow.»")
        with mock.patch.object(llm, "target", return_value=tgt) as pick:
            out, note = dictation.translate("Привет, завтра пришлю отчёт.", "en")
        self.assertEqual((out, note), ("Hello, I will send the report tomorrow.", ""))
        self.assertEqual(pick.call_args.args, ("gemma4:e4b",))
        self.assertEqual(self.chosen.call_args.args, ("quality",))
        self.assertIn("English", tgt.asked[0][0])

    def test_a_translator_of_the_captions_translates_with_its_card_prompt(self):
        from app import live_translate

        asked = []
        self.chosen.return_value = "hy-mt3-1.8b:latest"
        with mock.patch.object(live_translate, "translator_chat",
                               side_effect=lambda *a, **k: asked.append((a, k)) or "Hello, I will send the report tomorrow."), \
                mock.patch.object(llm, "target") as pick:
            out, note = dictation.translate("Привет, завтра пришлю отчёт.", "en")
        self.assertEqual((out, note), ("Hello, I will send the report tomorrow.", ""))
        pick.assert_not_called()  # no general model is asked
        (args, kw), = asked
        self.assertEqual(args, ("hy-mt3-1.8b:latest", "Привет, завтра пришлю отчёт.", "ru", "en"))
        self.assertTrue(kw["long"])
        # the request itself: the Hy-MT card prompt, a context and a length for paragraphs
        body = live_translate.translator_payload("hy-mt3-1.8b:latest", "Привет", "ru", "en", long=True)
        self.assertTrue(body["messages"][0]["content"].startswith("Translate the following text into English."))
        self.assertEqual((body["options"]["num_ctx"], body["options"]["num_predict"]), (4096, 1024))

    def test_text_already_in_the_language_is_typed_as_it_is(self):
        with mock.patch.object(llm, "target") as pick:
            self.assertEqual(dictation.translate("I will send you the report", "en"), ("I will send you the report", ""))
        pick.assert_not_called()

    def test_failure_or_silence_types_the_original(self):
        src = "Привет, завтра пришлю отчёт."
        for tgt, why in ((_Target(error=RuntimeError("Ollama не отвечает")), "Ollama не отвечает"),
                         (_Target(answer="  "), "пустой")):
            with mock.patch.object(llm, "target", return_value=tgt):
                out, note = dictation.translate(src, "en")
            self.assertEqual(out, src)
            self.assertIn(why, note)
        with mock.patch.object(llm, "target", side_effect=llm.LlmError("Ollama не запущена")):
            self.assertIn("Ollama не запущена", dictation.translate(src, "en")[1])
        with mock.patch.object(dictation, "TRANSLATE_TIMEOUT_SEC", 0.1), \
                mock.patch.object(llm, "target", return_value=_Target(answer="late", wait=1.0)):
            out, note = dictation.translate(src, "en")
        self.assertEqual(out, src)
        self.assertIn("не ответила", note)

    def test_hotkey_with_translation_types_the_translation(self):
        typed, notes, saved = [], [], []
        with mock.patch.object(dictation, "_record"), \
                mock.patch.object(dictation, "recognize", return_value=("Привет, завтра пришлю отчёт.", "gigaam-v3")), \
                mock.patch.object(dictation, "save_to_library", side_effect=lambda *a: saved.append(a[1:])), \
                mock.patch.object(dictation, "type_text", side_effect=typed.append), \
                mock.patch.object(llm, "target", return_value=_Target(answer="Hi, I will send the report tomorrow.")):
            self.assertEqual(dictation.toggle(translate=True), "started")
            dictation._chunks.append(np.zeros(dictation.SR, dtype=np.float32))
            dictation._finish(notify=lambda title, text, warning=False: notes.append((title, warning)))
        self.assertEqual(typed, ["Hi, I will send the report tomorrow."])
        self.assertEqual(notes, [("Диктовка с переводом", False)])
        dictation.threading.Event().wait(0.2)  # the library copy is made in a thread of its own
        # the library keeps what was said, with the typed translation as its translation
        self.assertEqual(saved, [("Привет, завтра пришлю отчёт.", "gigaam-v3", "en", "Hi, I will send the report tomorrow.")])

        # the plain hotkey still types what was said
        typed.clear()
        with mock.patch.object(dictation, "_record"), \
                mock.patch.object(dictation, "recognize", return_value=("Привет", "gigaam-v3")), \
                mock.patch.object(dictation, "save_to_library"), \
                mock.patch.object(dictation, "type_text", side_effect=typed.append), \
                mock.patch.object(llm, "target") as pick:
            dictation.toggle()
            dictation._chunks.append(np.zeros(dictation.SR, dtype=np.float32))
            dictation._finish()
        self.assertEqual(typed, ["Привет"])
        pick.assert_not_called()

    def test_a_forgotten_dictation_is_recognized_when_its_time_runs_out(self):
        """MAX_SEC ends the recording: what was said is recognized and kept as if the keys were pressed
        again, with the way the dictation was started (the home page: not typed)."""
        import sys
        import time
        import types

        class _Rec:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def record(self, numframes):
                time.sleep(0.01)
                return np.zeros((numframes, 1), dtype=np.float32)

        mic = mock.Mock()
        mic.recorder.return_value = _Rec()
        fake = types.SimpleNamespace(default_microphone=lambda: mic)
        typed = []
        with mock.patch.dict(sys.modules, {"soundcard": fake}), mock.patch.object(dictation, "MAX_SEC", 0.6), \
                mock.patch.object(dictation, "recognize", return_value=("Длинная диктовка", "gigaam-v3")), \
                mock.patch.object(dictation, "save_to_library"), \
                mock.patch.object(dictation, "type_text", side_effect=typed.append):
            self.assertEqual(dictation.toggle(type_out=False), "started")
            for _ in range(100):
                time.sleep(0.05)
                st = dictation.status()
                if not st["active"] and not st["busy"]:
                    break
        self.assertEqual(st["last_text"], "Длинная диктовка")
        self.assertEqual(typed, [])  # started from the home page: shown there, not typed

    def test_a_dictation_is_kept_in_its_library_folder(self):
        from pathlib import Path

        from app import database

        update_settings({"dictation_save": "true", "dictation_language": "ru"})
        audio = np.zeros(dictation.SR * 2, dtype=np.float32)
        mid = dictation.save_to_library(audio, "Привет, завтра пришлю отчёт.", "gigaam-v3", "en", "Hi, I will send it tomorrow.")
        self.addCleanup(database.delete_meeting, mid)
        m = database.get_meeting(mid)
        folder = next(f for f in database.list_folders() if f["id"] == m["folder_id"])
        self.assertEqual(folder["system_key"], "dictations")
        self.assertIn(mid, database.dictation_ids())  # not given to an agent (app/mcp_server.py)
        self.assertEqual((m["status"], m["duration"], m["transcript_model"]), ("completed", 2.0, "gigaam-v3"))
        self.assertEqual([s["text"] for s in m["segments"]], ["Привет, завтра пришлю отчёт."])
        self.assertEqual(m["translations"]["en"]["segments"]["0"]["text"], "Hi, I will send it tomorrow.")
        self.assertTrue(Path(m["media_path"]).exists())
        self.assertTrue(m["title"].startswith("Диктовка: Привет"))

        update_settings({"dictation_save": "false"})
        self.addCleanup(update_settings, {"dictation_save": "true"})
        self.assertIsNone(dictation.save_to_library(audio, "текст", "gigaam-v3"))

    def test_target_language_is_checked_when_saved(self):
        from app.settings_schema import clean

        self.assertEqual(clean("dictation_translate_to", "de"), "de")
        with self.assertRaises(ValueError):
            clean("dictation_translate_to", "klingon")


if __name__ == "__main__":
    unittest.main()


class OllamaModelChoiceTest(unittest.TestCase):
    """The embedding model of search by meaning (bge-m3) is never picked to write text: Ollama
    answers a chat with it by 400. And an Ollama error reaches the user in Ollama's words."""

    def setUp(self):
        init_db()
        update_settings({"ollama_model": "qwen2.5:7b", "semantic_model": "bge-m3"})

    def test_a_missing_model_falls_back_to_a_chat_model(self):
        from app import ollama_client

        status = {"running": True, "models": ["bge-m3:latest", "nomic-embed-text:latest", "qwen3:8b"]}
        status["chat_models"] = ollama_client.chat_models(status["models"])
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch("app.ollama_client.get_ollama_status", return_value=status):
            self.assertEqual(llm.target(None).model, "qwen3:8b")
        with mock.patch("app.ollama_client.ensure_ollama_running"), \
                mock.patch("app.ollama_client.get_ollama_status",
                           return_value={"running": True, "models": ["bge-m3:latest"], "chat_models": []}):
            with self.assertRaises(llm.LlmError):  # only an embedding model: "no model downloaded"
                llm.target(None)

    def test_ollama_error_text_is_kept(self):
        import httpx

        from app import ollama_client

        resp = httpx.Response(400, json={"error": "\"bge-m3:latest\" does not support chat"},
                              request=httpx.Request("POST", "http://127.0.0.1:11434/api/chat"))
        with self.assertRaises(RuntimeError) as e:
            ollama_client.raise_for_ollama(resp)
        self.assertIn("does not support chat", str(e.exception))
        self.assertIn("400", str(e.exception))


class OllamaModelsOnDiskTest(unittest.TestCase):
    """Ollama is started only when analysis needs it: with it stopped, the models it has downloaded are
    read from its folder, so a model on the disk does not read as «не скачана» after a restart."""

    def test_stopped_ollama_lists_the_models_of_its_folder(self):
        import tempfile
        from pathlib import Path

        from app import ollama_client

        init_db()
        with tempfile.TemporaryDirectory() as d:
            man = Path(d) / "manifests"
            for rel in ("registry.ollama.ai/library/gemma4/e4b", "registry.ollama.ai/library/bge-m3/latest",
                        "registry.ollama.ai/someone/tuned/q4", "hf.co/org/model-gguf/Q4_K_M"):
                (man / rel).parent.mkdir(parents=True, exist_ok=True)
                (man / rel).write_text("{}")
            self.assertEqual(ollama_client.models_on_disk(d),
                             ["bge-m3:latest", "gemma4:e4b", "hf.co/org/model-gguf:Q4_K_M", "someone/tuned:q4"])
            with mock.patch.object(ollama_client, "_is_ollama_port_open", return_value=False), \
                    mock.patch.object(ollama_client, "ollama_models_dir", return_value=d):
                st = ollama_client.get_ollama_status()
        self.assertFalse(st["running"])
        self.assertIn("gemma4:e4b", st["models"])
        self.assertTrue(next(x for x in st["catalog"] if x["id"] == "gemma4:e4b")["installed"])
        self.assertFalse(next(x for x in st["catalog"] if x["id"] == "gemma4:e2b")["installed"])

    def test_no_folder_no_models(self):
        from app import ollama_client

        self.assertEqual(ollama_client.models_on_disk("/nonexistent/ollama"), [])


class EmbeddingSettingTest(unittest.TestCase):
    def test_an_embedding_model_chosen_for_analysis_is_replaced_once(self):
        import httpx

        from app import database, ollama_client

        init_db()
        update_settings({"ollama_model": "bge-m3", "semantic_model": "bge-m3"})
        tags = {"models": [{"name": "bge-m3:latest"}, {"name": "qwen3:8b"}]}
        real = httpx.Client
        with mock.patch.object(ollama_client, "_is_ollama_port_open", return_value=True), \
                mock.patch("httpx.Client", side_effect=lambda **kw: real(transport=httpx.MockTransport(
                    lambda req: httpx.Response(200, json=tags)), **kw)):
            st = ollama_client.get_ollama_status()
        self.assertEqual(st["active_model"], "qwen3:8b")
        self.assertEqual(database.get_all_settings()["ollama_model"], "qwen3:8b")
        self.assertEqual(st["chat_models"], ["qwen3:8b"])


class AnalysisWithOllamaStoppedTest(unittest.TestCase):
    """Ollama stops with the app now: the automatic analysis after a transcription must still run (it starts
    Ollama), when Ollama is installed and has a model on the disk (reported by the user: it stopped running)."""

    def test_a_stopped_local_ollama_with_a_model_is_available(self):
        from app import ollama_client

        init_db()
        update_settings({"llm_provider": "ollama", "ollama_url": "http://127.0.0.1:11434"})
        off = {"running": False, "installed": True, "models": ["gemma4:e4b"], "chat_models": ["gemma4:e4b"]}
        with mock.patch("app.ollama_client.get_ollama_status", return_value=off), \
                mock.patch.object(ollama_client, "find_ollama_executable", return_value="C:/ollama.exe"):
            self.assertTrue(llm.available())
        with mock.patch("app.ollama_client.get_ollama_status", return_value={**off, "models": [], "chat_models": []}), \
                mock.patch.object(ollama_client, "find_ollama_executable", return_value="C:/ollama.exe"):
            self.assertFalse(llm.available())  # no model downloaded
        with mock.patch("app.ollama_client.get_ollama_status", return_value=off), \
                mock.patch.object(ollama_client, "find_ollama_executable", return_value=None):
            self.assertFalse(llm.available())  # Ollama not installed
        update_settings({"ollama_url": "http://192.168.1.5:11434"})
        with mock.patch("app.ollama_client.get_ollama_status", return_value=off), \
                mock.patch.object(ollama_client, "find_ollama_executable", return_value="C:/ollama.exe"):
            self.assertFalse(llm.available())  # Ollama on another computer is not started from here
        update_settings({"ollama_url": "http://127.0.0.1:11434"})


class TypingKeepsTheClipboardTest(unittest.TestCase):
    """Found in the audit: dictation typed through the clipboard and put back only text, so a copied
    image or file list was lost. With such content the text is typed as keystrokes instead."""

    def test_an_image_or_files_in_the_clipboard_are_left_alone(self):
        self.assertTrue(dictation._clipboard_holds_more_than_text([8, 17, 2]))  # an image
        self.assertTrue(dictation._clipboard_holds_more_than_text([15, 0xC0A1]))  # files from Explorer
        self.assertFalse(dictation._clipboard_holds_more_than_text([13, 1, 7, 16, 0xC0B2]))  # text, HTML
        self.assertFalse(dictation._clipboard_holds_more_than_text([]))

    def test_keystrokes_type_every_utf16_unit_and_enter_for_a_line_break(self):
        keys = dictation._unicode_keystrokes("Да😀\nb")
        units = [u for vk, u, f in keys if f == 0x0004]
        self.assertEqual(units, [ord("Д"), ord("а"), 0xD83D, 0xDE00, ord("b")])
        self.assertIn((0x0D, 0, 0), keys)
        self.assertEqual(len(keys), 2 * 6)  # each press is released
        self.assertEqual(dictation._unicode_keystrokes(""), [])
