from __future__ import annotations

import importlib
import json
import math
import os
from pathlib import Path
import struct
import sys

WORKSPACE = Path(__file__).resolve().parent.parent
CONFIG_PATH = WORKSPACE / "recurdyn-config.json"


def config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def install_dir():
    return Path(config()["install_dir"]).resolve()


def output_path(value, *, overwrite=False):
    """Keep all adapter writes inside the workspace and outside the installation."""
    path = Path(value)
    if not path.is_absolute():
        path = WORKSPACE / path
    path = path.resolve()
    if not path.is_relative_to(WORKSPACE) or path.is_relative_to(install_dir()):
        raise ValueError(f"Output must be inside the workspace: {WORKSPACE}")
    if path.suffix.lower() == ".tex":
        raise ValueError("This adapter does not write .tex files.")
    if path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {path}")
    return path


def finite_number(value, *, positive=False):
    number = float(value)
    if not math.isfinite(number) or (positive and number <= 0):
        raise ValueError(f"Expected a finite {'positive ' if positive else ''}number: {value}")
    return number


def simulation_settings(end_time, steps):
    duration = finite_number(end_time, positive=True)
    count = finite_number(steps, positive=True)
    if not count.is_integer() or count > 2_147_483_647:
        raise ValueError("steps must be a positive 32-bit integer")
    return duration, int(count)


def write_json(path, data):
    path = output_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return path


def load_sdk():
    if os.name != "nt" or struct.calcsize("P") != 8:
        raise RuntimeError("RecurDyn 2024 requires 64-bit Windows Python for this adapter.")
    # The SDK remains in the installation. Disable .pyc writes there.
    sys.dont_write_bytecode = True
    sdk_root = install_dir() / "Bin" / "Python" / "Lib"
    if not (sdk_root / "recurdyn" / "ProcessNet.py").is_file():
        raise FileNotFoundError(f"Official Python SDK not found: {sdk_root}")
    try:
        import win32com
    except ImportError as error:
        raise RuntimeError("Missing pywin32; use rd.ps1 or install requirements.txt in your own environment.") from error
    # Configure before importing win32com.client, which initializes gencache.
    cache = WORKSPACE / ".cache" / "win32com"
    cache.mkdir(parents=True, exist_ok=True)
    win32com.__gen_path__ = str(cache)
    import win32com.gen_py
    win32com.gen_py.__path__ = [str(cache)]
    if str(sdk_root) not in sys.path:
        sys.path.insert(0, str(sdk_root))
    sdk = importlib.import_module("recurdyn")
    if not Path(sdk.__file__).resolve().is_relative_to(sdk_root.resolve()):
        raise RuntimeError(f"A different RecurDyn SDK is already imported: {sdk.__file__}")
    return sdk


def diagnostics():
    root = install_dir()
    result = {
        "workspace": str(WORKSPACE),
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "bits": struct.calcsize("P") * 8,
        "install_dir": str(root),
        "executable_exists": (root / "Bin" / "RecurDyn.exe").is_file(),
        "sdk_exists": (root / "Bin" / "Python" / "Lib" / "recurdyn" / "ProcessNet.py").is_file(),
        "chm_extracted_files": sum(1 for _ in (WORKSPACE / ".reference" / "processnet" / "Python").rglob("*.html")),
    }
    try:
        load_sdk()
        import pywintypes
        import pythoncom
        import win32com.client
        result["sdk_import"] = "ok"
        try:
            result["com_clsid"] = str(pywintypes.IID("RecurDyn.RDApplication"))
        except pywintypes.com_error as error:
            result["com_registration_error"] = str(error)
            result["hint"] = "COM may be hidden by Codex sandbox. Run on the Windows host before concluding registration is missing."
        pythoncom.CoInitialize()
        try:
            try:
                obj = win32com.client.GetActiveObject("RecurDyn.RDApplication")
                app = load_sdk().IApplication(load_sdk().IRecurDynApp(obj._oleobj_).RecurDynApplication)
                result["running_instance"] = True
                result["application_version"] = app.Version
                result["connected_install_dir"] = app.GetInstallationPath()
            except pywintypes.com_error as error:
                result["running_instance"] = False
                result["attach_error"] = str(error)
        finally:
            pythoncom.CoUninitialize()
    except Exception as error:
        result["sdk_import_error"] = str(error)
    result["ready"] = bool(result.get("sdk_import") == "ok" and result.get("com_clsid"))
    return result
