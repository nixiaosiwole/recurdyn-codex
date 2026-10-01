"""Read installed API signatures and the extracted CHM without importing COM."""
import ast
from functools import lru_cache
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from .runtime import WORKSPACE, config, install_dir, output_path, write_json


def documentation_paths():
    configured = config().get("documentation", {})
    defaults = {"recurdyn_help_index": install_dir() / "Help/RecurDynHelp/index.html",
                "processnet_chm": install_dir() / "Help/ProcessNetHelp.chm",
                "examples_root": install_dir() / "Help",
                "processnet_html_dir": WORKSPACE / ".reference/processnet"}
    paths = {}
    for key, default in defaults.items():
        value = Path(configured.get(key) or default)
        paths[key] = (WORKSPACE / value).resolve() if not value.is_absolute() else value.resolve()
    paths["sdk_source"] = install_dir() / "Bin/Python/Lib/recurdyn/ProcessNet.py"
    paths["python_api_root"] = install_dir() / "Bin/Python"
    paths["sdk_package_dir"] = install_dir() / "Bin/Python/Lib/recurdyn"
    paths["python_template"] = install_dir() / "Bin/Python/ProcessNetTemplate.py"
    return paths


def documentation_status():
    paths = documentation_paths()
    return {"paths": {key: {"path": str(path), "exists": path.exists()} for key, path in paths.items()},
            "processnet_html_ready": (paths["processnet_html_dir"] / "Python").is_dir(), "sdk_modules": sdk_modules(),
            "next_step": "Use docs-extract if ProcessNet CHM exists but Python HTML is not available; SDK api/api-search remain available without extraction."}


def _root(source):
    paths = documentation_paths()
    return {"processnet": paths["processnet_html_dir"], "usage": paths["recurdyn_help_index"].parent,
            "examples": paths["examples_root"], "python": paths["python_api_root"]}[source]


class _HTMLReader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.codes = []
        self.code = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        elif not self.skip:
            if tag == "pre":
                self.code = []
            if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "pre", "dt", "dd", "tr"}:
                self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        elif not self.skip:
            if tag == "pre" and self.code is not None:
                self.codes.append("".join(self.code).strip("\n"))
                self.code = None
            if tag in {"p", "div", "li", "h1", "h2", "h3", "pre", "dt", "dd", "tr"}:
                self.text.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.text.append(data)
            if self.code is not None:
                self.code.append(data)


def html_document(path):
    source = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    title = re.search(r"<title[^>]*>(.*?)</title>", source, re.I | re.S)
    main = re.search(r'<(?:div|main|section)\b[^>]*\brole=["\']main["\'][^>]*>', source, re.I)
    if main:
        source = source[main.end():]
        source = re.split(r"<footer\b", source, maxsplit=1, flags=re.I)[0]
    reader = _HTMLReader()
    reader.feed(source)
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in "".join(reader.text).splitlines() if line.strip())
    return {"title": html.unescape(title[1]) if title else Path(path).stem, "text": text, "code_blocks": reader.codes}


def read_document(relative_path, source="processnet", *, max_chars=12000, offset=0):
    if not 100 <= max_chars <= 50000 or offset < 0:
        raise ValueError("max_chars must be 100..50000; offset must be nonnegative")
    root = _root(source).resolve()
    path = (root / relative_path).resolve()
    if not path.is_relative_to(root):
        raise ValueError("Document path must remain inside the configured documentation root")
    if not path.is_file():
        raise FileNotFoundError(f"Document missing: {path}; check docs-paths and run docs-extract for ProcessNet CHM")
    if path.suffix.lower() in {".html", ".htm"}:
        result = html_document(path)
    elif path.suffix.lower() in {".py", ".cs", ".txt", ".md"}:
        result = {"title": path.name, "text": path.read_text(encoding="utf-8-sig", errors="replace"), "code_blocks": []}
    else:
        raise ValueError(f"Use a format-specific reader for {path.suffix}; resolved path: {path}")
    full_text = result["text"]
    result.update(source=str(path), documentation_source=source, offset=offset, total_chars=len(full_text),
                  text=full_text[offset:offset + max_chars], truncated=offset + max_chars < len(full_text),
                  code_blocks_truncated=len(result["code_blocks"]) > 6 or any(len(code) > max_chars for code in result["code_blocks"]),
                  code_blocks=[code[:max_chars] for code in result["code_blocks"][:6]])
    return result


