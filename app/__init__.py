# Verbaliox package
__version__ = "0.9.5"

# The GPU build of ONNX Runtime (GigaAM / Parakeet on the video card) goes first on sys.path,
# before anything imports onnxruntime (app/onnx_gpu.py)
from app import onnx_gpu as _onnx_gpu  # noqa: E402

_onnx_gpu.activate()

# Requests to 127.0.0.1 (Ollama) never go to the proxy of the Windows settings (app/net_proxy.py)
from app import net_proxy as _net_proxy  # noqa: E402

_net_proxy.install()
