"""The file dialog's child process (app/native_dialog.py): what the server passes reaches it as it was given."""
import tests  # noqa: F401 - keeps the real user data out of reach (see tests/__init__.py)
import unittest
from unittest import mock

from app import native_dialog


class NativeDialogArgsTest(unittest.TestCase):
    def test_a_value_that_begins_with_a_dash(self):
        """Found in the audit: a recording named «-итоги» was read as an option, the child ended with code 2 and
        «Сохранить как» did not open."""
        argv = native_dialog._argv(["--mode", "save", "--dir", "C:/Docs", "--filename", "-итоги встречи.docx",
                                    "--filter", "Word (*.docx)|*.docx", "--ext", ".docx", "--title", "Сохранить как"])
        args = native_dialog._parser().parse_args(argv)
        self.assertEqual((args.mode, args.filename, args.ext, args.dir), ("save", "-итоги встречи.docx", ".docx", "C:/Docs"))
        self.assertEqual(native_dialog._parser().parse_args(native_dialog._argv(["--mode", "folder", "--title", "--"])).title, "--")

    def test_run_passes_them_so(self):
        with mock.patch("subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout="C:/out.docx", stderr="")
            self.assertEqual(native_dialog.run(["--mode", "save", "--filename", "-a"]), "C:/out.docx")
        self.assertEqual(run.call_args[0][0][-2:], ["--mode=save", "--filename=-a"])


if __name__ == "__main__":
    unittest.main()
