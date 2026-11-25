import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

import numpy as np

from app import live_phrases as lp

SR = lp.SR
F = lp.FRAME


def _run(probs):
    """Phrases a cutter gives for a list of per-frame probabilities."""
    c = lp.PhraseCutter()
    out = []
    for p in probs:
        r = c.push(p)
        if r:
            out.append(r)
    return out, c


def _sec(s):
    return int(round(s * SR / F))  # frames in s seconds


class PhraseCutterTest(unittest.TestCase):
    def test_a_pause_ends_a_phrase(self):
        probs = [0.0] * _sec(1) + [0.9] * _sec(2) + [0.05] * _sec(1) + [0.9] * _sec(1.5) + [0.0] * _sec(1)
        out, _ = _run(probs)
        self.assertEqual(len(out), 2)
        (a1, b1, f1), (a2, b2, f2) = out
        self.assertFalse(f1 or f2)
        self.assertAlmostEqual(a1 / SR, 1.0 - lp.PAD_SEC, delta=0.04)  # a little before the speech
        self.assertAlmostEqual(b1 / SR, 3.0 + lp.PAD_SEC, delta=0.04)  # and a little after
        self.assertLessEqual(b1, a2)  # never overlapping
        self.assertAlmostEqual(b2 / SR, 5.5 + lp.PAD_SEC, delta=0.04)

    def test_a_short_pause_does_not(self):
        probs = [0.9] * _sec(2) + [0.1] * _sec(0.3) + [0.9] * _sec(2) + [0.0] * _sec(1)
        out, _ = _run(probs)
        self.assertEqual(len(out), 1)

    def test_a_click_is_no_phrase(self):
        out, c = _run([0.0] * 10 + [0.9] * 3 + [0.0] * _sec(1))
        self.assertEqual(out, [])
        self.assertIsNone(c.start)

    def test_speech_without_pauses_is_cut_where_it_is_weakest_and_nothing_is_lost(self):
        probs = [0.95] * _sec(60)
        dips = {_sec(17): 0.4, _sec(34): 0.38, _sec(52): 0.36}  # breaths, still above the end of speech
        for i, q in dips.items():
            probs[i] = q
        out, c = _run(probs + [0.0] * _sec(1))
        forced = [x for x in out if x[2]]
        self.assertEqual(len(forced), 3)
        self.assertEqual(out[0][0], 0)
        for (a, b, _), (a2, _, _) in zip(out, out[1:]):
            self.assertEqual(b, a2)  # each phrase starts exactly where the one before was cut
            self.assertLessEqual(b - a, lp.MAX_PHRASE_SEC * SR)
        for (_, b, _), i in zip(forced, sorted(dips)):
            self.assertEqual(b, i * F + F // 2)  # in the middle of the weakest frame
        self.assertFalse(out[-1][2])  # the last one ends at the pause
        self.assertIsNone(c.start)

    def test_speech_without_any_dip_is_cut_at_20_s(self):
        out, _ = _run([0.95] * _sec(45) + [0.0] * _sec(1))
        self.assertEqual([x[2] for x in out], [True, True, False])
        self.assertAlmostEqual(out[0][1] / SR, lp.MAX_PHRASE_SEC, delta=0.05)
        self.assertEqual(out[0][1], out[1][0])
        self.assertEqual(out[1][1], out[2][0])

    def test_the_rest_after_a_cut_is_kept_however_short(self):
        probs = [0.95] * (int(lp.MAX_PHRASE_SEC * SR / F) + 2) + [0.0] * _sec(1)
        out, _ = _run(probs)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0][1], out[1][0])  # 64 ms of a word left after the cut: still a phrase


class StreamLevelTest(unittest.TestCase):
    def test_quiet_speech_is_raised_and_loud_is_not(self):
        lev = lp.StreamLevel()
        quiet = (np.sin(np.arange(SR) / 5) * 0.02).astype(np.float32)
        out = None
        for _ in range(5):
            out = lev(quiet)
        self.assertGreater(float(np.abs(out).max()), 0.5)
        loud = lp.StreamLevel()(np.full(SR, 0.6, dtype=np.float32))
        self.assertAlmostEqual(float(loud.max()), 0.6, places=5)


class _FakeVad:
    """Speech where the audio is loud."""

    def __init__(self, *_a):
        pass

    def prob(self, frame):
        return 0.95 if float(np.abs(frame).max()) > 0.1 else 0.02


def _pcm(sig):
    return (np.clip(sig, -1, 1) * 32767).astype("<i2").tobytes()


