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

    def test_hours_of_recordings_not_transcribed_yet_or_cancelled(self):
        """Reported by the user: the meeting hours stood still. The length was written only when a
        transcription began, so a recording waiting in the queue counted 0 hours, and a cancelled one was
        not counted at all."""
        import tempfile
        from pathlib import Path
        from unittest import mock

        folder = Path(tempfile.mkdtemp())
        ids = []
        for title, status in (("В очереди", "queued"), ("Отменённая", "cancelled"), ("Сломанная", "failed")):
            media = folder / f"{status}.wav"
            media.write_bytes(b"x")
            m = database.create_meeting(title, media.name, str(media))
            with database._db_lock:
                conn = database.get_connection()
                conn.execute("UPDATE meetings SET recorded_at = ?, duration = 0 WHERE id = ?", ("2026-11-18 10:00:00", m["id"]))
                conn.commit()
                conn.close()
            database.update_meeting_progress(m["id"], status=status, progress=0)
            ids.append(m["id"])
        with mock.patch("app.audio_utils.get_media_duration", return_value=2700.0) as probe:
            d = dashboard.build("week", today=self.TODAY)
            self.assertEqual(d["kpi"]["meetings"], 2)  # the failed one is no meeting
            self.assertEqual(d["kpi"]["hours"], 1.5)
            self.assertEqual(probe.call_count, 2)
            dashboard.build("week", today=self.TODAY)
            self.assertEqual(probe.call_count, 2)  # kept: the files are read once
        self.assertEqual(database.get_meeting(ids[0])["duration"], 2700.0)

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

    def test_meetings_are_read_without_their_transcripts(self):
        """The period's meetings: the protocol and each speaker's talk are read in one query, not a
        get_meeting (every word, versions, translations) per meeting; the user's share as before."""
        from unittest import mock

        mid = self._meeting("Молчун", "2026-11-17")
        segs = [{"id": 1, "start": 0, "end": 30, "speaker": "SPEAKER_01", "text": "длинная речь", "words": [{"word": "x"}]},
                {"id": 2, "start": 30, "end": 31, "speaker": "SPEAKER_00", "text": "да"},
                {"id": 3, "start": 31, "end": 90, "speaker": "SPEAKER_00", "text": "  "}]  # no words: not talk
        database.save_meeting_results(mid, segments=segs)
        with mock.patch("app.database.get_meeting", side_effect=AssertionError("transcript read")):
            row = dashboard.detail("meetings", "week", today=self.TODAY)["meetings"][0]
        self.assertEqual((row["id"], row["my_share"]), (mid, 3.2))  # 1 s of 31
        self.assertEqual(row["reasons"], ["silent"])

    def test_a_series_giving_nothing_lately(self):
        """Asked by the user: «Серии без отдачи» — the newest meetings of a series, three in a row, gave
        no decision and no task; one with a decision before them does not count."""
        from app import series

        sid = series.create_series("Еженедельный синк")
        good = self._meeting("Синк 1", "2026-11-03", protocol="## Решения\n- Выпускать\n")
        dull = [self._meeting(f"Синк {i}", f"2026-11-{9 + i:02d}", protocol="## Обзор\n- Поговорили\n") for i in (2, 3, 4)]
        for mid in [good, *dull]:
            database.update_meeting_fields(mid, series_id=sid)
        d = dashboard.build("week", today=self.TODAY)
        self.assertEqual([(x["name"], x["streak"], x["last"]["id"]) for x in d["dull_series"]], [("Еженедельный синк", 3, dull[-1])])
        commitments.create("Прислать отчёт", "Мария", meeting_id=dull[-1])  # the newest one gave a task
        self.assertEqual(dashboard.build("week", today=self.TODAY)["dull_series"], [])


if __name__ == "__main__":
    unittest.main()
