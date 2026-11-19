"""The dashboard (app/dashboard.py): periods, the user's own tasks only, features, people, decisions."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from datetime import date

try:
    from app import commitments, database, dashboard, features
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    dashboard = None


@unittest.skipIf(dashboard is None, "app dependencies not installed")
class DashboardTest(unittest.TestCase):
    TODAY = date(2026, 11, 18)  # a Wednesday

    def setUp(self):
        database.init_db()
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("DELETE FROM meetings")
            conn.commit()
            conn.close()
        commitments._init()
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("DELETE FROM commitments")
            conn.commit()
            conn.close()
        database.update_settings({"my_name": "Олег"})

    def tearDown(self):  # the other tests count meetings and tasks of their own
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("DELETE FROM commitments")
            conn.execute("DELETE FROM meetings")
            conn.commit()
            conn.close()
        database.update_settings({"my_name": ""})

    def _meeting(self, title, day, names=("Олег", "Мария"), protocol=""):
        m = database.create_meeting(title, "a.wav", "a.wav")
        spk = {f"SPEAKER_0{i}": {"id": f"SPEAKER_0{i}", "name": n} for i, n in enumerate(names)}
        database.save_meeting_results(m["id"], segments=[{"id": 1, "start": 0, "end": 5, "speaker": "SPEAKER_00", "text": "привет"}],
                                      speakers=spk, summaries={"protocol": protocol} if protocol else None)
        with database._db_lock:  # when it was recorded and how long it lasted
            conn = database.get_connection()
            conn.execute("UPDATE meetings SET recorded_at = ?, duration = 1800 WHERE id = ?", (f"{day} 10:00:00", m["id"]))
            conn.commit()
            conn.close()
        database.update_meeting_progress(m["id"], status="completed", progress=100)
        return m["id"]

    def test_the_period_its_numbers_and_only_my_tasks(self):
        a = self._meeting("Туманы: сроки", "2026-11-17", protocol="## Решения\n- Ограничить дальность тумана\n")
        self._meeting("Прошлая неделя", "2026-11-10")
        f = features.create_feature("Туманы на картах", "#FF9F0A")
        features.set_meeting_features(a, [f["id"]])
        commitments.create("Прислать смету", "Олег", due_date="2026-11-16", meeting_id=a)
        commitments.create("Чужая задача", "Мария", due_date="2026-11-15", meeting_id=a)
        d = dashboard.build("week", today=self.TODAY)
        self.assertEqual((d["start"], d["end"]), ("2026-11-16", "2026-11-23"))
        self.assertEqual(d["kpi"]["meetings"], 1)
        self.assertEqual(d["kpi"]["meetings_before"], 1)
        self.assertEqual(d["kpi"]["hours"], 0.5)
        self.assertEqual((d["kpi"]["open"], d["kpi"]["overdue"]), (1, 1))  # the others' tasks are not counted
        self.assertEqual([t["what"] for t in d["tasks"]], ["Прислать смету"])
        self.assertEqual(d["decisions"][0]["text"], "Ограничить дальность тумана")
        self.assertEqual([(x["name"], x["meetings"], x["open"]) for x in d["features"]], [("Туманы на картах", 1, 1)])
        self.assertEqual(d["features"][0]["spark"][-1], 1)
        self.assertEqual([p["name"] for p in d["people"]], ["Мария"])  # the user is not among the people
        self.assertEqual([b["key"] for b in d["buckets"]][:2], ["2026-11-16", "2026-11-17"])
        only = dashboard.build("week", feature_id=f["id"], today=self.TODAY)
        self.assertEqual(only["kpi"]["meetings_before"], 0)

    def test_months_quarters_and_no_name_set(self):
        self.assertEqual(dashboard._bounds("month", self.TODAY)[:2], (date(2026, 11, 1), date(2026, 12, 1)))
        self.assertEqual(dashboard._bounds("quarter", self.TODAY), (date(2026, 10, 1), date(2027, 1, 1), date(2026, 7, 1)))
        self.assertEqual(dashboard._bounds("quarter", date(2026, 2, 3))[2], date(2025, 10, 1))
        database.update_settings({"my_name": ""})
        d = dashboard.build("month", today=self.TODAY)
        self.assertTrue(d["needs_me"])
        self.assertEqual(d["tasks"], [])


    def test_details_without_outcome_waiting_decisions_and_a_person(self):
        """Asked by the user: every number of the dashboard opens its details; «Жду от других»; «Без итогов»."""
        good = self._meeting("Синк", "2026-11-17", protocol="## Решения\n- Выпускать в пятницу\n")
        empty = self._meeting("Болтовня", "2026-11-18", protocol="## Обзор\n- Поговорили\n")
        commitments.create("Прислать смету", "Мария", meeting_id=good)
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("UPDATE commitments SET to_whom = 'Олег' WHERE what = 'Прислать смету'")
            conn.commit()
            conn.close()
        d = dashboard.build("week", today=self.TODAY)
        self.assertEqual((d["kpi"]["useless"], d["kpi"]["waiting"]), (1, 1))
        self.assertEqual(d["waiting"][0]["what"], "Прислать смету")
        rows = dashboard.detail("meetings", "week", today=self.TODAY)["meetings"]
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id[good]["decisions"], 1)
        self.assertEqual(by_id[good]["tasks"], 1)
        self.assertEqual(by_id[empty]["reasons"], ["no_outcome"])
        self.assertEqual([r["id"] for r in dashboard.detail("useless", "week", today=self.TODAY)["meetings"]], [empty])
        self.assertEqual([x["text"] for x in dashboard.detail("decisions", "week", today=self.TODAY)["decisions"]], ["Выпускать в пятницу"])
        self.assertEqual([t["what"] for t in dashboard.detail("waiting", "week", today=self.TODAY)["tasks"]], ["Прислать смету"])
        person = dashboard.detail("person", person="Мария", today=self.TODAY)
        self.assertEqual({m["id"] for m in person["meetings"]}, {good, empty})
        self.assertEqual([t["what"] for t in person["owes_me"]], ["Прислать смету"])


if __name__ == "__main__":
    unittest.main()
