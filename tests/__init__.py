# Tests never touch the real user data folder: everything goes to a throw-away directory.
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="verbaliox-tests-")
os.environ["VERBALIOX_DATA_DIR"] = os.path.join(_TMP, "data")  # even when the shell points to real data
os.environ["VERBALIOX_MODELS_DIR"] = os.path.join(_TMP, "models")
os.environ["VERBALIOX_SKIP_MIGRATION"] = "1"
os.environ["VERBALIOX_NO_FFMPEG_AUTO"] = "1"  # the app start would download FFmpeg into the test data (Windows)

# The Ollama of the computer the tests run on is never read nor changed: its models folder is an empty
# folder of the tests (app/ollama_client.models_on_disk), and its port is refused below
os.environ["OLLAMA_MODELS"] = os.path.join(_TMP, "ollama")

# No network in the tests: a connection to Ollama's port, or to any address outside this computer, is refused
# (VERBALIOX_TESTS_NET=1 allows the outside for a manual check). Servers a test starts itself on this
# computer are reachable. A proxy of the environment would carry the outside through a loopback address,
# so it is not used either.
import socket as _socket

OLLAMA_PORT = 11434
_NET = os.environ.get("VERBALIOX_TESTS_NET") == "1"
_LOOPBACK = {"127.0.0.1", "localhost", "::1", "0.0.0.0", "", "::"}
refused: list = []  # (host, port) of every connection refused: a test can check, the audit can print

if not _NET:
    for _k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(_k, None)


def _allowed(address) -> bool:
    if not isinstance(address, tuple) or len(address) < 2:
        return True  # a Unix socket or a socket pair: not the network
    host, port = str(address[0]).lower(), address[1]
    loopback = host in _LOOPBACK or host.startswith("127.") or host == "::ffff:127.0.0.1"
    if loopback:
        return port != OLLAMA_PORT
    return _NET


def _refuse(address):
    refused.append(tuple(address[:2]))
    log = os.environ.get("VERBALIOX_TESTS_NET_LOG")
    if log:
        import traceback

        with open(log, "a", encoding="utf-8") as f:
            f.write(f"REFUSED {address[:2]}\n{''.join(traceback.format_stack(limit=14)[:-2])}\n")
    raise ConnectionRefusedError(f"tests do not reach the network: {address[:2]}")


_connect = _socket.socket.connect
_connect_ex = _socket.socket.connect_ex


def _guarded_connect(self, address):
    if not _allowed(address):
        _refuse(address)
    return _connect(self, address)


def _guarded_connect_ex(self, address):
    if not _allowed(address):
        _refuse(address)
    return _connect_ex(self, address)


_socket.socket.connect = _guarded_connect
_socket.socket.connect_ex = _guarded_connect_ex
# socket.create_connection (httpx, urllib) connects through socket.socket.connect: covered as well

# No `ollama serve` of the computer is started (app/ollama_client.ensure_ollama_running, once the port is refused)
import subprocess as _subprocess

_Popen_init = _subprocess.Popen.__init__


def _guarded_popen(self, args, *a, **kw):
    argv = [args] if isinstance(args, (str, bytes, os.PathLike)) else list(args or [])
    exe = os.path.basename(str(argv[0])).lower() if argv else ""
    if exe in ("ollama", "ollama.exe"):
        raise FileNotFoundError("tests do not start Ollama")
    return _Popen_init(self, args, *a, **kw)


_subprocess.Popen.__init__ = _guarded_popen

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
