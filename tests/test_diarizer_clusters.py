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

    def _meeting(self, sizes, outliers=4, spread=0.9):
        """A call: every voice through the same codec (a shared part), uneven talk, and a few phrases
        that are no one's voice (a laugh, a noise)."""
        common = self.rng.normal(size=192)
        embs, truth, durs = [], [], []
        for i, n in enumerate(sizes):
            embs.append(_voice(self.rng, common + self.rng.normal(size=192) * 0.9, n, spread))
            truth += [i] * n
            durs += list(self.rng.uniform(0.8, 8.0, size=n))
        for _ in range(outliers):
            embs.append(_voice(self.rng, common, 1, 1.6))
            truth.append(-1)
            durs.append(3.0)
        return np.vstack(embs).astype(np.float32), np.array(durs, dtype=np.float32), np.array(truth)

    def _agrees(self, labels, truth):
        from sklearn.metrics import adjusted_rand_score

        mask = truth >= 0
        return adjusted_rand_score(truth[mask], labels[mask])

    def test_six_said_with_stray_phrases_gives_six_speakers_not_one(self):
        # Stray phrases took five of the six groups and the whole meeting went to one speaker
        embs, durs, truth = self._meeting([120, 60, 40, 25, 15, 10])
        labels = _determine_clusters(embs, durs, num_speakers_hint=6)
        self.assertEqual(len(set(labels.tolist())), 6)
        self.assertGreater(self._agrees(labels, truth), 0.95)

    def test_auto_finds_several_voices_of_one_call(self):
        embs, durs, truth = self._meeting([50] * 6)
        labels = _determine_clusters(embs, durs)
        self.assertEqual(len(set(labels.tolist())), 6)
        self.assertGreater(self._agrees(labels, truth), 0.95)

    def test_a_count_said_is_the_most_there_are(self):
        # Ten invited, two spoke: the two are not cut into more speakers
        embs, durs, truth = self._meeting([100, 50])
        labels = _determine_clusters(embs, durs, num_speakers_hint=10)
        self.assertEqual(len(set(labels.tolist())), 2)

    def test_a_count_said_gives_what_auto_finds_within_it(self):
        # «4 said» grouped worse than Auto: within 2..4 the best-scoring split was often three groups
        embs, durs, truth = self._meeting([90, 60, 35, 20])
        auto = _determine_clusters(embs, durs)
        said = _determine_clusters(embs, durs, num_speakers_hint=4)
        self.assertEqual(len(set(said.tolist())), 4)
        self.assertEqual(said.tolist(), auto.tolist())
        self.assertGreater(self._agrees(said, truth), 0.95)

    def test_more_voices_than_said_the_least_heard_is_taken_apart(self):
        """AMI with 4 said: Auto found 5, the fifth a little group of scraps; joined whole to the closest
        group, two real people were put together (wrong person 3 % -> 11 % of the time)."""
        from app.diarizer import _fold_least_heard

        common = self.rng.normal(size=192)
        a_base = common + self.rng.normal(size=192) * 0.9
        bases = [a_base, a_base + self.rng.normal(size=192) * 0.5,  # two alike voices, both talk a lot
                 common + self.rng.normal(size=192) * 0.9, common + self.rng.normal(size=192) * 0.9]
        embs, truth, labels = [], [], []
        for v, n in enumerate((60, 50, 40, 30)):
            embs.append(_voice(self.rng, bases[v], n, 0.3))
            truth += [v] * n
            labels += [v] * n
        scraps = [0, 2, 3, 3, 1, 2]  # whose scraps the fifth group really holds
        for v in scraps:
            embs.append(_voice(self.rng, bases[v] + common * 0.8, 1, 0.3))
            truth.append(v)
            labels.append(4)
        embs = np.vstack(embs).astype(np.float32)
        durs = np.r_[np.full(180, 5.0), np.full(len(scraps), 1.0)].astype(np.float32)
        truth, labels = np.array(truth), np.array(labels)
        out = _fold_least_heard(embs, durs, labels, 4)
        self.assertEqual(len(set(out.tolist())), 4)
        for v in range(4):  # each real voice is one speaker and no two share one
            self.assertEqual(len(set(out[truth == v][:30].tolist())), 1)
        self.assertEqual(len({int(out[truth == v][0]) for v in range(4)}), 4)
        self.assertGreater(self._agrees(out, truth), 0.9)  # the scraps went to their people

    def test_more_voices_than_said_each_voice_stays_whole(self):
        embs, durs, truth = self._meeting([80, 60, 40, 30, 25])
        labels = _determine_clusters(embs, durs, num_speakers_hint=4)
        self.assertEqual(len(set(labels.tolist())), 4)
        for v in range(5):  # the least heard voice goes into others; the rest stay whole
            if v != 4:
                self.assertEqual(len(set(labels[truth == v].tolist())), 1)

    def test_one_voice_of_a_call_stays_one_speaker(self):
        embs, durs, _ = self._meeting([200], outliers=6, spread=1.1)
        self.assertEqual(set(_determine_clusters(embs, durs).tolist()), {0})

    def test_a_short_recording_still_splits_into_the_count_said(self):
        a = _voice(self.rng, self.voice_a, 1, 0.1)
        b = _voice(self.rng, self.voice_b, 2, 0.1)
        embs = np.vstack([a, b]).astype(np.float32)
        durs = np.array([5.0, 5.0, 5.0], dtype=np.float32)
        self.assertEqual(len(set(_determine_clusters(embs, durs, num_speakers_hint=2).tolist())), 2)


if __name__ == "__main__":
    unittest.main()
