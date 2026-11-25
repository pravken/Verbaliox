"""A cut or a video with subtitles is listed with its recording once written, never before (found in an audit):
listed before, a job refused or failed left the path of a file the user already had at that place, which «delete
with its copies» then deleted."""

import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import pending_exports, transcriber
from app.database import create_meeting, get_meeting, init_db, save_meeting_results, update_meeting_progress


class ExportListedWhenWrittenTest(unittest.TestCase):
    def setUp(self):
        init_db()
        self.dir = tests.temp_dir(self)
        media = self.dir / "talk.mp4"
        media.write_bytes(b"video")
        m = create_meeting("Видео", "talk.mp4", str(media))
        save_meeting_results(m["id"], speakers={}, segments=[{"id": 0, "start": 0, "end": 2, "speaker": "S1", "text": "Добрый день"}])
        update_meeting_progress(m["id"], status="completed")
        self.mid = m["id"]

    def _exports(self):
        return get_meeting(self.mid).get("exports") or []

    def test_a_cut(self):
        out = self.dir / "mine.mp4"
        with mock.patch("app.media_cut.run_cut", side_effect=RuntimeError("FFmpeg")):
            with self.assertRaises(RuntimeError):
                transcriber._cut_runner(self.mid, "clean", [(0.0, 1.0)], True, str(out))
        self.assertEqual(self._exports(), [])
        with mock.patch("app.media_cut.run_cut", return_value=out):
            transcriber._cut_runner(self.mid, "clean", [(0.0, 1.0)], True, str(out))
        self.assertEqual(self._exports(), [str(out)])

    def test_burned_subtitles(self):
        out = self.dir / "subs.mp4"
        with mock.patch("app.video_subtitles.burn_subtitles", side_effect=RuntimeError("FFmpeg")), \
                mock.patch("app.video_subtitles.probe_media", return_value={"duration": 2.0, "has_video": True}):
            with self.assertRaises(RuntimeError):
                transcriber._burn_runner(self.mid, "ru", "1\n", str(out), True)
        self.assertEqual(self._exports(), [])
        with mock.patch("app.video_subtitles.burn_subtitles", return_value=out), \
                mock.patch("app.video_subtitles.probe_media", return_value={"duration": 2.0, "has_video": True}):
            transcriber._burn_runner(self.mid, "ru", "1\n", str(out), True)
        self.assertEqual(self._exports(), [str(out)])

    def test_a_waiting_export_with_soft_subtitles(self):
        with mock.patch("app.video_subtitles.probe_media", return_value={"duration": 2.0, "has_video": True}), \
                mock.patch("app.video_subtitles.mux_soft_subtitles", side_effect=RuntimeError("FFmpeg")):
            with self.assertRaises(RuntimeError):
                pending_exports._video_subtitles(get_meeting(self.mid), {"kind": "video_soft", "lang": None, "variant": "original"}, self.dir)
        self.assertEqual(self._exports(), [])

    def test_a_refused_burn_is_not_listed(self):
        with mock.patch("app.video_subtitles.probe_media", return_value={"duration": 2.0, "has_video": True}), \
                mock.patch.object(transcriber, "enqueue_burn_subtitles_job", return_value=False):
            with self.assertRaises(RuntimeError):
                pending_exports._video_subtitles(get_meeting(self.mid), {"kind": "video_burn", "lang": None, "variant": "original"}, self.dir)
        self.assertEqual(self._exports(), [])


if __name__ == "__main__":
    unittest.main()