def api_search(term, *, limit=15, module=None):
    if not term.strip() or not 1 <= limit <= 100:
        raise ValueError("Supply a search term and limit 1..100")
    hits = []
    terms = term.lower().split()
    for module_name in ([module] if module else sdk_modules()):
        # Most specific API names occur in one module. Avoid parsing every wrapper.
        source = _sdk_file(module_name).read_text(encoding="mbcs").lower()
        if not all(word in source for word in terms):
            continue
        sdk_file, tree = _api_tree(module_name)
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef):
                continue
            for item in cls.body:
                names = []
                if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
                    names.append(item.name)
                elif isinstance(item, ast.Assign) and isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Name) and item.value.func.id == "property":
                    names.extend(target.id for target in item.targets if isinstance(target, ast.Name))
                elif any(isinstance(base, ast.Name) and base.id == "IntEnum" for base in cls.bases) and isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant):
                    names.extend(target.id for target in item.targets if isinstance(target, ast.Name) and not target.id.startswith("_"))
                for name in names:
                    searchable = cls.name + "." + name
                    if all(word in searchable.lower() for word in terms):
                        hit = api_description(cls.name, name, module_name)["members"][0]
                        hits.append({"interface": cls.name, "member": name, "module": module_name, "source": str(sdk_file), **hit})
    hits.sort(key=lambda hit: (hit["member"].lower() != term.lower(), len(hit["interface"]), hit["interface"], hit["member"]))
    return {"sdk_package_dir": str(documentation_paths()["sdk_package_dir"]), "query": term, "total_matches": len(hits), "matches": hits[:limit], "truncated": len(hits) > limit}


def search_documents(term, source="all", *, limit=10, full_text=False, examples_only=False):
    if not term.strip() or not 1 <= limit <= 100:
        raise ValueError("Supply a search term and limit 1..100")
    words = term.lower().split()
    sources = ["processnet", "usage", "examples", "python"] if source == "all" else [source]
    hits, unavailable = [], []
    for kind in sources:
        root = _root(kind)
        if not root.is_dir():
            unavailable.append({"source": kind, "path": str(root), "hint": "Run docs-extract for CHM or configure documentation paths"})
            continue
        scan_root = root / "Python" if kind == "processnet" else root
        if not scan_root.is_dir():
            unavailable.append({"source": kind, "path": str(scan_root), "hint": "Extract the configured ProcessNet CHM"})
            continue
        for path in sorted(scan_root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".html", ".htm", ".py", ".cs", ".pdf"}:
                continue
            relative = path.relative_to(root).as_posix()
            is_example = "coreexample" in relative.lower() or (kind == "examples" and path.suffix.lower() in {".py", ".cs"}) or (kind == "python" and "template" in path.name.lower())
            if examples_only and not is_example:
                continue
            matched = all(word in relative.lower() for word in words)
            snippet = None
            if not matched and full_text and path.suffix.lower() != ".pdf":
                text = html_document(path)["text"] if path.suffix.lower() in {".html", ".htm"} else path.read_text(encoding="utf-8-sig", errors="replace")
                matched = all(word in text.lower() for word in words)
                if matched:
                    position = text.lower().find(words[0])
                    snippet = text[max(0, position - 80):position + 350]
            if matched:
                hits.append({"source": kind, "relative_path": relative, "path": str(path), "example": is_example,
                             "match": "content" if snippet is not None else "path", "snippet": snippet})
    hits.sort(key=lambda item: (not item["example"], item["match"] != "path", len(item["relative_path"]), item["relative_path"]))
    return {"query": term, "matches": hits[:limit], "total_matches": len(hits), "truncated": len(hits) > limit,
            "unavailable_sources": unavailable, "note": "Default searches paths/API names. Use --text for HTML/code contents; PDF matches are filenames, not parsed contents."}


