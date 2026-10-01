"""RDX first, selective ProcessNet enrichment, and complete-model templates."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import shutil
import time
import uuid
import re

from .rdx import bundle_files, copy_bundle, load_index, parse_bundle, query, select_entity, sha256, summary
from .runtime import finite_number, output_path, write_json


def scan(filename, folder, session_factory, *, refresh=False, limit=40):
    source = Path(filename).resolve()
    if not source.is_file() or source.suffix.lower() not in {".rdyn", ".rdx"}:
        raise ValueError(f"Expected an existing .rdyn/.rdx: {source}")
    folder = output_path(folder, overwrite=True)
    index_file = folder / "index.json"
    if index_file.is_file() and not refresh:
        index = load_index(index_file)
        if index.get("source_model", {}).get("path") != str(source):
            raise ValueError("Cache belongs to a different source model; choose a new output directory")
        return {"index": str(index_file), "cache_hit": True, **summary(index, limit=limit)}
    if folder.exists():
        if not refresh:
            raise FileExistsError("Scan output exists without a usable cache; use a new directory or --refresh")
        folder = output_path(folder / ("snapshot_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")))
    folder.mkdir(parents=True, exist_ok=False)
    source_files = bundle_files(source) if source.suffix.lower() == ".rdx" else [source]
    source_records = [{"path": str(p), "sha256": sha256(p)} for p in source_files]
    before = sha256(source)
    exported = 0.0
    if source.suffix.lower() == ".rdx":
        rdx = copy_bundle(source, folder / "bundle")
    else:
        # Read the saved model, including when an unsaved source document is open.
        stage = folder / "source"
        stage.mkdir()
        staged = output_path(stage / source.name)
        shutil.copy2(source, staged)
        bundle = output_path(folder / "bundle")
        bundle.mkdir()
        rdx = bundle / "model.rdx"
        with session_factory() as session:
            document = session.open_model(staged)
            try:
                started = time.perf_counter()
                document.FileExport(str(rdx), False)
                exported = time.perf_counter() - started
            finally:
                session.application.CloseModelDocument(document)
    if any(record["sha256"] != sha256(record["path"]) for record in source_records):
        raise ValueError("Source model changed during snapshot creation; rescan")
    index = parse_bundle(rdx)
    index["source_model"] = {"path": str(source), "sha256": before, "files": source_records, "mode": "saved_file_snapshot"}
    index["metrics"]["export_seconds"] = exported
    index_file = write_json(folder / "index.json", index)
    return {"index": str(index_file), "cache_hit": False, **summary(index, limit=limit)}


def _typed(session, document, entity, interface, index):
    # Generic.QueryInterface is not exposed by this out-of-process COM server.
    # Follow just the indexed ownership chain and use typed collection lookups.
    chain = []
    current = entity
    while current.get("parent_id"):
        chain.append(current)
        current = index["entities"][current["parent_id"]]
    obj = session.sdk.ISubSystem(document.Model)
    collections = {"SUBSYSTEM": ("SubSystemCollection", "ISubSystem"), "BODY": ("BodyCollection", "IBody"),
                   "MARKER": ("MarkerCollection", "IMarker"), "PV": ("ParametricValueCollection", "IParametricValue"),
                   "EXPRESSION": ("ExpressionCollection", "IExpression")}
    for current in reversed(chain):
        if current["kind"] == "BODY" and current["type"] == "Dummy":
            raise ValueError("Internal RDX dummy body has no verified public API adapter")
        if current["kind"] == "BODY" and current["type"] == "Ground":
            obj = session.sdk.IBody(obj.Ground)
        else:
            collection, cls = collections[current["kind"]]
            obj = getattr(session.sdk, cls)(getattr(obj, collection).Item(current["name"]))
        if obj.Name != current["name"]:
            raise ValueError("API collection lookup did not match the indexed object")
    if obj.FullName != entity.get("full_name"):
        raise ValueError("API object full name did not match the indexed object")
    return getattr(session.sdk, interface)(obj)


def api_fields(session, document, entity, fields, index):
    """Explicit field allowlist; do not enumerate an entire COM object graph."""
    interfaces = {"BODY": "IBody", "MARKER": "IMarker", "SUBSYSTEM": "ISubSystem", "PV": "IParametricValue", "EXPRESSION": "IExpression"}
    result = {}
    obj = None
    for field in fields:
        if not can_enrich(entity, field):
            result[field] = {"value": None, "source": "missing", "reason": "No verified API adapter for this field/entity kind"}
            continue
        try:
            if obj is None:
                obj = _typed(session, document, entity, interfaces[entity["kind"]], index)
            if field == "global_origin": value = list(obj.RefFrame.AtModel().GetOrigin())
            elif field == "global_frame":
                frame = obj.RefFrame.AtModel()
                value = {"origin": list(frame.GetOrigin()), "euler": list(frame.GetEulerAngle()), "relative_to": "model"}
            elif field == "value": value = obj.Value
            elif field == "text": value = obj.Text
            elif field == "mass": value = obj.Mass.Value
            result[field] = {"value": value, "source": "api", "interface": interfaces[entity["kind"]]}
        except Exception as error:
            result[field] = {"value": None, "source": "missing", "reason": str(error)}
    return result


def can_enrich(entity, field):
    if entity["kind"] == "BODY" and entity["type"] == "Dummy":
        return False
    return ((field in {"global_origin", "global_frame"} and entity["kind"] in {"BODY", "MARKER", "SUBSYSTEM"})
            or (field in {"value", "text"} and entity["kind"] == "PV")
            or (field == "text" and entity["kind"] == "EXPRESSION")
            or (field == "mass" and entity["kind"] == "BODY"))


def hybrid_query(index_file, selector, fields, session_factory, *, api_missing=False, graph=False, limit=40):
    index = load_index(index_file)
    result = query(index, selector, fields, graph=graph, limit=limit)
    missing = [name for name, value in result.get("fields", {}).items() if value["source"] == "missing"]
    result["api_entity_reads"] = 0
    result["api_field_reads"] = 0
    result["api_attempted"] = False
    if api_missing and missing:
        if not any(can_enrich(select_entity(index, selector), field) for field in missing):
            result["missing_fields"] = missing
            return result
        result["api_attempted"] = True
        # Opening a private copy avoids reading unsaved changes in an open snapshot.
        folder = Path(index_file).resolve().parent / "api_queries" / uuid.uuid4().hex
        staged = copy_bundle(index["bundle"]["rdx"], folder)
        with session_factory() as session:
            document = session.open_model(staged)
            try:
                values = api_fields(session, document, select_entity(index, selector), missing, index)
                result["fields"].update(values)
                result["api_entity_reads"] = int(any(value["source"] == "api" for value in values.values()))
                result["api_field_reads"] = sum(value["source"] == "api" for value in values.values())
                result["api_snapshot"] = str(staged)
            finally:
                session.application.CloseModelDocument(document)
    result["missing_fields"] = [name for name, value in result.get("fields", {}).items() if value["source"] == "missing"]
    return result


def create_template(index_file, folder, selectors=None):
    index = load_index(index_file)
    selected = [select_entity(index, selector) for selector in selectors] if selectors else [
        e for e in index["entities"].values() if e["kind"] == "PV" and "parameter_value" in e
        and not e["properties"]["ENTITY/Content"]["references"]]
    if any(e["kind"] != "PV" for e in selected):
        raise ValueError("Only parametric values can be exposed as template parameters")
    if not selected:
        raise ValueError("No editable numeric parameter found; select specific PVs with --parameter")
    if len({e["id"] for e in selected}) != len(selected):
        raise ValueError("Duplicate template parameter")
    folder = output_path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    rdx = copy_bundle(index["bundle"]["rdx"], folder / "bundle")
    template_index = parse_bundle(rdx)
    # Relative bundle metadata makes a template movable within the workspace.
    template_index["bundle"]["rdx"] = str(rdx.relative_to(folder))
    for record in template_index["bundle"]["files"]:
        record["path"] = str(Path(record["path"]).relative_to(folder))
    write_json(folder / "index.json", template_index)
    parameters = [{"id": e["id"], "full_name": e["full_name"], "path": e["path"],
                   "default": e.get("parameter_value"), "formula": e["properties"]["ENTITY/Content"]["raw"],
                   "overriding_replaces_formula": bool(e["properties"]["ENTITY/Content"]["references"])} for e in selected]
    manifest = {"schema": 1, "kind": "recurdyn_complete_model_template", "rdx": "bundle/" + rdx.name,
                "index": "index.json", "parameters": parameters, "units": index["units"],
                "resources": index["resources"], "source_index": str(Path(index_file).resolve()),
                "portability": "Preserves the RDX bundle. Referenced external resources/toolkit licenses require separate validation."}
    path = write_json(folder / "template.json", manifest)
    return {"template": str(path), "parameters": parameters, "resource_count": len(index["resources"])}


def instantiate(template_file, folder, settings, session_factory):
    template_file = Path(template_file).resolve()
    manifest = json.loads(template_file.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("kind") != "recurdyn_complete_model_template":
        raise ValueError("Unsupported template manifest")
    index_path = (template_file.parent / manifest["index"]).resolve()
    rdx_path = (template_file.parent / manifest["rdx"]).resolve()
    if not index_path.is_relative_to(template_file.parent) or not rdx_path.is_relative_to(template_file.parent):
        raise ValueError("Template files must stay inside the template directory")
    index = load_index(index_path)
    if Path(index["bundle"]["rdx"]).resolve() != rdx_path:
        raise ValueError("Template bundle does not match its verified index")
    allowed = {p["id"]: p for p in manifest["parameters"]}
    changes = []
    for selector, value in settings.items():
        entity = select_entity(index, selector)
        if entity["id"] not in allowed:
            raise ValueError(f"Parameter is not exposed by the template: {selector}")
        changes.append((entity, finite_number(value)))
    if len({e["id"] for e, _ in changes}) != len(changes):
        raise ValueError("The same template parameter was supplied under multiple names")
    folder = output_path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    staged = copy_bundle(rdx_path, folder / "input")
    with session_factory() as session:
        document = session.open_model(staged)
        try:
            applied = []
            for entity, value in changes:
                parameter = _typed(session, document, entity, "IParametricValue", index)
                previous = parameter.Value
                parameter.Value = value
                applied.append({"name": parameter.FullName, "before": previous, "after": parameter.Value})
            session.commit(document)
            target = session.save(document, folder / "model.rdyn")
            exported = output_path(folder / "snapshot")
            exported.mkdir()
            document.FileExport(str(exported / "model.rdx"), False)
        finally:
            session.application.CloseModelDocument(document)
    after = parse_bundle(exported / "model.rdx")
    after_index = write_json(folder / "index.json", after)
    # Compare the complete structural signature after import/save/export.
    signature = lambda model: sorted((e.get("path"), e["kind"], e["type"]) for e in model["entities"].values())
    changed_paths = {entity["path"] for entity, _ in changes}
    def owner_path(model, entity_id):
        return model["entities"].get(entity_id, {}).get("path", entity_id)
    def topology(model):
        return sorted((owner_path(model, edge["from"]), edge["relation"], edge["property"], owner_path(model, edge["to"]))
                      for edge in model["edges"] if owner_path(model, edge["from"]) not in changed_paths)
    def formulas(model):
        return sorted((entity["path"], key, re.sub(r"\{(\d+)\}", lambda match: "{" + owner_path(model, match[1]) + "}", prop["raw"]))
                      for entity in model["entities"].values() for key, prop in entity["properties"].items()
                      if prop["type"] == "FORMULA" and entity.get("path") not in changed_paths)
    if signature(index) != signature(after) or topology(index) != topology(after) or formulas(index) != formulas(after):
        raise RuntimeError("Template instance failed the structure/connection round-trip check")
    checked = []
    for entity, value in changes:
        instance = select_entity(after, entity["path"])
        actual = instance.get("parameter_value")
        if actual is None or abs(actual - value) > max(1e-10, abs(value) * 1e-10):
            raise RuntimeError(f"Saved parameter did not match: {entity['full_name']}")
        checked.append({"path": entity["path"], "expected": value, "actual": actual})
    report = {"model": str(target), "template": str(template_file), "index": str(after_index),
              "changes": applied, "structure_round_trip": "passed", "parameter_checks": checked,
              "resource_count": len(after["resources"])}
    write_json(folder / "instance-result.json", report)
    return report
