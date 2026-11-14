"""Text kept away from the cloud stays away: the consent holds for a model asked by name, and a
recording of a "local analysis only" folder keeps that when the folder is deleted."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest

from app import database as db
from app.database import init_db, update_settings

try:
    from app import llm
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    llm = None


@unittest.skipIf(llm is None, "app dependencies not installed")
class CloudConsentTest(unittest.TestCase):
    def test_cloud_asked_by_name_needs_the_consent(self):
        init_db()
        update_settings({"llm_cloud_consent": "false", "llm_provider": "ollama"})
        with self.assertRaises(llm.LlmError) as err:
            llm.target(model="cloud")
        self.assertIn("Подтвердите", str(err.exception))


class LocalOnlyFolderTest(unittest.TestCase):
    def test_deleting_a_protected_folder_keeps_its_recordings_protected(self):
        init_db()
        top = db.create_folder("Секретно")
        db.update_folder(top["id"], local_only=True)
        inner = db.create_folder("Внутри", top["id"])
        m = db.create_meeting("Совет", "a.wav", "a.wav")
        db.set_meeting_folder(m["id"], top["id"])
        db.delete_folder(top["id"])
        self.assertTrue(db.is_local_only(db.get_meeting(m["id"])))
        self.assertTrue(db.get_folder(inner["id"])["local_only"])

    def test_deleting_a_plain_folder_marks_nothing(self):
        init_db()
        f = db.create_folder("Обычная")
        m = db.create_meeting("Планёрка", "b.wav", "b.wav")
        db.set_meeting_folder(m["id"], f["id"])
        db.delete_folder(f["id"])
        self.assertFalse(db.is_local_only(db.get_meeting(m["id"])))


if __name__ == "__main__":
    unittest.main()