class LivePhraseSessionTest(unittest.TestCase):
    def setUp(self):
        from app.database import init_db

        init_db()

    def _session(self):
        from app import asr_onnx, live

        with mock.patch.object(live, "caption_onnx_model", return_value="gigaam-v3"):
            s = live.LiveSession("ru", None)
        self.patches = [mock.patch.object(asr_onnx, "live_phrases", return_value=True),
                        mock.patch.object(asr_onnx, "is_loaded", return_value=True),
                        mock.patch.object(lp, "SileroStream", _FakeVad),
                        mock.patch.object(asr_onnx, "recognize_phrase", side_effect=self._recognize)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        self.calls = []
        return s

    def _recognize(self, model, audio):
        self.calls.append(audio.size)
        return [(0.0, audio.size / SR, f"Фраза {len(self.calls)}.")]

    def _feed(self, s, sig, piece=1.0):
        n = int(piece * SR)
        for i in range(0, sig.size, n):
            s.add_pcm16(_pcm(sig[i:i + n]))
            s.step()

    def test_finals_after_a_pause_and_a_draft_while_speaking(self):
        s = self._session()
        speech = np.full(int(2.0 * SR), 0.5, dtype=np.float32)
        silence = np.zeros(int(1.0 * SR), dtype=np.float32)
        self._feed(s, np.concatenate([silence, speech]))
        self.assertEqual(s.lines, [])
        self.assertTrue(s.partial)  # the phrase being spoken, as a draft
        self._feed(s, np.concatenate([silence, speech, silence]))
        self.assertEqual(len(s.lines), 2)
        first, second = s.lines
        self.assertAlmostEqual(first["start"], 1.0 - lp.PAD_SEC, delta=0.05)
        self.assertAlmostEqual(first["end"], 3.0 + lp.PAD_SEC, delta=0.05)
        self.assertAlmostEqual(second["start"], 4.0 - lp.PAD_SEC, delta=0.05)
        self.assertEqual(first["lang"], "ru")
        self.assertEqual(s.partial, "")
        self.assertLess(s.audio.size, 2 * SR)  # what is final leaves the buffer

    def test_continuous_speech_loses_and_repeats_nothing(self):
        s = self._session()
        self._feed(s, np.full(int(47 * SR), 0.5, dtype=np.float32))
        self._feed(s, np.zeros(int(1.0 * SR), dtype=np.float32))
        lines = s.lines
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[0]["start"], 0.0)
        for a, b in zip(lines, lines[1:]):
            self.assertEqual(a["end"], b["start"])
            self.assertLessEqual(a["end"] - a["start"], lp.MAX_PHRASE_SEC + 0.01)
        self.assertAlmostEqual(lines[-1]["end"], 47.0 + lp.PAD_SEC, delta=0.05)
        self.assertLess(s.audio.size, 2 * SR)

    def test_the_translator_gets_the_finals(self):
        s = self._session()
        s.translator = mock.Mock()
        s.draft = True
        self._feed(s, np.concatenate([np.full(2 * SR, 0.5, dtype=np.float32), np.zeros(SR, dtype=np.float32)]))
        s.translator.add_lines.assert_called_once()
        s.translator.set_draft.assert_called()

    def test_waits_for_the_model_keeping_the_audio(self):
        from app import asr_onnx, live

        with mock.patch.object(live, "caption_onnx_model", return_value="gigaam-v3"):
            s = live.LiveSession("ru", None)
        with mock.patch.object(asr_onnx, "live_phrases", return_value=True), \
                mock.patch.object(asr_onnx, "is_loaded", return_value=False), \
                mock.patch.object(asr_onnx, "preload_async", return_value="") as pre:
            self._feed(s, np.full(3 * SR, 0.5, dtype=np.float32))
        pre.assert_called_with("gigaam-v3")
        self.assertEqual(s.audio.size, 3 * SR)


