"""One source-hash-pinned import compatibility fix; never edits upstream files."""
import hashlib
import importlib.util
from pathlib import Path
import sys

# Pin follows source 925ede7. That source now imports Path itself, so the
# module.Path shim below is harmless and kept only to keep the load path unchanged.
ONBOARDING_SHA256 = '30eeeb07ada27c311e4d711bdc1e2626a222649954d64cd7aa670e98927ed815'


def load_pinned_onboarding(upstream):
    """The pinned module evaluates tuple[Path,...] before bind_module supplies Path.

    Supply just that missing standard-library name before executing the original
    module, then let upstream's normal HandlerRegistry install/bind it unchanged.
    Fail on different bytes instead of patching a newer source opportunistically.
    """
    name = 'tui_gateway.methods_onboarding'
    if name in sys.modules:
        return
    path = Path(upstream) / 'tui_gateway/methods_onboarding.py'
    if hashlib.sha256(path.read_bytes()).hexdigest() != ONBOARDING_SHA256:
        raise RuntimeError('onboarding compatibility shim source hash mismatch')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    module.Path = Path
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
