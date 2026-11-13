"""A person's own photo (app/people.py): kept by name, moved with a rename or a merge."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import base64
import unittest

try:
    from app import database, people
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    people = None

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200


def b64(data):
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


@unittest.skipIf(people is None, "app dependencies not installed")
class PersonPhotoTest(unittest.TestCase):
    def setUp(self):
        database.init_db()
        people.init_table()
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("DELETE FROM people_directory")
            conn.commit()
            conn.close()
        d = people._photo_dir()
        if d.is_dir():
            for f in d.iterdir():
                f.unlink()

    def test_set_shown_by_name_and_its_variants_and_removed(self):
        people.set_photo("Мария Петрова", b64(JPEG))
        self.assertEqual(people.photo_path("мария петрова").read_bytes(), JPEG)
        self.assertIn("мария петрова", people.photos())
        people.update("Мария Петрова", new_name="Мария П.")  # renamed: the photo goes with her
        found = people.photos()
        self.assertIn("мария п.", found)
        self.assertIn("мария петрова", found)  # the old spelling is a variant now
        self.assertEqual(people.photo_path("Мария П.").read_bytes(), JPEG)
        self.assertTrue(people.remove_photo("Мария П."))
        self.assertEqual(people.photos(), {})

    def test_a_merge_keeps_one_photo(self):
        people.set_photo("Маша", b64(PNG))
        people.add("Мария")
        people.merge(["Мария", "Маша"])
        self.assertEqual(people.photo_path("Мария").read_bytes(), PNG)
        self.assertEqual(people.photo_path("Маша").read_bytes(), PNG)  # a variant: the same person

    def test_only_a_small_jpeg_or_png(self):
        with self.assertRaises(ValueError):
            people.set_photo("Олег", b64(b"<svg onload=alert(1)>"))
        with self.assertRaises(ValueError):
            people.set_photo("Олег", b64(JPEG + b"0" * people.PHOTO_MAX_BYTES))
        with self.assertRaises(ValueError):
            people.set_photo("Олег", "не картинка")
        self.assertEqual(people.photos(), {})


if __name__ == "__main__":
    unittest.main()
