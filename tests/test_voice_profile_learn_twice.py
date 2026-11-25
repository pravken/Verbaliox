"""Two recordings naming the same new person at once (found in an audit): the voice prints were read before the
lock that writes them, both found no print of that name, and the second insert failed on the unique name. The
moment between the read and the write is reproduced with the read giving what it gave before the first write."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import voice_profiles
from app.database import init_db, update_settings


class LearnTwiceTest(unittest.TestCase):
    def test_the_second_learn_refines_the_print_the_first_one_stored(self):
        init_db()
        update_settings({"voice_profiles": "true"})
        name = "Вымышленная Тестова"
        self.addCleanup(lambda: [voice_profiles.delete_profile(p["id"]) for p in voice_profiles.list_profiles()
                                 if p["name"] == name])
        voice_profiles.learn(name, [1.0, 0.0, 0.0])
        with mock.patch.object(voice_profiles, "_load", return_value=[]):  # read before the first one wrote
            voice_profiles.learn(name, [0.0, 1.0, 0.0])
        mine = [p for p in voice_profiles.list_profiles() if p["name"] == name]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["samples"], 2)


if __name__ == "__main__":
    unittest.main()
