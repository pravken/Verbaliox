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
        # the recordings of the week the filter leaves out are told (reported by the user: zeros with a filter on)
        self.assertEqual(only["outside"], d["kpi"]["meetings"] - only["kpi"]["meetings"])
        self.assertEqual(d["outside"], 0)

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

    def test_lengths_not_read_again_and_not_while_mixing(self):
        """Found in the review: every load of «Главная» ran ffprobe again on files it cannot read, and wrote
        the length of a recording still being mixed (its file not whole yet)."""
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        folder = Path(tempfile.mkdtemp())
        rows = []
        for status in ("queued", "mixing"):
            media = folder / f"{status}.wav"
            media.write_bytes(b"x")
            m = database.create_meeting(status, media.name, str(media))
            database.update_meeting_progress(m["id"], status=status, progress=0)
            rows.append(database.get_meeting(m["id"]))
        broken, mixing = rows
        with mock.patch("app.audio_utils.get_media_duration", return_value=0.0) as probe:
            self.assertEqual(database.fill_durations([dict(broken, duration=0), dict(mixing, duration=0)]), 0)
            database.fill_durations([dict(broken, duration=0)])
            self.assertEqual(probe.call_count, 1)  # the file it could not read: once, the mixing one never
        os.utime(broken["media_path"], (1_000_000_000, 1_000_000_000))  # the file changed: read again
        with mock.patch("app.audio_utils.get_media_duration", return_value=60.0) as probe:
            self.assertEqual(database.fill_durations([dict(broken, duration=0), dict(mixing, duration=0)]), 1)
            self.assertEqual(probe.call_count, 1)
        self.assertEqual(database.get_meeting(mixing["id"])["duration"], 0)

    def test_months_quarters_and_no_name_set(self):
        self.assertEqual(dashboard._bounds("month", self.TODAY)[:2], (date(2026, 11, 1), date(2026, 12, 1)))
        self.assertEqual(dashboard._bounds("quarter", self.TODAY), (date(2026, 10, 1), date(2027, 1, 1), date(2026, 7, 1)))
        self.assertEqual(dashboard._bounds("quarter", date(2026, 2, 3))[2], date(2025, 10, 1))
        database.update_settings({"my_name": ""})
        d = dashboard.build("month", today=self.TODAY)
        self.assertTrue(d["needs_me"])
        self.assertEqual(d["tasks"], [])


    def test_details_without_outcome_waiting_decisions_and_a_person(self):
        """Asked by the user: every number of the dashboard opens its details; «Ожидаю от других»; «Без итогов»."""
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

    def test_the_figures_of_six_periods(self):
        """«Статистика»: every figure with the last six periods (the current one last, as the widgets count it),
        the hours spent with each person; the protocols are read, not the transcripts."""
        from unittest import mock

        self._meeting("Сейчас", "2026-11-17", protocol="## Решения\n- Выпускать в пятницу\n")
        self._meeting("Неделю назад", "2026-11-10", names=("Олег", "Мария", "Иван"))
        self._meeting("Пустая", "2026-11-03", protocol="## Обзор\n- Поговорили\n")
        self._meeting("Давно", "2026-08-01")  # before the six weeks
        t = commitments.create("Прислать смету", "Олег")
        with database._db_lock:
            conn = database.get_connection()
            conn.execute("UPDATE commitments SET created_at = '2026-11-01T09:00:00', status = 'done', done_at = '2026-11-11T09:00:00' WHERE id = ?", (t["id"],))
            conn.commit()
            conn.close()
        with mock.patch("app.database.get_meeting", side_effect=AssertionError("transcript read")), \
                mock.patch("app.worktime.remind_hours", return_value=8.0), mock.patch("app.holidays_cal.between", return_value={}):
            d = dashboard.build("week", today=self.TODAY)
        h = d["history"]
        self.assertEqual(h["starts"], ["2026-10-12", "2026-10-19", "2026-10-26", "2026-11-02", "2026-11-09", "2026-11-16"])
        v = h["values"]
        self.assertEqual(v["meetings"], [0, 0, 0, 1, 1, 1])
        self.assertEqual(v["hours"][-1], d["kpi"]["hours"])
        self.assertEqual(v["decisions"], [0, 0, 0, 0, 0, 1])
        self.assertEqual(v["useless"][3], 1)  # analysed, no decision, no task
        self.assertEqual(v["people"][-2:], [2, 1])
        self.assertEqual(v["avg"][-1], 30)
        self.assertEqual(v["mine"][-3:], [1, 0, 0])  # open at the end of the week of 2 November, done on the 11th
        self.assertEqual(v["closed"][-3:], [0, 1, 0])
        # Monday to Wednesday gone by: 24 working hours, half an hour in meetings
        self.assertEqual((v["share"][-1], v["focus"][-1]), (2, 23.5))
        self.assertEqual(d["people"][0], {"name": "Мария", "color": "", "meetings": 1, "hours": 0.5})
        # «Частые участники» with a period of its own: a month here
        month = dashboard.people(date(2026, 11, 1), date(2026, 12, 1))
        self.assertEqual([(p["name"], p["meetings"], p["hours"]) for p in month], [("Мария", 3, 1.5), ("Иван", 1, 0.5)])

    def test_the_people_route_takes_up_to_a_year(self):
        from fastapi.testclient import TestClient

        from app import main

        self._meeting("Синк", "2026-11-17")
        c = TestClient(main.app, base_url="http://127.0.0.1:8790")
        c.cookies.set("vs_session_8790", main.SESSION_TOKEN)
        r = c.get("/api/dashboard/people", params={"start": "2026-01-01", "end": "2027-01-01"})
        self.assertEqual([p["name"] for p in r.json()["people"]], ["Мария"])
        self.assertEqual(c.get("/api/dashboard/people", params={"start": "2025-01-01", "end": "2027-01-01"}).status_code, 400)
        self.assertEqual(c.get("/api/dashboard/people", params={"start": "x", "end": "2027-01-01"}).status_code, 400)

    def test_a_series_giving_nothing_lately(self):
        """Asked by the user: «Серии без результатов» — the newest meetings of a series, three in a row, gave
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

    def test_the_year_its_months_and_its_years(self):
        """Asked by the user: the year as a period — 1 January to 1 January, its hours by month, its trend over
        the years there are data of (six at most)."""
        from unittest import mock

        self.assertEqual(dashboard._bounds("year", self.TODAY), (date(2026, 1, 1), date(2027, 1, 1), date(2025, 1, 1)))
        self.assertEqual(dashboard._bounds("year", date(2026, 1, 1))[:2], (date(2026, 1, 1), date(2027, 1, 1)))
        self.assertEqual(dashboard._periods_back("year", date(2026, 1, 1), 3),
                         [(date(2024, 1, 1), date(2025, 1, 1)), (date(2025, 1, 1), date(2026, 1, 1)), (date(2026, 1, 1), date(2027, 1, 1))])
        self._meeting("Весна", "2026-03-10")
        self._meeting("Осень", "2026-11-17")
        self._meeting("Год назад", "2025-11-12")
        with mock.patch("app.worktime.remind_hours", return_value=8.0), mock.patch("app.holidays_cal.between", return_value={}):
            d = dashboard.build("year", today=self.TODAY)
        self.assertEqual((d["start"], d["end"], d["past"]), ("2026-01-01", "2027-01-01", False))
        self.assertEqual([b["key"][:7] for b in d["buckets"]][:3], ["2026-01", "2026-02", "2026-03"])
        self.assertEqual(len(d["buckets"]), 12)
        self.assertEqual([b["hours"] for b in d["buckets"] if b["hours"]], [0.5, 0.5])
        self.assertEqual(d["history"]["starts"], ["2025-01-01", "2026-01-01"])  # no year before the first recording
        self.assertEqual(d["history"]["values"]["meetings"], [1, 2])
        self.assertEqual(d["kpi"]["meetings_before"], 1)

    def test_a_past_period_is_complete(self):
        """Asked by the user: any past week, month, quarter or year. Its working days are all gone by, its
        open tasks are those open at its end; the current period is today's; a later day means today."""
        from unittest import mock

        self._meeting("Октябрь", "2026-10-14")
        t = commitments.create("Прислать смету", "Олег", due_date="2026-10-20")
        with database._db_lock:
            conn = database.get_connection()  # made in October, done in November
            conn.execute("UPDATE commitments SET created_at = '2026-10-05T09:00:00', status = 'done', done_at = '2026-11-03T09:00:00' WHERE id = ?", (t["id"],))
            conn.commit()
            conn.close()
        self.assertEqual(dashboard.anchor("month", date(2026, 10, 14), self.TODAY),
                         (date(2026, 10, 1), date(2026, 11, 1), date(2026, 9, 1), date(2026, 10, 31), True))
        self.assertEqual(dashboard.anchor("month", None, self.TODAY)[3:], (self.TODAY, False))
        self.assertEqual(dashboard.anchor("week", date(2027, 5, 1), self.TODAY)[0], date(2026, 11, 16))  # not ahead of today
        with mock.patch("app.worktime.remind_hours", return_value=8.0), mock.patch("app.holidays_cal.between", return_value={}):
            d = dashboard.build("month", today=self.TODAY, at=date(2026, 10, 14))
            now = dashboard.build("month", today=self.TODAY)
        self.assertEqual((d["start"], d["end"], d["past"], d["asof"], d["today"]), ("2026-10-01", "2026-11-01", True, "2026-10-31", "2026-11-18"))
        self.assertEqual(d["kpi"]["meetings"], 1)
        # open at the end of October and overdue by then; done now
        self.assertEqual((d["kpi"]["open"], d["kpi"]["overdue"]), (1, 1))
        self.assertEqual((now["kpi"]["open"], now["kpi"]["overdue"]), (0, 0))
        # every working day of October counted: 22 days of 8 hours, half an hour in meetings
        self.assertEqual(d["history"]["values"]["focus"][-1], 22 * 8 - 0.5)
        self.assertEqual(d["history"]["starts"][-1], "2026-10-01")
        self.assertEqual([r["title"] for r in d["recent"]], ["Октябрь"])

    def test_no_working_time_is_made_up_before_the_first_data(self):
        """Reported in review: a year with no recording showed «2088 ч рабочего времени без встреч». A period
        that ends before the first day with data (or with no data at all) has no share and no time without
        meetings: None, shown as «—»; the counts stay zero."""
        from unittest import mock

        with mock.patch("app.worktime.remind_hours", return_value=8.0), mock.patch("app.holidays_cal.between", return_value={}):
            empty = dashboard.build("year", today=self.TODAY, at=date(2025, 6, 1))
            self._meeting("Первая", "2026-11-17")
            before = dashboard.build("year", today=self.TODAY, at=date(2025, 6, 1))
            week = dashboard.build("week", today=self.TODAY)
            year_ago = dashboard.build("week", today=self.TODAY, compare="year")
        for d in (empty, before):
            v = d["history"]["values"]
            self.assertEqual((v["focus"], v["share"], v["meetings"]), ([None], [None], [0]))
        v = week["history"]["values"]
        self.assertEqual(v["focus"][:5], [None] * 5)  # the weeks before 17 November
        self.assertEqual((v["share"][-1], v["focus"][-1]), (2, 23.5))
        self.assertIsNone(week["history"]["before"]["focus"])
        self.assertIsNone(year_ago["history"]["before"]["focus"])

    def test_compared_with_the_same_days_a_year_earlier(self):
        """Asked by the user: the figures against the period before or the same days a year earlier."""
        from unittest import mock

        self.assertEqual(dashboard._year_ago(date(2028, 2, 29)), date(2027, 2, 28))
        self._meeting("Сейчас", "2026-11-17")
        self._meeting("Неделю назад", "2026-11-10")
        self._meeting("Год назад 1", "2025-11-17")
        self._meeting("Год назад 2", "2025-11-21")
        with mock.patch("app.worktime.remind_hours", return_value=8.0), mock.patch("app.holidays_cal.between", return_value={}):
            prev = dashboard.build("week", today=self.TODAY)
            year = dashboard.build("week", today=self.TODAY, compare="year")
            past = dashboard.build("month", today=self.TODAY, at=date(2026, 10, 2), compare="year")
        self.assertEqual(prev["history"]["compare"], {"kind": "prev", "start": "2026-11-09", "end": "2026-11-16"})
        self.assertEqual((prev["kpi"]["meetings_before"], prev["history"]["before"]["meetings"]), (1, 1))
        # the same days: 16–22 November 2025
        self.assertEqual(year["history"]["compare"], {"kind": "year", "start": "2025-11-16", "end": "2025-11-23"})
        self.assertEqual((year["kpi"]["meetings_before"], year["history"]["before"]["meetings"]), (2, 2))
        self.assertEqual(year["history"]["before"]["hours"], 1.0)
        self.assertEqual(year["history"]["values"]["meetings"][-2:], [1, 1])  # the trend stays by period
        self.assertEqual(past["history"]["compare"]["start"], "2025-10-01")

    def test_the_route_takes_a_day_and_a_comparison(self):
        from fastapi.testclient import TestClient

        from app import main

        c = TestClient(main.app, base_url="http://127.0.0.1:8790")
        c.cookies.set("vs_session_8790", main.SESSION_TOKEN)
        r = c.get("/api/dashboard", params={"period": "year", "at": "2025-06-01", "compare": "year"})
        self.assertEqual((r.json()["start"], r.json()["past"], r.json()["compare"]), ("2025-01-01", True, "year"))
        self.assertEqual(c.get("/api/dashboard", params={"at": "2025-13-01"}).status_code, 400)
        self.assertEqual(c.get("/api/dashboard", params={"at": "1900-01-01"}).status_code, 400)
        r = c.get("/api/dashboard/detail", params={"kind": "meetings", "period": "month", "at": "2025-06-10"})
        self.assertEqual((r.json()["start"], r.json()["end"]), ("2025-06-01", "2025-07-01"))


if __name__ == "__main__":
    unittest.main()
