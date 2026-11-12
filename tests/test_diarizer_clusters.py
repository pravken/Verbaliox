import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

try:
    import numpy as np

    from app.diarizer import _determine_clusters
except ImportError:  # heavy ML dependencies are not installed (e.g. in CI)
    _determine_clusters = None


def _voice(rng, base, n, spread):
    vecs = base + rng.normal(0, spread, size=(n, base.size))
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


@unittest.skipIf(_determine_clusters is None, "numpy/torch/sklearn not installed")
class DetermineClustersTest(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(0)
        self.voice_a = self.rng.normal(size=192)
        self.voice_b = self.rng.normal(size=192)

    def test_single_outlier_phrase_is_not_a_new_speaker(self):
        same = _voice(self.rng, self.voice_a, 3, 0.25)
        outlier = _voice(self.rng, self.voice_a + self.voice_b * 1.2, 1, 0.05)
        embs = np.vstack([same[:2], outlier, same[2:]]).astype(np.float32)
        durs = np.array([5.2, 9.0, 2.5, 5.2], dtype=np.float32)
        self.assertEqual(set(_determine_clusters(embs, durs).tolist()), {0})

    def test_two_real_speakers_are_separated(self):
        a = _voice(self.rng, self.voice_a, 4, 0.25)
        b = _voice(self.rng, self.voice_b, 4, 0.25)
        embs = np.vstack([a, b]).astype(np.float32)
        durs = np.array([5.0, 4.0, 6.0, 3.0, 4.5, 5.5, 3.5, 6.0], dtype=np.float32)
        labels = _determine_clusters(embs, durs).tolist()
        self.assertEqual(labels[:4], [0, 0, 0, 0])
        self.assertEqual(labels[4:], [1, 1, 1, 1])

    def _voices(self, k, n=5, spread=0.25):
        bases = [self.rng.normal(size=192) for _ in range(k)]
        embs = np.vstack([_voice(self.rng, b, n, spread) for b in bases]).astype(np.float32)
        durs = np.full(len(embs), 5.0, dtype=np.float32)
        return embs, durs

    def test_a_count_of_one_or_two_said_is_corrected_to_clearly_more_voices(self):
        embs, durs = self._voices(5)
        for said in (1, 2):
            self.assertEqual(len(set(_determine_clusters(embs, durs, num_speakers_hint=said).tolist())), 5)

    def test_three_clear_voices_correct_a_count_of_two(self):
        embs, durs = self._voices(3)
        self.assertEqual(len(set(_determine_clusters(embs, durs, num_speakers_hint=2).tolist())), 3)

    def test_a_count_said_stays_when_the_voices_do_not_clearly_make_three(self):
        embs, durs = self._voices(2)
        self.assertEqual(set(_determine_clusters(embs, durs, num_speakers_hint=1).tolist()), {0})
        # three "voices" that are one voice said a little differently: the count said stays
        common = self.rng.normal(size=192)
        embs = np.vstack([_voice(self.rng, common + self.rng.normal(0, 0.15, size=192), 5, 0.25) for _ in range(3)]).astype(np.float32)
        durs = np.full(len(embs), 5.0, dtype=np.float32)
        self.assertLessEqual(len(set(_determine_clusters(embs, durs, num_speakers_hint=2).tolist())), 2)


if __name__ == "__main__":
    unittest.main()
