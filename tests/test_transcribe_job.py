import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from app import transcriber
    from app.database import create_meeting, get_meeting, init_db, save_meeting_results, update_settings
except ImportError:  # app dependencies are not installed (e.g. in the release CI job)
    transcriber = None

OLD = [{"id": 0, "start": 0.0, "end": 1.0, "speaker": "SPEAKER_00", "text": "прежняя правка"}]
NEW = [{"start": 0.0, "end": 2.0, "text": "новый текст", "words": []}]


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class ProcessMeetingJobTest(unittest.TestCase):
    """The recognition job end to end with GigaAM on ONNX, the model and FFmpeg replaced by stand-ins."""

    def setUp(self):
        init_db()
        update_settings({"auto_summary": "false", "clean_fillers": "false"})
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        media = Path(self.tmp.name) / "meeting.wav"
        media.write_bytes(b"RIFF")
        m = create_meeting(title="Задание", filename="meeting.wav", media_path=str(media))
        self.mid = m["id"]
        from app.database import update_meeting_fields

        update_meeting_fields(self.mid, model_name="gigaam-v3", language="ru")
        save_meeting_results(self.mid, segments=OLD, speakers={"SPEAKER_00": {"name": "Анна", "color": "#0A84FF"}})

        from app import asr_onnx, onnx_gpu, semantic

        def diarize(wav_path, raw_segments, **kw):
            return ({"SPEAKER_00": {"name": "Участник 1", "color": "#0A84FF"}},
                    [{**s, "id": i, "speaker": "SPEAKER_00"} for i, s in enumerate(raw_segments)])

        patches = [
            mock.patch.object(transcriber, "get_hardware_info",
                              return_value={"recommended_device": "cpu", "recommended_compute_type": "int8"}),
            mock.patch.object(transcriber, "extract_audio_16k_mono", side_effect=lambda src, dst, **kw: Path(dst).write_bytes(b"x")),
            mock.patch.object(transcriber, "get_media_duration", return_value=2.0),
            mock.patch.object(transcriber, "_after_transcription", return_value=[]),
            mock.patch.object(asr_onnx, "supports_language", return_value=True),
            mock.patch.object(asr_onnx, "is_installed", return_value=True),
            mock.patch.object(semantic, "kick"),
            mock.patch("app.diarizer.diarize_and_merge_segments", side_effect=diarize),
            mock.patch("app.voice_profiles.apply_to_speakers", return_value=0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.release = mock.patch.object(asr_onnx, "release").start()
        self.addCleanup(mock.patch.stopall)
        self.gpu = mock.patch.object(onnx_gpu, "gpu_for_job", return_value=False).start()
        self.asr = asr_onnx

    def _run(self, transcribe):
        with mock.patch.object(self.asr, "transcribe", side_effect=transcribe):
            transcriber._process_meeting_job(self.mid)
        return get_meeting(self.mid)

    def test_gpu_failure_is_done_again_on_the_cpu(self):
        self.gpu.return_value = True
        calls = []

        def transcribe(model, wav, dur, progress, cancel, out, gpu=False, leveling=True):
            calls.append(gpu)
            if gpu:
                raise RuntimeError("CUDA out of memory")
            return NEW

        m = self._run(transcribe)
        self.assertEqual(calls, [True, False])
        self.release.assert_any_call("gigaam-v3", gpu=True)
        self.assertEqual(m["status"], "completed")
        self.assertEqual([s["text"] for s in m["segments"]], ["новый текст"])

    def test_cancel_keeps_the_previous_transcript(self):
        def transcribe(model, wav, dur, progress, cancel, out, gpu=False, leveling=True):
            out.append(NEW[0])
            progress(0.5)  # a partial save would replace the old transcript: not for a recording that has one
            raise transcriber.JobCancelled()

        m = self._run(transcribe)
        self.assertEqual(m["status"], "cancelled")
        self.assertEqual([s["text"] for s in m["segments"]], ["прежняя правка"])

    def test_a_first_transcription_cancelled_half_way_keeps_what_it_recognized(self):
        from app.database import save_meeting_results

        save_meeting_results(self.mid, segments=[], speakers={})  # nothing recognized before

        def transcribe(model, wav, dur, progress, cancel, out, gpu=False, leveling=True):
            out.append(NEW[0])
            with mock.patch.object(transcriber, "PARTIAL_EVERY_SEC", 0):
                progress(0.5)
            raise transcriber.JobCancelled()

        m = self._run(transcribe)
        self.assertEqual(m["status"], "cancelled")
        self.assertTrue(m["segments"])
        self.assertIn("часть, распознанная до отмены", m["stage_text"])

    def test_failure_keeps_the_previous_transcript_and_says_why(self):
        def transcribe(model, wav, dur, progress, cancel, out, gpu=False, leveling=True):
            raise RuntimeError("model file damaged")

        m = self._run(transcribe)
        self.assertEqual(m["status"], "failed")
        self.assertIn("model file damaged", m["error_message"])
        self.assertEqual([s["text"] for s in m["segments"]], ["прежняя правка"])

    def test_a_model_not_downloaded_is_downloaded_first(self):
        stages = []
        real_update = transcriber.update_meeting_progress

        def update(mid, **kw):
            if kw.get("stage_text"):
                stages.append(kw["stage_text"])
            return real_update(mid, **kw)

        def download(model, on_progress):
            on_progress(40)

        with mock.patch.object(self.asr, "is_installed", return_value=False), \
                mock.patch.object(self.asr, "ensure_downloaded", side_effect=download) as dl, \
                mock.patch.object(transcriber, "update_meeting_progress", side_effect=update):
            m = self._run(lambda *a, **k: NEW)
        dl.assert_called_once()
        self.assertIn("Скачивание модели GigaAM v3: 40%", stages)
        self.assertEqual(m["status"], "completed")

    def test_a_failed_model_download_says_so(self):
        with mock.patch.object(self.asr, "is_installed", return_value=False), \
                mock.patch.object(self.asr, "ensure_downloaded", side_effect=OSError("no network")):
            m = self._run(lambda *a, **k: self.fail("recognition must not start"))
        self.assertEqual(m["status"], "failed")
        self.assertIn("Не удалось скачать модель GigaAM v3: no network", m["error_message"])

    def test_the_recordings_own_processing_is_used(self):
        from app.database import effective_processing, set_meeting_processing

        set_meeting_processing(self.mid, {"denoise": False, "leveling": False, "diarization": False, "bogus": True})
        self.assertEqual(get_meeting(self.mid)["processing"],
                         {**effective_processing({}), "denoise": False, "leveling": False, "diarization": False})
        seen = {}

        def transcribe(model, wav, dur, progress, cancel, out, gpu=False, leveling=True):
            seen["leveling"] = leveling
            return NEW

        with mock.patch.object(transcriber, "extract_audio_16k_mono",
                               side_effect=lambda src, dst, **kw: (seen.update(kw), Path(dst).write_bytes(b"x"))), \
                mock.patch("app.diarizer.diarize_and_merge_segments",
                           side_effect=lambda **kw: (seen.update(diar=kw["diarization_enabled"]),
                                                     ({"SPEAKER_00": {"name": "Участник 1", "color": "#0A84FF"}},
                                                      [{**s, "id": i, "speaker": "SPEAKER_00"} for i, s in enumerate(kw["raw_segments"])]))[1]):
            m = self._run(transcribe)
        self.assertEqual(m["status"], "completed")
        self.assertEqual((seen["denoise"], seen["loudnorm"], seen["leveling"], seen["diar"]), (False, True, False, False))

    def test_missing_media_fails_at_once(self):
        Path(get_meeting(self.mid)["media_path"]).unlink()
        m = self._run(lambda *a, **k: self.fail("recognition must not start"))
        self.assertEqual(m["status"], "failed")
        self.assertIn("не найден", m["stage_text"])


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class AutoModelJobTest(unittest.TestCase):
    """model "auto": the language of the first minute picks the Russian model or the main one."""

    _run = ProcessMeetingJobTest._run  # the same stand-ins, without repeating its tests

    def setUp(self):
        ProcessMeetingJobTest.setUp(self)
        from app.database import update_meeting_fields

        update_settings({"whisper_model": "parakeet-v3", "speech_model_ru": "gigaam-v3"})
        update_meeting_fields(self.mid, model_name="auto", language="auto")

    def _models_used(self, heard):
        used = []

        def transcribe(model, wav, dur, progress, cancel, out, gpu=False, leveling=True):
            used.append(model)
            return NEW

        with mock.patch.object(transcriber, "_detect_speech_language", return_value=heard) as detect:
            m = self._run(transcribe)
        detect.assert_called_once()
        return used, m

    def test_russian_speech_goes_to_the_russian_model(self):
        used, m = self._models_used("ru")
        self.assertEqual(used, ["gigaam-v3"])
        self.assertEqual(m["status"], "completed")

    def test_other_speech_goes_to_the_main_model(self):
        used, m = self._models_used("other")
        self.assertEqual(used, ["parakeet-v3"])
        self.assertEqual(m["status"], "completed")

    def test_undecided_speech_goes_to_the_main_model(self):
        used, _m = self._models_used(None)
        self.assertEqual(used, ["parakeet-v3"])


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class DetectSpeechLanguageTest(unittest.TestCase):
    """_detect_speech_language: the letters GigaAM / Parakeet write, or Whisper's guess and its probability."""

    def setUp(self):
        import numpy as np
        import soundfile as sf

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.wav = Path(self.tmp.name) / "a.wav"
        sf.write(str(self.wav), np.zeros(16000, dtype="float32"), 16000)

    def test_onnx_model_reads_the_letters(self):
        from app import asr_onnx, onnx_gpu

        text = [{"text": "Давайте начнём с того, что успели сделать за эту неделю"}]
        with mock.patch.object(asr_onnx, "is_installed", return_value=True), \
                mock.patch.object(onnx_gpu, "gpu_for_job", return_value=False), \
                mock.patch.object(asr_onnx, "transcribe", return_value=text):
            self.assertEqual(transcriber._detect_speech_language(self.wav, "parakeet-v3", "cpu", "int8"), "ru")
        self.assertFalse(list(Path(self.tmp.name).glob("*.lang.wav")))  # the clip is removed

    def test_whisper_needs_a_confident_guess(self):
        from types import SimpleNamespace

        model = mock.Mock()
        with mock.patch("app.model_manager.is_whisper_model_installed", return_value=True), \
                mock.patch.object(transcriber, "_get_whisper_model", return_value=(model, None)):
            model.transcribe.return_value = ([], SimpleNamespace(language="ru", language_probability=0.95))
            self.assertEqual(transcriber._detect_speech_language(self.wav, "large-v3-turbo", "cpu", "int8"), "ru")
            model.transcribe.return_value = ([], SimpleNamespace(language="en", language_probability=0.9))
            self.assertEqual(transcriber._detect_speech_language(self.wav, "large-v3-turbo", "cpu", "int8"), "other")
            model.transcribe.return_value = ([], SimpleNamespace(language="ru", language_probability=0.2))
            self.assertIsNone(transcriber._detect_speech_language(self.wav, "large-v3-turbo", "cpu", "int8"))

    def test_a_model_not_downloaded_is_not_fetched_for_this(self):
        from app import asr_onnx

        with mock.patch.object(asr_onnx, "is_installed", return_value=False), \
                mock.patch.object(asr_onnx, "transcribe") as tr:
            self.assertIsNone(transcriber._detect_speech_language(self.wav, "gigaam-v3", "cpu", "int8"))
        tr.assert_not_called()


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class LanguageChoiceTest(unittest.TestCase):
    """The language chosen for a recording stays for the next run; the one heard is stored apart."""

    _run = ProcessMeetingJobTest._run

    def setUp(self):
        ProcessMeetingJobTest.setUp(self)
        from app.database import update_meeting_fields

        update_meeting_fields(self.mid, model_name="parakeet-v3", language="mixed")

    def test_several_languages_stay_chosen(self):
        mixed = [{"start": 0.0, "end": 1.0, "text": "Давайте начнём встречу", "words": []},
                 {"start": 1.0, "end": 2.0, "text": "and then we talk about the plan for this week", "words": []}]
        for _ in range(2):
            m = self._run(lambda *a, **k: [dict(s) for s in mixed])
            self.assertEqual(m["status"], "completed")
            self.assertEqual(m["language_choice"], "mixed")
            self.assertEqual([s.get("lang") for s in m["segments"]], ["ru", "en"])  # per phrase, every run

    def test_a_german_transcript_is_not_taken_for_english(self):
        from app.database import update_meeting_fields

        update_meeting_fields(self.mid, language="auto", language_choice="")
        german = [{"start": 0.0, "end": 2.0, "text": "Wir haben heute nicht viel Zeit und die Aufgabe ist eine andere", "words": []}]
        m = self._run(lambda *a, **k: german)
        self.assertEqual((m["language"], m["language_choice"]), ("de", "auto"))


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class AutoChaptersTest(unittest.TestCase):
    """The topics above the timeline are made with the overview for a meeting of 10 minutes or more."""

    _run = ProcessMeetingJobTest._run

    def setUp(self):
        ProcessMeetingJobTest.setUp(self)
        update_settings({"auto_summary": "true", "auto_commitments": "false", "summary_grounding": "false"})
        self.addCleanup(update_settings, {"auto_summary": "false", "auto_commitments": "true", "summary_grounding": "true"})
        from app import llm

        for p in (mock.patch.object(llm, "available", return_value=True),
                  mock.patch.object(llm, "uses_cloud", return_value=False)):
            p.start()
            self.addCleanup(p.stop)

    def _templates(self, end):
        made = []

        def summary(**kw):
            made.append(kw["template_key"])
            return "- [00:00] Начало — вступление\n- [05:00] Итоги — решения" if kw["template_key"] == "chapters" else "## Итоги"

        segs = [{"start": 0.0, "end": end, "text": "длинный разговор", "words": []}]
        with mock.patch.object(transcriber, "generate_meeting_summary", side_effect=summary):
            m = self._run(lambda *a, **k: segs)
        return made, m

    def test_long_meeting_gets_chapters(self):
        made, m = self._templates(900.0)
        self.assertEqual(made, ["protocol", "chapters"])
        self.assertIn("[05:00] Итоги", m["summaries"]["chapters"])

    def test_short_one_does_not(self):
        made, _m = self._templates(120.0)
        self.assertEqual(made, ["protocol"])


def _words(text, start=0.0):
    out, t = [], start
    for w in text.split():
        out.append({"word": " " + w, "start": t, "end": t + 0.4, "prob": 0.9})
        t += 0.5
    return out


@unittest.skipIf(transcriber is None, "app dependencies not installed")
class EnsembleJobTest(unittest.TestCase):
    """The precise mode: another model recognizes the recording too and the versions are merged."""

    _run = ProcessMeetingJobTest._run

    def setUp(self):
        ProcessMeetingJobTest.setUp(self)
        update_settings({"asr_ensemble": "true", "asr_ensemble_models": "parakeet-v3"})
        self.addCleanup(update_settings, {"asr_ensemble": "false", "asr_ensemble_models": ""})
        from app import llm

        self.asked = []

        def chat(system, user):
            self.asked.append(user)
            return '{"choices": [2]}'

        target = mock.Mock(chat=chat)
        p = mock.patch.object(llm, "target", return_value=target)
        p.start()
        self.addCleanup(p.stop)

    def _transcribe(self, model, wav, dur, progress, cancel, out=None, gpu=False, leveling=True):
        text = "попроси клода сделать обзор" if model == "gigaam-v3" else "попроси Claude сделать обзор"
        return [{"start": 0.0, "end": 2.0, "text": text, "words": _words(text)}]

    def test_versions_are_kept_and_merged(self):
        from app.database import all_transcripts

        m = self._run(self._transcribe)
        self.assertEqual(m["status"], "completed")
        self.assertEqual(m["transcript_model"], "merged")
        self.assertEqual(m["segments"][0]["text"], "попроси Claude сделать обзор")  # the analysis model's pick
        disputed = [w for w in m["segments"][0]["words"] if w.get("alts")]
        self.assertEqual([w.get("by") for w in disputed], ["llm"])  # the hint says who picked it
        self.assertEqual(m["segments"][0]["speaker"], "SPEAKER_00")  # the speakers of the main model's version
        self.assertTrue({"gigaam-v3", "parakeet-v3", "merged"} <= set(all_transcripts(self.mid)))
        self.assertEqual(sorted(m["merged_models"]), ["gigaam-v3", "parakeet-v3"])  # the chips light these
        from app.database import switch_transcript_version

        switch_transcript_version(self.mid, "gigaam-v3")
        self.assertEqual(get_meeting(self.mid)["merged_models"], [])
        switch_transcript_version(self.mid, "merged")  # back: the list came with the version
        self.assertEqual(sorted(get_meeting(self.mid)["merged_models"]), ["gigaam-v3", "parakeet-v3"])
        self.assertEqual(len(self.asked), 1)
        self.release.assert_any_call()  # the models went out of memory before the next one (all of them)
        self.assertIn("клода", self.asked[0])
        self.assertNotIn("обзор сделать", self.asked[0])  # only the disputed place and the words around it

    def test_a_model_that_already_transcribed_it_is_not_run_again(self):
        from app.database import save_transcript_version

        text = "попроси Claude сделать обзор"
        save_transcript_version(self.mid, "parakeet-v3", {"segments": [
            {"id": 0, "start": 0.0, "end": 2.0, "speaker": "SPEAKER_05", "text": text, "words": _words(text)}],
            "speakers": {}, "language": "ru", "at": "2026-11-01 10:00:00"})
        ran = []

        def transcribe(model, *a, **k):
            ran.append(model)
            return self._transcribe(model, *a, **k)

        m = self._run(transcribe)
        self.assertEqual(m["transcript_model"], "merged")
        self.assertNotIn("parakeet-v3", ran)  # its version was used as it was
        self.assertEqual(m["segments"][0]["text"], text)

    def test_the_text_of_the_main_model_is_taken_as_it_is(self):
        """«Все модели» on a recording GigaAM transcribed and the user corrected: GigaAM is not run again
        and the corrections are what goes into the merge."""
        from app.database import all_transcripts

        text = "попроси Claude сделать обзор"
        save_meeting_results(self.mid, segments=[{"id": 0, "start": 0.0, "end": 2.0, "speaker": "SPEAKER_00",
                                                  "text": text, "words": _words(text)}],
                             speakers={"SPEAKER_00": {"name": "Анна", "color": "#0A84FF"}}, transcript_model="gigaam-v3")
        ran = []

        def transcribe(model, *a, **k):
            ran.append(model)
            return self._transcribe(model, *a, **k)

        m = self._run(transcribe)
        self.assertEqual(ran, ["parakeet-v3"])
        self.assertEqual(m["transcript_model"], "merged")
        self.assertEqual(all_transcripts(self.mid)["gigaam-v3"]["segments"][0]["text"], text)  # the corrected text kept

    def test_the_main_text_is_made_again_when_its_settings_changed(self):
        """GigaAM's text exists, but the number of people was changed since: it is recognized again."""
        from app.database import update_meeting_fields

        text = "попроси Claude сделать обзор"
        save_meeting_results(self.mid, segments=[{"id": 0, "start": 0.0, "end": 2.0, "speaker": "SPEAKER_00",
                                                  "text": text, "words": _words(text)}],
                             speakers={"SPEAKER_00": {"name": "Анна"}}, transcript_model="gigaam-v3")
        update_meeting_fields(self.mid, transcript_made_with='{"speakers": 5}', num_speakers_hint=2)
        ran = []

        def transcribe(model, *a, **k):
            ran.append(model)
            return self._transcribe(model, *a, **k)

        self._run(transcribe)
        self.assertIn("gigaam-v3", ran)

    def test_a_cancel_in_the_other_models_keeps_the_finished_transcript(self):
        def transcribe(model, *a, **k):
            if model == "parakeet-v3":
                raise transcriber.JobCancelled()
            return self._transcribe(model, *a, **k)

        m = self._run(transcribe)
        self.assertEqual(m["status"], "completed")
        self.assertEqual(m["transcript_model"], "gigaam-v3")
        self.assertIn("точный режим отменён", m["stage_text"])

    def test_a_version_made_another_way_is_made_again(self):
        from app.database import save_transcript_version

        old = "совсем другой язык"
        save_transcript_version(self.mid, "parakeet-v3", {
            "segments": [{"id": 0, "start": 0.0, "end": 2.0, "speaker": "SPEAKER_00", "text": old, "words": _words(old)}],
            "speakers": {}, "language": "en", "made_with": {"language": "en", "denoise": True, "loudnorm": True, "vad": True},
            "at": "2026-11-01 10:00:00"})
        ran = []

        def transcribe(model, *a, **k):
            ran.append(model)
            return self._transcribe(model, *a, **k)

        self._run(transcribe)
        self.assertIn("parakeet-v3", ran)  # recognized again: the old version was made for English

    def test_the_live_captions_keep_their_copy_of_the_model(self):
        """A recording with GigaAM captions goes on while this job runs: only the video card's copies go."""
        from app import live

        gpu_release = mock.patch.object(self.asr, "release_gpu").start()
        with mock.patch.object(live, "has_sessions", return_value=True):
            self._run(self._transcribe)
        self.assertNotIn(mock.call(), self.release.call_args_list)  # not every copy
        self.assertNotIn(mock.call("parakeet-v3"), self.release.call_args_list)
        gpu_release.assert_called()

    def test_without_another_model_the_main_one_stays(self):
        from app import asr_onnx

        with mock.patch.object(asr_onnx, "is_installed", side_effect=lambda m: m == "gigaam-v3"):
            m = self._run(self._transcribe)
        self.assertEqual(m["status"], "completed")
        self.assertEqual(m["transcript_model"], "gigaam-v3")
        self.assertIn("нет других установленных моделей", m["stage_text"])

    def test_whisper_pro_is_always_among_the_models(self):
        from app import asr_onnx

        installed = {"gigaam-v3", "parakeet-v3", "large-v3", "large-v3-turbo"}
        settings = {"asr_ensemble_models": ""}
        with mock.patch.object(asr_onnx, "is_installed", side_effect=lambda m: m in installed), \
                mock.patch("app.model_manager.is_whisper_model_installed", side_effect=lambda m: m in installed):
            got = transcriber.ensemble_models(settings, "parakeet-v3", "ru", False)
            self.assertEqual(got[0], "large-v3")
            self.assertEqual(len(got), transcriber.ENSEMBLE_MAX_MODELS - 1)
            # English: GigaAM does not know it, Whisper Pro still leads
            self.assertEqual(transcriber.ensemble_models(settings, "gigaam-v3", "en", False)[0], "large-v3")
            installed.discard("large-v3")
            self.assertNotIn("large-v3", transcriber.ensemble_models(settings, "parakeet-v3", "ru", False))

    def test_off_for_this_recording(self):
        from app.database import set_meeting_processing

        set_meeting_processing(self.mid, {"ensemble": False})
        m = self._run(self._transcribe)
        self.assertEqual(m["transcript_model"], "gigaam-v3")
        self.assertEqual(self.asked, [])


class WhisperFallbackTest(unittest.TestCase):
    def test_a_processor_fallback_is_known_as_one(self):
        if transcriber is None:
            self.skipTest("app dependencies not installed")
        calls = []

        class FakeWhisper:
            def __init__(self, path, device, compute_type, download_root):
                calls.append((device, compute_type))
                if device == "cuda":
                    raise RuntimeError("cudnn missing")

        fake = mock.Mock(WhisperModel=FakeWhisper)
        with mock.patch.dict("sys.modules", {"faster_whisper": fake}), \
                mock.patch.object(transcriber, "register_cuda_dlls"), \
                mock.patch("app.model_manager.get_whisper_model_path", return_value="x"):
            transcriber.release_whisper_model()
            transcriber._get_whisper_model("large-v3-turbo", "cuda", "float16")
            try:
                self.assertEqual(transcriber.whisper_cache_key(), ("large-v3-turbo", "cpu", "int8"))
                self.assertEqual(transcriber._whisper_device("cuda"), "cpu")  # no GPU batches on the processor
            finally:
                transcriber.release_whisper_model()
