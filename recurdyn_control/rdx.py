"""Offline RDX bundle reader. Never send the raw XML/thumbnail to the model."""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import time
import xml.etree.ElementTree as ET

from .runtime import output_path

SCHEMA = 1
REF = re.compile(r"\{(\d+)\}")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def xml_root(path):
    content = Path(path).read_bytes()
    if b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError("DTD/entity declarations are not supported in RDX XML.")
    return ET.fromstring(content)


def bundle_files(filename):
    """2024 FileExport writes .rdx + .data + .hier + geometry (usually .rxb)."""
    path = Path(filename).resolve()
    if path.suffix.lower() != ".rdx" or not path.is_file():
        raise ValueError(f"Expected an existing RDX: {path}")
    root = xml_root(path)
    if root.tag != "DOCUMENT":
        raise ValueError(f"Unsupported RDX root: {root.tag}")
    files = {path}
    for node in root.findall("./FILES/FILE"):
        text = (node.text or "").strip()
        if not text:
            continue
        candidate = (path.parent / text).resolve()
        if not candidate.is_relative_to(path.parent):
            raise ValueError(f"RDX companion escapes its bundle directory: {text}")
        if not candidate.is_file():
            raise FileNotFoundError(f"Missing RDX companion: {candidate}; copy the complete bundle.")
        files.add(candidate)
    for suffix in (".data", ".hier"):
        candidate = path.with_suffix(suffix)
        if not candidate.is_file():
            raise FileNotFoundError(f"Missing RDX companion: {candidate}; this reader requires the 2024 bundle format.")
        files.add(candidate)
    return sorted(files)


def copy_bundle(filename, folder):
    files = bundle_files(filename)
    folder = output_path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    for source in files:
        shutil.copy2(source, output_path(folder / source.name))
    return folder / Path(filename).name


def scalar(text, type_name):
    text = text.strip()
    try:
        if type_name == "BOOL":
            return {"TRUE": True, "FALSE": False}[text.upper()]
        if type_name in {"INTEGER", "UNSIGNEDINTEGER"}:
            return int(text)
        if type_name in {"DOUBLE", "FLOAT", "VARIANTDOUBLE"}:
            value = float(text)
            return value if math.isfinite(value) else None
        if type_name in {"VECTOR", "DVECTOR", "VARIANTVECTOR"}:
            values = [float(item.strip()) for item in text.split(",")]
            return values if all(math.isfinite(value) for value in values) else None
    except (ValueError, KeyError):
        return None
    return text


def properties(element):
    result = {}

    def visit(node, prefix):
        counts = Counter(child.get("keyword", child.tag) for child in node)
        seen = Counter()
        for child in node:
            key = child.get("keyword", child.tag)
            seen[key] += 1
            if counts[key] > 1:
                key += f"[{seen[key]}]"
            path = "/".join(prefix + [key])
            if child.tag.endswith("PROPERTY"):
                raw = (child.text or "").strip()
                result[path] = {"type": child.get("type", "TEXT"), "raw": raw,
                                "value": scalar(raw, child.get("type", "TEXT")), "source": "rdx"}
                result[path].update({k: v for k, v in child.attrib.items() if k not in {"keyword", "type"}})
                # Container flags matter for disabled friction/motion/force options.
                if node.attrib:
                    result[path]["container_attributes"] = dict(node.attrib)
            else:
                visit(child, prefix + [key])
    visit(element, [])
    return result


def arithmetic(expression):
    """Deliberately narrow evaluator: arithmetic only, no calls, names or eval()."""
    if len(expression) > 4096:
        raise ValueError("Formula too long")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 128:
        raise ValueError("Formula too complex")

    def evaluate(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = float(node.value)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add): value = left + right
            elif isinstance(node.op, ast.Sub): value = left - right
            elif isinstance(node.op, ast.Mult): value = left * right
            elif isinstance(node.op, ast.Div): value = left / right
            elif isinstance(node.op, ast.Pow) and abs(right) <= 32: value = left ** right
            else: raise ValueError("Unsupported arithmetic operator")
        else:
            raise ValueError("Formula needs RecurDyn evaluation")
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Nonfinite formula value")
        return float(value)
    return evaluate(tree.body)


