# Tests never touch the real user data folder: everything goes to a throw-away directory.
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="verbaliox-tests-")
os.environ["VERBALIOX_DATA_DIR"] = os.path.join(_TMP, "data")  # even when the shell points to real data
os.environ["VERBALIOX_MODELS_DIR"] = os.path.join(_TMP, "models")
os.environ["VERBALIOX_SKIP_MIGRATION"] = "1"
os.environ["VERBALIOX_NO_FFMPEG_AUTO"] = "1"  # the app start would download FFmpeg into the test data (Windows)
# Nothing is downloaded from Hugging Face: a test that reaches the background download of a model's files
# (app/asr_onnx._complete_async with is_installed faked) fails offline instead of fetching gigabytes
os.environ["HF_HUB_OFFLINE"] = "1"

# PyTorch (CUDA wheels, gigabytes) is not installed for the tests: a small stand-in reports "no GPU"
try:
    import torch  # noqa: F401
except ImportError:
    import sys

    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "stubs"))

# The background unload of idle models never runs in the tests: a job a test finishes would start its minute
# (app/idle_unload.work_done), and its unload would reach the Ollama of the computer the tests run on
try:
    from app import idle_unload as _idle_unload

    _idle_unload._started = True
except ImportError:  # the release CI runs without the app's packages
    pass
