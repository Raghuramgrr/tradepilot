# tradepilot/config.py
import yaml
from pathlib import Path

_cfg = None

def load(path: str = None) -> dict:
    global _cfg
    if _cfg is not None:
        return _cfg
    cfg_path = path or Path(__file__).parent / "config.yaml"
    with open(cfg_path) as f:
        _cfg = yaml.safe_load(f)
    return _cfg

def get(path: str, default=None):
    """Dot-notation access: get('risk.kelly_fraction')"""
    cfg = load()
    keys = path.split(".")
    val = cfg
    for k in keys:
        if not isinstance(val, dict):
            return default
        val = val.get(k, default)
    return val