def parse_bundle(filename):
    started = time.perf_counter()
    path = Path(filename).resolve()
    files = bundle_files(path)
    doc = xml_root(path)
    data = xml_root(path.with_suffix(".data"))
    hierarchy = xml_root(path.with_suffix(".hier"))
    if data.tag != "ROOT" or hierarchy.tag != "HIERARCHY":
        raise ValueError("Unsupported RDX data/hierarchy schema")
    warnings = []
    entities = {}
    for group in data:
        for node in group:
            entity_id = node.get("id")
            if entity_id is None:
                warnings.append(f"Unindexed data section: {group.tag}/{node.tag}")
                continue
            if entity_id in entities:
                raise ValueError(f"Duplicate RDX entity ID: {entity_id}")
            entities[entity_id] = {"id": entity_id, "kind": node.tag, "type": node.get("keyword"),
                                   "name": node.get("name"), "properties": properties(node), "source": "rdx"}

    visited = set()

    def walk(node, parent=None, scope=None):
        entity_id = node.get("id")
        if entity_id not in entities:
            raise ValueError(f"Hierarchy ID is absent from data: {entity_id}")
        if entity_id in visited:
            raise ValueError(f"Duplicate hierarchy entity: {entity_id}")
        visited.add(entity_id)
        entity = entities[entity_id]
        name = entity["name"]
        if name != node.get("name") or entity["kind"] != node.tag:
            raise ValueError(f"Data/hierarchy mismatch: {entity_id}")
        owner = entities[parent] if parent else None
        if owner is None:
            full_name, entity_path = name, "/" + name
        elif node.tag == "SUBSYSTEM":
            full_name, entity_path = name + "@" + owner["full_name"], owner["path"] + "/" + name
        elif owner["kind"] == "BODY":
            full_name = owner["name"] + "." + name + "@" + entities[scope]["full_name"]
            entity_path = owner["path"] + "/" + name
        else:
            full_name, entity_path = name + "@" + entities[scope]["full_name"], owner["path"] + "/" + name
        entity.update(parent_id=parent, scope_id=scope, full_name=full_name, path=entity_path)
        if node.tag == "SUBSYSTEM":
            scope = entity_id
        for child in node:
            walk(child, entity_id, scope)
    for node in hierarchy:
        walk(node)
    for entity_id in entities.keys() - visited:
        warnings.append(f"No hierarchy entry for entity ID {entity_id}; resolve by ID, not name")
    roots = [e for e in entities.values() if e["kind"] == "SUBSYSTEM" and e.get("parent_id") is None]
    if len(roots) != 1:
        raise ValueError("Expected exactly one model root")

    edges = []
    for entity in entities.values():
        for property_path, prop in entity["properties"].items():
            refs = []
            if prop.get("id") not in (None, "0"):
                refs.append((prop["id"], "entity_reference"))
            if prop.get("refid") not in (None, "0"):
                refs.append((prop["refid"], "parameter_binding"))
            refs += [(ref, "formula_reference") for ref in REF.findall(prop["raw"])]
            prop["references"] = list(dict.fromkeys(ref for ref, _ in refs))
            for ref, relation in dict.fromkeys(refs):
                edge = {"from": entity["id"], "to": ref, "relation": relation, "property": property_path,
                        "resolved": ref in entities}
                edges.append(edge)
                if ref not in entities:
                    warnings.append(f"Unresolved reference {entity['id']}:{property_path} -> {ref}")
            if refs:
                prop["display"] = REF.sub(lambda match: entities.get(match[1], {}).get("full_name", match[0]), prop["raw"])

    resolving = set()

    def parameter_value(entity_id):
        entity = entities[entity_id]
        if "parameter_value" in entity:
            return entity["parameter_value"]
        if entity_id in resolving or entity["kind"] != "PV":
            raise ValueError("Cyclic or non-PV formula dependency")
        resolving.add(entity_id)
        try:
            raw = entity["properties"]["ENTITY/Content"]["raw"]
            expression = REF.sub(lambda match: "(" + str(parameter_value(match[1])) + ")", raw)
            value = arithmetic(expression)
            entity["parameter_value"] = value
            entity["parameter_value_source"] = "rdx_arithmetic"
            return value
        finally:
            resolving.remove(entity_id)
    for entity in entities.values():
        if entity["kind"] == "PV":
            try:
                parameter_value(entity["id"])
            except (ValueError, KeyError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError) as error:
                entity["parameter_value_missing"] = str(error)

    # Record resource paths without copying unrelated files or claiming portability.
    resources = []
    for owner_id, props in [(e["id"], e["properties"]) for e in entities.values()] + [("document", properties(doc.find("MODEL")))]:
        for key, prop in props.items():
            if prop["type"] == "TEXT" and prop["raw"] and re.search(r"file|path|directory", key, re.I):
                resources.append({"owner_id": owner_id, "property": key, "path": prop["raw"]})

    units = {p.tag: (p.text or "").strip() for p in doc.find("./MODEL/UNIT")}
    settings = properties(doc.find("SETTINGS"))
    for key, prop in settings.items():
        # refid in DOCUMENT/MODEL also denotes file references; only variant
        # properties in SETTINGS are interpreted as parametric bindings here.
        if prop["type"].startswith("VARIANT") and prop.get("refid") not in (None, "0"):
            ref = prop["refid"]
            edges.append({"from": "document", "to": ref, "relation": "parameter_binding",
                          "property": "SETTINGS/" + key, "resolved": ref in entities})
            if ref not in entities:
                warnings.append(f"Unresolved document parameter binding: {key} -> {ref}")
    index = {"schema": SCHEMA, "rdx_version": doc.get("version"), "root_id": roots[0]["id"],
             "units": units, "entities": entities, "edges": edges, "warnings": sorted(set(warnings)),
             "document_properties": properties(doc.find("MODEL")), "document_settings": settings, "resources": resources,
             "bundle": {"rdx": str(path), "files": [{"path": str(p), "bytes": p.stat().st_size, "sha256": sha256(p)} for p in files]},
             "metrics": {"parse_seconds": time.perf_counter() - started,
                         "bundle_bytes": sum(p.stat().st_size for p in files), "api_entity_reads": 0}}
    return index


