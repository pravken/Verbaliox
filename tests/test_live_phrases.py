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


class ForcedCutWithoutBrokenWordsTest(unittest.TestCase):
    """A word cut in half at 20 s was heard by both phrases (bench-report/asr-2026-11-check.md): «которых ко
    которых», «и и вправду», and a line of one character from a phrase of 0.04 s."""

    def test_the_cut_goes_into_a_gap_between_words_not_into_a_dip_inside_one(self):
        probs = [0.95] * _sec(25)
        probs[_sec(13)] = 0.2   # a gap between words, below the end of speech
        probs[_sec(18)] = 0.5   # a dip inside a word: the weakest of the last 4 s, but still speech
        out, _ = _run(probs + [0.0] * _sec(1))
        self.assertTrue(out[0][2])
        self.assertEqual(out[0][1], _sec(13) * F + F // 2)  # before: in the middle of the word at 18 s
        self.assertEqual(out[0][1], out[1][0])

    def test_of_the_gaps_in_the_last_seconds_the_weakest(self):
        probs = [0.95] * _sec(25)
        probs[_sec(12)] = 0.1
        probs[_sec(17)] = 0.3
        probs[_sec(18.5)] = 0.2
        out, _ = _run(probs + [0.0] * _sec(1))
        self.assertEqual(out[0][1], _sec(18.5) * F + F // 2)

    def test_without_a_gap_at_the_weakest_point_as_before(self):
        probs = [0.95] * _sec(25)
        probs[_sec(18)] = 0.5
        out, _ = _run(probs + [0.0] * _sec(1))
        self.assertEqual(out[0][1], _sec(18) * F + F // 2)

    def test_the_repeated_word_at_the_seam_is_dropped(self):
        self.assertEqual(lp.drop_seam_repeat("которых", "ко которых мы говорили."), "мы говорили.")
        self.assertEqual(lp.drop_seam_repeat("и", "И вправду так."), "вправду так.")
        self.assertEqual(lp.drop_seam_repeat("Которых,", "которых нет."), "нет.")
        self.assertEqual(lp.drop_seam_repeat("и", "Вправду так."), "Вправду так.")  # nothing repeated
        self.assertEqual(lp.drop_seam_repeat("которых", "к ним."), "к ним.")  # one letter: a word of its own
        self.assertEqual(lp.drop_seam_repeat("", "и так."), "и так.")
        self.assertEqual(lp.last_word("Говорили о тех, которых."), "которых")

    def test_a_tail_of_the_cut_is_no_line(self):
        self.assertTrue(lp.tail_fragment(int(0.04 * SR), "а"))
        self.assertTrue(lp.tail_fragment(int(0.5 * SR), "а."))
        self.assertFalse(lp.tail_fragment(int(0.5 * SR), "да."))
        self.assertFalse(lp.tail_fragment(int(2.0 * SR), "Я."))  # a whole phrase of one word stays


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


class DraftPaceTest(unittest.TestCase):
    """The draft of the phrase being spoken: every 0.3 s of audio on average, never sooner than three times the time
    the last one took."""

    def _drafts(self, seconds, cost, piece=0.25):
        pace = lp.DraftPace()
        at, made = [], 0.0
        while made < seconds - 1e-9:
            made += piece
            if pace.due(made):
                pace.done(made, cost)
                at.append(made)
        return at

    def test_the_interval_follows_the_recognition_time(self):
        pace = lp.DraftPace()
        self.assertEqual(pace.interval(), lp.DRAFT_MIN_SEC)
        pace.done(1.0, 0.05)
        self.assertEqual(pace.interval(), lp.DRAFT_MIN_SEC)  # a fast draft: the floor of 0.3 s
        pace.done(2.0, 0.4)
        self.assertAlmostEqual(pace.interval(), 1.2)  # a slow one: three times its time

    def test_pieces_of_a_quarter_second_keep_the_interval_on_average(self):
        at = self._drafts(30.0, 0.02)
        gaps = np.diff(at)
        self.assertAlmostEqual(30.0 / len(at), lp.DRAFT_MIN_SEC, delta=0.03)
        self.assertGreaterEqual(gaps.min(), 0.25 - 1e-9)  # never two drafts on one piece
        self.assertLessEqual(gaps.max(), 0.5 + 1e-9)

    def test_a_slow_computer_gets_fewer_drafts_not_a_backlog(self):
        at = self._drafts(30.0, 0.3)  # each draft takes 0.3 s: one every 0.9 s or more
        self.assertLessEqual(len(at), 30.0 / 0.9 + 1)
        self.assertGreaterEqual(np.diff(at).min(), 0.45 - 1e-9)

    def test_after_a_delay_no_burst_of_drafts(self):
        pace = lp.DraftPace()
        pace.done(1.0, 0.02)
        self.assertTrue(pace.due(5.0))  # the model was busy for 4 s
        pace.done(5.0, 0.02)
        self.assertFalse(pace.due(5.1))
        self.assertTrue(pace.due(5.3))

    def test_a_new_phrase_drafts_at_once(self):
        pace = lp.DraftPace()
        pace.done(1.0, 0.02)
        pace.restart()
        self.assertTrue(pace.due(1.05))


class _FakeVad:
    """Speech where the audio is loud."""

    made = 0  # how many were made (each is an InferenceSession of the Silero VAD)

    def __init__(self, *_a):
        type(self).made += 1
        self.resets = 0

    def prob(self, frame):
        return 0.95 if float(np.abs(frame).max()) > 0.1 else 0.02

    def reset(self):
        self.resets += 1


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

    def test_drafts_while_speaking_every_third_of_a_second(self):
        """Pieces of 0.25 s as the page sends them: the draft of the phrase being spoken every ~0.3 s of speech."""
        s = self._session()
        self._feed(s, np.full(int(12 * SR), 0.5, dtype=np.float32), piece=0.25)
        self.assertGreaterEqual(len(self.calls), 12 / 0.5)
        self.assertLessEqual(len(self.calls), 12 / lp.DRAFT_MIN_SEC + 1)
        self.assertTrue(s.partial)

    def test_no_draft_in_a_pause(self):
        s = self._session()
        self._feed(s, np.full(2 * SR, 0.5, dtype=np.float32), piece=0.25)
        n = len(self.calls)
        self._feed(s, np.zeros(int(0.45 * SR), dtype=np.float32), piece=0.15)  # the pause before the phrase ends
        self.assertLessEqual(len(self.calls) - n, 1)  # at most the draft that hears the last word
        self.assertTrue(s.partial)

    def test_a_slow_draft_spaces_the_drafts(self):
        """A recognition of 0.25 s per draft (on a fake clock): a draft every 0.75 s or more."""
        s = self._session()
        clock = [0.0]

        def slow(model, audio):
            clock[0] += 0.25
            return self._recognize(model, audio)

        with mock.patch("app.asr_onnx.recognize_phrase", side_effect=slow), \
                mock.patch.object(lp, "_clock", lambda: clock[0]):
            self._feed(s, np.full(int(12 * SR), 0.5, dtype=np.float32), piece=0.25)
        self.assertGreaterEqual(len(self.calls), 12 / 1.0)
        self.assertLessEqual(len(self.calls), 12 / 0.75 + 1)
        self.assertTrue(s.partial)

    def test_pieces_of_a_quarter_second_go_into_the_room_after_the_audio(self):
        """A piece every 0.25 s: the audio kept is not copied for each one, cuts keep the times, nothing is lost."""
        from app import live

        with mock.patch.object(live, "caption_onnx_model", return_value=None):
            s = live.LiveSession("ru", None)
        sig = (np.arange(12 * SR) % 20000 / 20000.0 - 0.5).astype(np.float32)
        n = SR // 4
        copies = 0
        for i in range(0, sig.size, n):
            before = s._buf
            s.add_pcm16(_pcm(sig[i:i + n]))
            copies += s._buf is not before
            if i == 6 * SR:
                with s._audio_lock:
                    s._cut(5 * SR)
        self.assertLessEqual(copies, 4)
        self.assertEqual(s.base, 5 * SR)
        self.assertEqual(s.audio.size, 7 * SR)
        want = np.round(sig[5 * SR:] * 32767) / 32768.0
        self.assertTrue(np.allclose(s.audio, want, atol=1e-4))

    def _seam(self, first, second, tail_sec=0.0, tail_text=""):
        """Lines of 20.5 s of speech without a pause cut by force and recognized by a fake that hears a word at the
        seam twice; with tail_sec, the cut leaves only that much of the speech."""
        s = self._session()

        def heard(model, audio):
            sec = audio.size / SR
            if sec >= 19.5:
                return [(0.0, sec, first)]
            return [(0.0, sec, tail_text if tail_sec else second)]

        self.patches[-1].stop()
        p = mock.patch("app.asr_onnx.recognize_phrase", side_effect=heard)
        p.start()
        self.addCleanup(p.stop)
        self.patches = self.patches[:-1]
        speech = (20.0 + tail_sec) if tail_sec else 22.0
        self._feed(s, np.concatenate([np.full(int(speech * SR), 0.5, dtype=np.float32), np.zeros(SR, dtype=np.float32)]))
        return [x["text"] for x in s.lines]

    def test_the_word_cut_in_half_is_not_repeated(self):
        self.assertEqual(self._seam("Говорили о тех, которых", "ко которых мы ждали."),
                         ["Говорили о тех, которых", "мы ждали."])

    def test_a_repeated_conjunction_is_not_repeated(self):
        self.assertEqual(self._seam("Он сказал, и", "и вправду так."), ["Он сказал, и", "вправду так."])

    def test_a_tail_of_one_letter_is_no_line(self):
        self.assertEqual(self._seam("Говорили о тех, которых", "", tail_sec=0.06, tail_text="х"),
                         ["Говорили о тех, которых"])

    def test_the_translator_gets_the_finals(self):
        s = self._session()
        s.translator = mock.Mock()
        s.draft = True
        self._feed(s, np.concatenate([np.full(2 * SR, 0.5, dtype=np.float32), np.zeros(SR, dtype=np.float32)]))
        s.translator.add_lines.assert_called_once()
        s.translator.set_draft.assert_called()

    def test_translation_turned_off_meanwhile_loses_nothing(self):
        """Another request's configure() sets the translator to None while the step uses it: no AttributeError (the
        step failed with it and its lines were not handed over)."""
        s = self._session()
        tr = mock.Mock()
        tr.add_lines.side_effect = lambda lines: setattr(s, "translator", None)  # configure() in another thread
        s.translator = tr
        self._feed(s, np.concatenate([np.full(2 * SR, 0.5, dtype=np.float32), np.zeros(SR, dtype=np.float32)]))
        self.assertEqual(s.error, "")
        tr.add_lines.assert_called_once()
        tr.reset_draft.assert_called_once()
        self.assertEqual(len(s.lines), 1)

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


class WindowPhraseDraftTest(unittest.TestCase):
    """English with Parakeet: the final lines from the window as before, and between its runs the draft of the phrase
    being spoken alone, every ~0.3 s."""

    def setUp(self):
        from app.database import init_db

        init_db()

    def _session(self, window_sec=0.0, draft_sec=0.0):
        from app import asr_onnx, live

        with mock.patch.object(live, "caption_onnx_model", return_value="parakeet-v3"):
            s = live.LiveSession("en", None)
        self.windows, self.phrases, self.at_window = [], [], []
        clock = self.clock = [0.0]
        self.window_sec = window_sec  # a number, or a list: the time of each run in turn (the last one repeats)

        def window(model, audio):
            costs = self.window_sec if isinstance(self.window_sec, list) else [self.window_sec]
            clock[0] += costs[min(len(self.windows), len(costs) - 1)]
            self.windows.append(audio.size)
            self.at_window.append(len(self.phrases))
            out, loud = [], np.abs(audio) > 0.1
            k = 0
            while k < audio.size:
                if not loud[k]:
                    k += 1
                    continue
                e = k
                while e < audio.size and loud[e]:
                    e += 1
                out.append((k / SR, e / SR, "Alpha." if abs(float(audio[k]) - 0.5) < 0.01 else "beta"))
                k = e
            return out

        def phrase(model, audio):
            clock[0] += draft_sec
            self.phrases.append(audio.size)
            return [(0.0, audio.size / SR, f"beta {len(self.phrases)}")]

        patches = [mock.patch.object(asr_onnx, "live_phrases", return_value=False),
                   mock.patch.object(asr_onnx, "is_loaded", return_value=True),
                   mock.patch.object(lp, "SileroStream", _FakeVad),
                   mock.patch.object(asr_onnx, "recognize_array", side_effect=window),
                   mock.patch.object(asr_onnx, "recognize_phrase", side_effect=phrase),
                   mock.patch.object(live, "_clock", lambda: clock[0]),
                   mock.patch.object(lp, "_clock", lambda: clock[0])]
        _FakeVad.made = 0
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in reversed(patches)])
        return s

    def _feed(self, s, sig, piece=0.25):
        n = int(piece * SR)
        drafts = []
        for i in range(0, sig.size, n):
            s.add_pcm16(_pcm(sig[i:i + n]))
            s.step()
            if s.partial and (not drafts or drafts[-1] != s.partial):
                drafts.append(s.partial)
        return drafts

    def _speech(self):
        quiet = np.zeros(SR, dtype=np.float32)
        first = np.full(SR, 0.5, dtype=np.float32)
        pause = np.zeros(int(0.7 * SR), dtype=np.float32)
        second = np.full(int(2.8 * SR), 0.3, dtype=np.float32)
        return np.concatenate([quiet, first, pause, second])  # 5.5 s: speech 1–2 s and 2.7–5.5 s

    def test_the_draft_follows_the_phrase_between_the_window_runs(self):
        s = self._session()
        drafts = self._feed(s, self._speech())
        self.assertLessEqual(len(self.windows), 5.5 / 2.0 + 1)  # the window as often as before (every 2 s)
        self.assertGreaterEqual(len(self.phrases), 4)
        self.assertLessEqual(len(self.phrases), 5.5 / lp.DRAFT_MIN_SEC)
        # the second phrase alone: none of the first one's audio is recognized again for the draft
        self.assertLessEqual(max(self.phrases), int((5.5 - 2.7 + lp.PAD_SEC) * SR))
        # the window's draft of the first phrase stays before the draft of the phrase being spoken
        phrase_drafts = [d for d in drafts if d.startswith("Alpha. beta ")]
        self.assertTrue(phrase_drafts, drafts)
        self.assertEqual([x["text"] for x in s.lines], ["Alpha."])  # final from the window, never from a draft

    def test_the_finals_stay_the_windows(self):
        s = self._session()
        self._feed(s, np.concatenate([self._speech(), np.zeros(3 * SR, dtype=np.float32)]))
        self.assertEqual([x["text"] for x in s.lines], ["Alpha.", "beta"])

    def test_a_slow_window_keeps_its_own_draft(self):
        s = self._session(window_sec=1.0)  # a run of the window takes 1 s: the window does not keep up
        self._feed(s, self._speech())
        self.assertGreaterEqual(len(self.windows), 2)
        self.assertEqual(len(self.phrases), self.at_window[0])  # no phrase draft after the first slow run
        self.assertTrue(s.partial)

    def test_without_the_vad_the_window_as_before(self):
        s = self._session()
        with mock.patch.object(lp, "SileroStream", side_effect=RuntimeError("no VAD")):
            self._feed(s, self._speech())
        self.assertIs(s._follow, False)
        self.assertEqual(self.phrases, [])
        self.assertTrue(self.windows)

    def test_window_and_drafts_share_one_budget(self):
        """The window and the drafts of the phrase together take at most CAPTION_BUSY_SHARE of the time of the copy:
        drafts at a third of it besides the window took up to 63 % of a 4-thread copy (review of the load)."""
        from app import live

        for window_sec, draft_sec in ((0.3, 0.1), (0.5, 0.05), (0.1, 0.1)):
            s = self._session(window_sec=window_sec, draft_sec=draft_sec)
            self._feed(s, np.full(30 * SR, 0.3, dtype=np.float32))
            self.assertTrue(self.phrases, (window_sec, draft_sec))
            busy = self.clock[0] / 30.0
            self.assertLessEqual(busy, live.CAPTION_BUSY_SHARE + 0.02, (window_sec, draft_sec, busy))

    def test_the_vad_listens_while_the_drafts_are_off(self):
        """A slow window turns the drafts off; the VAD goes on hearing every frame, so turning them on again needs no
        new VAD (each was a new InferenceSession) and the phrase being spoken is known at once."""
        s = self._session(window_sec=[0.7, 0.7, 0.3])
        speech = np.full(int(9.5 * SR), 0.3, dtype=np.float32)
        self._feed(s, speech[:int(4.5 * SR)])
        self.assertFalse(s._drafts_on)  # off after a run of 0.7 s
        drafts_off = len(self.phrases)
        self.assertGreaterEqual(s._follow.cutter.pos, s.base + s.audio.size - SR // 2)  # heard to the end
        self._feed(s, speech[int(4.5 * SR):])
        self.assertTrue(s._drafts_on)  # on again after a run under 0.4 s
        self.assertGreater(len(self.phrases), drafts_off)
        self.assertEqual(_FakeVad.made, 1)

    def test_drafts_go_off_above_the_limit_and_on_only_well_below_it(self):
        from app import live

        s = self._session()
        for cost, on in ((0.3, True), (0.65, False), (0.5, False), (0.45, False), (0.35, True), (0.55, True),
                         (0.61, False)):
            s._window_ran(cost)
            self.assertEqual(s._drafts_on, on, cost)
        self.assertEqual((live.DRAFTS_OFF_SEC, live.DRAFTS_ON_SEC), (0.6, 0.4))

    def test_audio_dropped_before_the_vad_heard_it_resets_the_vad(self):
        s = self._session()
        self._feed(s, np.full(2 * SR, 0.3, dtype=np.float32))
        vad = s._follow.vad
        with s._audio_lock:
            s._cut(s.audio.size)  # dropped (a failed step) before the VAD heard what comes next
        s.base += SR
        s._follow_speech()
        self.assertIs(s._follow.vad, vad)
        self.assertEqual(vad.resets, 1)
        self.assertEqual(_FakeVad.made, 1)
