"""Load provider/wiro.py the way the plugin runtime does: by file path."""

import importlib.util

from conftest import PLUGIN_ROOT


def load_provider_class():
    spec = importlib.util.spec_from_file_location("wiro_provider", PLUGIN_ROOT / "provider" / "wiro.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.WiroModelProvider


def new_provider():
    """The runtime builds providers with schemas; credential checks do not need them."""
    cls = load_provider_class()
    return cls.__new__(cls)