def load_index(filename, *, verify=True):
    path = Path(filename).resolve()
    index = json.loads(path.read_text(encoding="utf-8"))
    if index.get("schema") != SCHEMA:
        raise ValueError("Unsupported model index schema; rescan the model")
    for record in index["bundle"]["files"]:
        candidate = Path(record["path"])
        if not candidate.is_absolute():
            record["path"] = str((path.parent / candidate).resolve())
    rdx = Path(index["bundle"]["rdx"])
    if not rdx.is_absolute():
        index["bundle"]["rdx"] = str((path.parent / rdx).resolve())
    if verify:
        for record in index["bundle"]["files"]:
            candidate = Path(record["path"])
            if not candidate.is_file() or sha256(candidate) != record["sha256"]:
                raise ValueError(f"Snapshot changed or incomplete; rescan: {candidate}")
        source = index.get("source_model")
        if source:
            for record in source.get("files", [source]):
                if not Path(record["path"]).is_file() or sha256(record["path"]) != record["sha256"]:
                    raise ValueError("Source model or RDX companion changed; rescan before querying this snapshot")
    return index


def select_entity(index, selector):
    entities = index["entities"]
    if selector == "document":
        props = {"MODEL/" + key: value for key, value in index["document_properties"].items()}
        props.update({"SETTINGS/" + key: value for key, value in index.get("document_settings", {}).items()})
        return {"id": "document", "kind": "DOCUMENT", "type": "Document", "name": "document", "full_name": "document", "properties": props}
    if selector in entities:
        return entities[selector]
    matches = [e for e in entities.values() if selector in (e.get("full_name"), e.get("path"), e.get("name"))]
    if not matches:
        raise KeyError(f"Entity not found: {selector}")
    if len(matches) > 1:
        raise ValueError(f"Ambiguous entity {selector}; use ID/full_name/path: " + ", ".join(e.get("full_name", e["id"]) for e in matches))
    return matches[0]


def connection(index, entity):
    result = {}
    for label in ("BaseMarker", "ActionMarker"):
        prop = entity["properties"].get("CONNECTOR/" + label)
        if prop is not None:
            marker = index["entities"].get(prop.get("id"), {})
            body = index["entities"].get(marker.get("parent_id"), {})
            result[label] = {"marker_id": prop.get("id"), "marker": marker.get("full_name"),
                             "body_id": body.get("id"), "body": body.get("full_name")}
    return result


def summary(index, *, limit=40):
    entities = list(index["entities"].values())
    useful = [e for e in entities if e["kind"] in {"SUBSYSTEM", "BODY", "JOINT", "FORCE", "PV", "EXPRESSION"}
              and e["type"] not in {"Dummy", "Ground"}]
    catalog = [{k: e.get(k) for k in ("id", "kind", "type", "full_name", "parent_id")} for e in useful[:limit]]
    motions = [{"owner_id": e["id"], "owner": e.get("full_name"), "property": key,
                "enabled": e["properties"].get("ENTITY/IncludeMotion", {}).get("value"),
                "expression_id": prop.get("id")} for e in entities for key, prop in e["properties"].items()
               if "/MOTION/" in key and key.endswith("/Expression")]
    result = {"model": index["entities"][index["root_id"]]["name"], "units": index["units"],
              "counts": dict(Counter(e["kind"] for e in entities)), "catalog": catalog,
              "catalog_total": len(useful), "catalog_truncated": len(useful) > limit,
              "motions": motions[:limit], "motions_total": len(motions),
              "reference_count": len(index["edges"]), "warning_count": len(index["warnings"]),
              "warnings": index["warnings"][:limit], "resource_count": len(index["resources"]),
              "metrics": index["metrics"]}
    return result


