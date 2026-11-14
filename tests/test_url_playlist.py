"""A link to a playlist: every video a recording of its own, in a folder named after it; or the first
video only (app/url_import.py)."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import sys
import types
import unittest
from unittest import mock

try:
    from app import url_import
    from app.database import get_folder, get_meeting, init_db
    from app.paths import UPLOADS_DIR
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    url_import = None

VIDEOS = [("https://example.com/v/1", "Первая лекция"), ("https://example.com/v/2", "Вторая лекция"),
          ("https://example.com/v/3", "Третья лекция")]


class FakeYDL:
    downloaded = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=True):
        if self.opts.get("extract_flat") and url.endswith("/playlist"):
            return {"_type": "playlist", "title": "Курс", "entries": [{"url": u, "title": t} for u, t in VIDEOS]}
        if url.endswith("/playlist"):  # downloaded as one link: yt-dlp takes playlist_items
            assert self.opts.get("playlist_items") == "1"
            url = VIDEOS[0][0]
        self.url = url
        return {"title": dict(VIDEOS)[url], "upload_date": "20260115"}

    def process_ie_result(self, info, download=True):
        FakeYDL.downloaded.append(self.url)
        name = self.opts["outtmpl"].replace("\\\\", "/").split("/")[-1].replace("%(title).80B.%(ext)s", "v.m4a")
        path = UPLOADS_DIR / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 100)
        return {**info, "requested_downloads": [{"filepath": str(path)}]}


@unittest.skipIf(url_import is None, "app dependencies not installed")
class PlaylistTest(unittest.TestCase):
    def _start(self, playlist):
        FakeYDL.downloaded = []
        with mock.patch.dict(sys.modules, {"yt_dlp": types.SimpleNamespace(YoutubeDL=FakeYDL)}), \
                mock.patch.object(url_import, "ensure_package"), \
                mock.patch("threading.Thread", side_effect=lambda target, args, **kw: types.SimpleNamespace(start=lambda: target(*args))), \
                mock.patch("app.transcriber.enqueue_meeting_job") as enq:
            m = url_import.start("https://example.com/playlist", "large-v3-turbo", "auto", 0, playlist=playlist)
        return m, enq

    def test_every_video_is_a_recording_in_the_playlist_folder(self):
        init_db()
        m, enq = self._start(True)
        self.assertEqual(FakeYDL.downloaded, [u for u, _ in VIDEOS])
        ids = [c.args[0] for c in enq.call_args_list]
        self.assertEqual(len(ids), 3)
        got = [get_meeting(i) for i in ids]
        self.assertEqual([g["title"] for g in got], [t for _, t in VIDEOS])
        self.assertEqual(len({g["folder_id"] for g in got}), 1)
        self.assertEqual(get_folder(got[0]["folder_id"])["name"], "Курс")
        self.assertEqual(ids[0], m["id"])

    def test_without_the_choice_only_the_first_video(self):
        init_db()
        _m, enq = self._start(False)
        self.assertEqual(FakeYDL.downloaded, [VIDEOS[0][0]])
        self.assertEqual(enq.call_count, 1)

    def test_probe_says_how_long_it_is(self):
        with mock.patch.dict(sys.modules, {"yt_dlp": types.SimpleNamespace(YoutubeDL=FakeYDL)}), \
                mock.patch.object(url_import, "ensure_package"):
            self.assertEqual(url_import.probe("https://example.com/playlist"), {"playlist": True, "title": "Курс", "count": 3})
            self.assertFalse(url_import.probe("https://example.com/v/1")["playlist"])

    def test_deleting_one_video_leaves_the_others(self):
        init_db()
        FakeYDL.downloaded = []
        state = {}
        real_one = url_import._download_one

        def one(mid, url, stop):
            if not state:  # while the first downloads, the user deletes it and the third one
                state["ids"] = sorted(url_import._waiting)
                url_import.drop(mid)
                url_import.drop(state["ids"][-1])
            real_one(mid, url, stop)

        with mock.patch.dict(sys.modules, {"yt_dlp": types.SimpleNamespace(YoutubeDL=FakeYDL)}), \
                mock.patch.object(url_import, "ensure_package"), \
                mock.patch.object(url_import, "_download_one", one), \
                mock.patch("threading.Thread", side_effect=lambda target, args, **kw: types.SimpleNamespace(start=lambda: target(*args))), \
                mock.patch("app.transcriber.enqueue_meeting_job") as enq:
            url_import.start("https://example.com/playlist", "large-v3-turbo", "auto", 0, playlist=True)
        self.assertEqual(FakeYDL.downloaded, [VIDEOS[1][0]])  # the second still came
        self.assertEqual(enq.call_count, 1)
        self.assertEqual(url_import._cancel, {})


if __name__ == "__main__":
    unittest.main()
