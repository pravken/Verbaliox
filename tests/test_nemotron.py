"""Nemotron 3 Diarization's turns put on the transcript (app/diarizer.py, app/nemotron_diar.py)."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

try:
    import numpy as np

    from app import diarizer, nemotron_diar
except ImportError:  # heavy ML dependencies are not installed
    diarizer = None


def _words(*items):
    return [{"start": s, "end": e, "word": w} for s, e, w in items]


@unittest.skipIf(diarizer is None, "numpy/torch not installed")
class TurnsOnTranscriptTest(unittest.TestCase):
    TURNS = [(0.0, 5.0, 0), (5.2, 9.0, 1), (9.0, 12.0, 0)]

    def test_a_phrase_goes_to_who_covers_most_of_it(self):
        self.assertEqual(diarizer._turn_speaker(0.5, 4.5, self.TURNS), 0)
        self.assertEqual(diarizer._turn_speaker(4.0, 8.5, self.TURNS), 1)
        self.assertIsNone(diarizer._turn_speaker(20.0, 22.0, self.TURNS))  # left unmarked

    def test_a_phrase_is_cut_where_the_speaker_changes(self):
        seg = {"start": 3.0, "end": 7.0, "text": " так и сделаем да конечно", "language": "ru",
               "words": _words((3.0, 3.4, " так"), (3.4, 3.7, " и"), (3.7, 4.6, " сделаем"),
                               (5.3, 5.6, " да"), (5.7, 6.9, " конечно"))}
        out = diarizer._split_by_turns([seg], self.TURNS)
        self.assertEqual([p["text"] for p in out], ["так и сделаем", "да конечно"])
        self.assertEqual((out[1]["start"], out[1]["end"]), (5.3, 6.9))
        self.assertEqual(out[1]["language"], "ru")  # what else the line holds goes with its pieces
        whole = {"start": 0.5, "end": 4.0, "text": " одно", "words": _words((0.5, 1.0, " одно"), (1.0, 4.0, " целое"))}
        self.assertEqual(diarizer._split_by_turns([whole], self.TURNS), [whole])

    def test_unmarked_phrases_go_to_the_closest_voice(self):
        rng = np.random.default_rng(1)
        a, b = rng.normal(size=192), rng.normal(size=192)
        unit = lambda v: v / np.linalg.norm(v)  # noqa: E731
        segs = [{"start": 0.5, "end": 4.0}, {"start": 5.5, "end": 8.5}, {"start": 20.0, "end": 22.0},
                {"start": 9.5, "end": 11.5}]
        embs = np.vstack([unit(a), unit(b), unit(b + rng.normal(size=192) * 0.2), unit(a)]).astype(np.float32)
        durs = np.array([3.5, 3.0, 2.0, 2.0], dtype=np.float32)
        labels = diarizer._labels_from_turns(segs, [0, 1, 2, 3], embs, durs, self.TURNS)
        self.assertEqual(labels, [0, 1, 1, 0])  # the unmarked third phrase has the second voice

    def test_without_voice_prints_the_neighbour_decides(self):
        segs = [{"start": 0.5, "end": 4.0}, {"start": 20.0, "end": 21.0}, {"start": 5.5, "end": 8.5}]
        self.assertEqual(diarizer._labels_from_turns(segs, [], None, np.array([]), self.TURNS), [0, 0, 1])

    def test_a_count_said_takes_apart_the_least_heard(self):
        rng = np.random.default_rng(2)
        bases = [rng.normal(size=192) for _ in range(3)]
        turns = [(0, 10, 0), (10, 20, 1), (20, 21, 2), (21, 31, 0)]
        segs = [{"start": 1, "end": 9}, {"start": 11, "end": 19}, {"start": 20, "end": 21}, {"start": 22, "end": 30}]
        embs = np.vstack([bases[0], bases[1], bases[0] + rng.normal(size=192) * 0.1, bases[0]])
        embs = (embs / np.linalg.norm(embs, axis=1, keepdims=True)).astype(np.float32)
        durs = np.array([8, 8, 1, 8], dtype=np.float32)
        labels = diarizer._labels_from_turns(segs, [0, 1, 2, 3], embs, durs, turns, num_speakers_hint=2)
        self.assertEqual(labels, [0, 1, 0, 0])


@unittest.skipIf(diarizer is None, "numpy/torch not installed")
class NemotronChoiceTest(unittest.TestCase):
    def test_used_only_when_chosen_downloaded_and_the_library_is_there(self):
        with mock.patch.object(nemotron_diar, "installed", return_value=True), \
                mock.patch.object(nemotron_diar, "library_ready", return_value=True):
            self.assertTrue(nemotron_diar.usable({"diarizer_engine": "nemotron"}))
            self.assertFalse(nemotron_diar.usable({"diarizer_engine": "ecapa"}))
            self.assertFalse(nemotron_diar.usable({}))  # ECAPA by default
        with mock.patch.object(nemotron_diar, "installed", return_value=False), \
                mock.patch.object(nemotron_diar, "library_ready", return_value=True):
            self.assertFalse(nemotron_diar.usable({"diarizer_engine": "nemotron"}))

    def _diarize(self, turns_result):
        segs = [{"start": 0.5, "end": 4.0, "text": "раз"}, {"start": 5.5, "end": 8.5, "text": "два"},
                {"start": 9.5, "end": 11.5, "text": "три"}]
        rng = np.random.default_rng(3)
        a, b = rng.normal(size=192), rng.normal(size=192)
        vecs = [a / np.linalg.norm(a), b / np.linalg.norm(b), a / np.linalg.norm(a)]
        with mock.patch.object(nemotron_diar, "usable", return_value=True), \
                mock.patch.object(nemotron_diar, "turns", **turns_result), \
                mock.patch.object(diarizer.sf, "read", return_value=(np.zeros(16000 * 12, dtype=np.float32), 16000)), \
                mock.patch.object(diarizer, "_get_ecapa_encoder", return_value=object()), \
                mock.patch.object(diarizer, "_prepare_slice", return_value=np.ones(16000, dtype=np.float32)), \
                mock.patch.object(diarizer, "_embed_slices", return_value=vecs), \
                mock.patch.object(diarizer, "unload_diarizer"):
            return diarizer.diarize_and_merge_segments("x.wav", segs, device="cpu")

    def test_the_turns_decide_who_speaks(self):
        speakers, merged = self._diarize({"return_value": [(0.0, 5.0, 0), (5.2, 9.0, 1), (9.0, 12.0, 0)]})
        self.assertEqual([m["speaker"] for m in merged], ["SPEAKER_00", "SPEAKER_01", "SPEAKER_00"])
        self.assertEqual(len(speakers), 2)

    def test_a_failure_falls_back_to_ecapa(self):
        with mock.patch.object(diarizer, "_determine_clusters", wraps=diarizer._determine_clusters) as clusters:
            speakers, merged = self._diarize({"side_effect": RuntimeError("CUDA error")})
        clusters.assert_called_once()  # ECAPA groups the voices instead
        self.assertTrue(speakers and merged)


if __name__ == "__main__":
    unittest.main()