def field_value(index, entity, field):
    props = entity["properties"]
    if field in props:
        prop = dict(props[field])
        if prop.get("refid"):
            target = index["entities"].get(prop["refid"], {})
            if target.get("kind") == "PV" and "parameter_value" in target:
                prop["resolved_value"] = target["parameter_value"]
                prop["resolved_value_source"] = "rdx_arithmetic"
        return {"value": prop, "source": "rdx"}
    if field == "connections" and entity["kind"] in {"JOINT", "FORCE"}:
        return {"value": connection(index, entity), "source": "rdx"}
    if field == "local_frame" and any(key.startswith("REFFRAME/") for key in props):
        return {"value": {"owner_id": entity.get("parent_id"), "properties": {k: v for k, v in props.items() if k.startswith("REFFRAME/")}}, "source": "rdx", "note": "Stored frame data; explicit reference properties can override the owner frame. Use global_origin/global_frame for model-frame coordinates."}
    if field == "value" and entity["kind"] == "PV" and "parameter_value" in entity:
        return {"value": entity["parameter_value"], "source": entity["parameter_value_source"]}
    if field == "mass" and entity["kind"] == "BODY":
        prop = props.get("MATERIAL/Mass")
        if prop:
            if prop.get("refid"):
                pv = index["entities"].get(prop["refid"], {})
                if "parameter_value" in pv:
                    return {"value": pv["parameter_value"], "source": "rdx_arithmetic"}
            elif isinstance(prop.get("value"), (int, float)):
                return {"value": prop["value"], "source": "rdx"}
    if field in {"stiffness", "damping", "free_length"} and entity["kind"] == "FORCE" and entity["type"] == "Spring":
        paths = {"stiffness": "ENTITY/FORCECHARACTERISTIC/COEFFICIENTSTIFFNESS/CoefficientValue",
                 "damping": "ENTITY/FORCECHARACTERISTIC/COEFFICIENTDAMPING/CoefficientValue", "free_length": "ENTITY/FreeLength"}
        prop = props.get(paths[field], {})
        if field in {"stiffness", "damping"}:
            mode_path = paths[field].rsplit("/", 1)[0] + "/UseCoefficientValue"
            if props.get(mode_path, {}).get("value") is not True:
                return {"value": None, "source": "missing", "reason": "Spline coefficient mode; inspect its referenced spline instead of treating the stored coefficient as an effective constant"}
        if prop.get("refid"):
            target = index["entities"].get(prop["refid"], {})
            if "parameter_value" in target:
                return {"value": target["parameter_value"], "source": "rdx_arithmetic", "parameter_id": target["id"]}
        elif isinstance(prop.get("value"), (int, float)):
            return {"value": prop["value"], "source": "rdx"}
    return {"value": None, "source": "missing", "reason": entity.get("parameter_value_missing", "Field requires API or is unsupported")}


def query(index, selector, fields=None, *, graph=False, limit=40):
    entity = select_entity(index, selector)
    result = {k: entity.get(k) for k in ("id", "kind", "type", "name", "full_name", "path", "parent_id", "scope_id")}
    if fields:
        result["fields"] = {field: field_value(index, entity, field) for field in fields}
    else:
        items = list(entity["properties"].items())
        result.update(properties=dict(items[:limit]), property_total=len(items), properties_truncated=len(items) > limit)
        if entity["kind"] in {"JOINT", "FORCE"}: result["connections"] = connection(index, entity)
        if entity["kind"] == "PV": result["value"] = field_value(index, entity, "value")
    if graph:
        incident = [e for e in index["edges"] if entity["id"] in (e["from"], e["to"])]
        result["edges"] = [{**edge, "from_name": index["entities"].get(edge["from"], {}).get("full_name"),
                            "to_name": index["entities"].get(edge["to"], {}).get("full_name")} for edge in incident[:limit]]
        result["edge_total"] = len(incident)
        children = [e for e in index["entities"].values() if e.get("parent_id") == entity["id"]]
        result["children"] = [{k: e.get(k) for k in ("id", "kind", "full_name")} for e in children[:limit]]
        result["children_total"] = len(children)
    return result