def extract_processnet(*, folder=None, timeout=120):
    """Decompile a local licensed CHM copy into workspace-owned HTML."""
    from .rdx import sha256
    if timeout <= 0:
        raise ValueError("Extraction timeout must be positive")
    paths = documentation_paths()
    chm = paths["processnet_chm"]
    if not chm.is_file():
        raise FileNotFoundError(f"Configured ProcessNet CHM missing: {chm}")
    target = output_path(folder or paths["processnet_html_dir"], overwrite=True)
    fingerprint = sha256(chm)
    manifest_file = target / "extraction.json"
    if manifest_file.is_file():
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if manifest.get("source_sha256") == fingerprint and (target / "Python").is_dir():
            if sum(1 for _ in (target / "Python").rglob("*.html")) != manifest.get("python_html_pages"):
                raise ValueError("CHM cache is incomplete; extract into a new directory")
            return {"folder": str(target), "cached": True, **manifest}
        raise ValueError("Existing CHM cache belongs to a different source; use --output with a new directory")
    if target.exists():
        raise FileExistsError("HTML directory already exists without verified extraction metadata; use --output with a new directory, then configure processnet_html_dir")
    if os.name != "nt":
        raise RuntimeError("CHM extraction requires the Windows HTML Help executable")
    hh = Path(os.environ.get("SystemRoot", "C:/Windows")) / "hh.exe"
    if not hh.is_file():
        raise FileNotFoundError(hh)
    staged = output_path(WORKSPACE / ".reference/chm" / fingerprint, overwrite=True)
    staged.mkdir(parents=True, exist_ok=True)
    local_chm = staged / "ProcessNetHelp.chm"
    if not local_chm.is_file():
        shutil.copy2(chm, output_path(local_chm))
    elif sha256(local_chm) != fingerprint:
        raise ValueError("Staged CHM hash differs; use a fresh cache directory")
    target.mkdir(parents=True, exist_ok=False)
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    process = subprocess.Popen([str(hh), "-decompile", str(target), str(local_chm)], cwd=WORKSPACE, startupinfo=startup)
    deadline, previous_count, stable_since = time.monotonic() + timeout, -1, None
    while time.monotonic() < deadline:
        count = sum(1 for _ in (target / "Python").rglob("*.html"))
        if count > 0 and count == previous_count:
            stable_since = stable_since or time.monotonic()
            if process.poll() == 0 and time.monotonic() - stable_since >= 2:
                manifest = {"source_chm": str(chm), "source_sha256": fingerprint, "python_html_pages": count}
                write_json(manifest_file, manifest)
                return {"folder": str(target), "cached": False, **manifest}
        else:
            stable_since = None
        previous_count = count
        time.sleep(.5)
    raise TimeoutError(f"CHM extraction did not finish with Python HTML within {timeout}s; preserve partial output for diagnostics: {target}")


def sdk_modules():
    names = [path.stem for path in documentation_paths()["sdk_package_dir"].glob("*.py") if not path.name.startswith("_")]
    return sorted(names, key=lambda name: (name != "ProcessNet", name))


def _sdk_file(module):
    if module not in sdk_modules():
        raise KeyError(f"Unknown SDK module {module}; available: {sdk_modules()}")
    return documentation_paths()["sdk_package_dir"] / (module + ".py")


@lru_cache(maxsize=32)
def _cached_tree(filename, mtime, size):
    return ast.parse(Path(filename).read_text(encoding="mbcs"))


def _api_tree(module="ProcessNet"):
    sdk_file = _sdk_file(module)
    # SDK source is ASCII-compatible mbcs; syntax extraction is independent of COM.
    info = sdk_file.stat()
    return sdk_file, _cached_tree(str(sdk_file), info.st_mtime_ns, info.st_size)


def api_description(interface, member=None, module=None):
    node = None
    for module_name in ([module] if module else sdk_modules()):
        if not re.search(r"^class " + re.escape(interface) + r"[(:]", _sdk_file(module_name).read_text(encoding="mbcs"), re.M):
            continue
        sdk_file, tree = _api_tree(module_name)
        node = next((item for item in tree.body if isinstance(item, ast.ClassDef) and item.name == interface), None)
        if node is not None:
            break
    if node is None:
        raise KeyError(f"Unknown SDK interface: {interface}")
    descriptions = []
    is_enum = any(isinstance(base, ast.Name) and base.id == "IntEnum" for base in node.bases)
    for position, item in enumerate(node.body):
        following = node.body[position + 1] if position + 1 < len(node.body) else None
        following_doc = following.value.value if isinstance(following, ast.Expr) and isinstance(following.value, ast.Constant) and isinstance(following.value.value, str) else None
        if isinstance(item, ast.FunctionDef) and not item.name.startswith("_"):
            if member is None or member == item.name:
                signature = interface + "." + item.name + "(" + ", ".join(arg.arg for arg in item.args.args[1:]) + ")"
                descriptions.append({"signature": signature, "documentation": ast.get_docstring(item), "sdk_line": item.lineno})
        if isinstance(item, ast.Assign) and isinstance(item.value, ast.Call) and isinstance(item.value.func, ast.Name) and item.value.func.id == "property":
            for target in item.targets:
                if isinstance(target, ast.Name) and (member is None or member == target.id):
                    descriptions.append({"property": interface + "." + target.id, "writable": len(item.value.args) > 1 and not isinstance(item.value.args[1], ast.Constant), "documentation": following_doc, "sdk_line": item.lineno})
        elif is_enum and isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant):
            for target in item.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_") and (member is None or member == target.id):
                    descriptions.append({"enum": interface + "." + target.id, "value": item.value.value, "documentation": following_doc, "sdk_line": item.lineno})
    if member is not None and not descriptions:
        raise KeyError(f"Unknown member: {interface}.{member}")
    return {"source": str(sdk_file), "module": module_name, "interface": interface, "members": descriptions}


def help_text(relative_path):
    return read_document(relative_path)