class PhraseVariantTest(unittest.TestCase):
    """The captions' copy of GigaAM is the e2e-CTC int8, once its file is there; until then the main model."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        from app import asr_onnx

        self.asr = asr_onnx
        self.dir = Path(tempfile.mkdtemp())
        self.patches = [mock.patch.object(asr_onnx, "model_dir", lambda mid: self.dir / mid),
                        mock.patch.object(asr_onnx, "_vad_dir", lambda: self.dir / "vad"),
                        mock.patch.object(asr_onnx, "_present", set()),
                        mock.patch.dict(asr_onnx._completing, {}, clear=True)]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(self.patches)])
        (self.dir / "gigaam-v3").mkdir()
        (self.dir / "gigaam-v3" / "v3_e2e_rnnt_encoder.onnx").write_bytes(b"x")
        (self.dir / "vad").mkdir()
        (self.dir / "vad" / "silero_vad.onnx").write_bytes(b"x")

    def test_without_the_file_the_window_and_a_download_in_the_background(self):
        with mock.patch.object(self.asr, "fetch") as fetch:
            self.assertFalse(self.asr.live_phrases("gigaam-v3"))
            self.assertEqual(self.asr._variant("gigaam-v3", "live")["onnx_name"], "gigaam-v3-e2e-rnnt")
            for t in __import__("threading").enumerate():
                if t.name == "onnx_complete_gigaam-v3":
                    t.join(5)
        fetch.assert_called_once_with("gigaam-v3")  # once, not on every step
        for name in ("v3_e2e_ctc.int8.onnx", "v3_e2e_ctc_vocab.txt"):
            (self.dir / "gigaam-v3" / name).write_bytes(b"x")
        self.assertTrue(self.asr.live_phrases("gigaam-v3"))
        v = self.asr._variant("gigaam-v3", "live")
        self.assertEqual((v["onnx_name"], v["quantization"]), ("gigaam-v3-e2e-ctc", "int8"))
        self.assertFalse(self.asr.live_phrases("parakeet-v3"))  # English and the rest: the window

    def test_a_copy_made_before_the_download_is_made_again(self):
        import sys
        import types

        fake = types.ModuleType("onnx_asr")
        fake.load_model = mock.Mock(side_effect=lambda *a, **k: mock.Mock())
        fake.load_vad = mock.Mock(return_value="vad")
        with mock.patch.dict(sys.modules, {"onnx_asr": fake}), mock.patch.object(self.asr, "ensure_package"), \
                mock.patch.object(self.asr, "fetch"), mock.patch.object(self.asr, "_complete_async"), \
                mock.patch.dict(self.asr._loaded, {}, clear=True), mock.patch.dict(self.asr._made, {}, clear=True), \
                mock.patch.dict(self.asr._plain, {}, clear=True):
            self.asr._load("gigaam-v3", live=True)
            self.assertTrue(self.asr.is_loaded("gigaam-v3"))
            for name in ("v3_e2e_ctc.int8.onnx", "v3_e2e_ctc_vocab.txt"):
                (self.dir / "gigaam-v3" / name).write_bytes(b"x")
            self.assertFalse(self.asr.is_loaded("gigaam-v3"))  # the CTC is there now: loaded in the background
            self.asr._load("gigaam-v3", live=True)
            self.assertTrue(self.asr.is_loaded("gigaam-v3"))
            names = [(c.args[0], c.kwargs.get("quantization")) for c in fake.load_model.call_args_list]
            self.assertEqual(names, [("gigaam-v3-e2e-rnnt", None), ("gigaam-v3-e2e-ctc", "int8")])
            self.assertIn("gigaam-v3@live", self.asr._plain)
            self.asr.release("gigaam-v3")
            self.assertEqual(self.asr._plain, {})

    def test_a_job_on_the_processor_takes_the_rnnt_int8_and_the_card_fp32(self):
        import sys
        import types

        fake = types.ModuleType("onnx_asr")
        fake.load_model = mock.Mock(side_effect=lambda *a, **k: mock.Mock())
        fake.load_vad = mock.Mock(return_value="vad")
        from app import onnx_gpu

        with mock.patch.dict(sys.modules, {"onnx_asr": fake}), mock.patch.object(self.asr, "ensure_package"), \
                mock.patch.object(self.asr, "fetch"), mock.patch.object(self.asr, "_complete_async") as complete, \
                mock.patch.object(onnx_gpu, "prepare_cuda"), mock.patch.object(self.asr, "queue_threads", return_value=4), \
                mock.patch.dict(self.asr._loaded, {}, clear=True), mock.patch.dict(self.asr._made, {}, clear=True):
            self.asr._load("gigaam-v3")  # not downloaded yet: fp32, its int8 fetched in the background
            complete.assert_called_with("gigaam-v3")
            for name in self.asr.ONNX_MODELS["gigaam-v3"]["variants"]["cpu"]["files"]:
                (self.dir / "gigaam-v3" / name).write_bytes(b"x")
            self.asr._load("gigaam-v3")  # the next job: int8
            self.asr._load("gigaam-v3", gpu=True)
            self.asr._load("parakeet-v3")
        got = [(c.args[0], c.kwargs.get("quantization")) for c in fake.load_model.call_args_list]
        self.assertEqual(got, [("gigaam-v3-e2e-rnnt", None), ("gigaam-v3-e2e-rnnt", "int8"),
                               ("gigaam-v3-e2e-rnnt", None), ("nemo-parakeet-tdt-0.6b-v3", None)])

    def test_recognize_phrase_cuts_sentences_at_words(self):
        from types import SimpleNamespace

        res = SimpleNamespace(text="Да. Хорошо", tokens=["▁Да", ".", "▁Хо", "рошо"], timestamps=[0.1, 0.3, 1.2, 1.5])
        plain = mock.Mock()
        plain.recognize.return_value = res
        with mock.patch.object(self.asr, "_load"), mock.patch.dict(self.asr._plain, {"gigaam-v3@live": plain}):
            out = self.asr.recognize_phrase("gigaam-v3", np.zeros(2 * SR, dtype=np.float32))
            self.assertEqual(self.asr.recognize_phrase("gigaam-v3", np.zeros(100, dtype=np.float32)), [])
        self.assertEqual([o[2] for o in out], ["Да.", "Хорошо"])
        self.assertEqual(out[1][0], 1.2)
        self.assertEqual(out[1][1], 2.0)


if __name__ == "__main__":
    unittest.main()
