import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import runpy

from .demo import run_demo
from .docs import api_description, api_search, documentation_status, extract_processnet, help_text, read_document, search_documents
from .hybrid import scan, hybrid_query, create_template, instantiate
from .rdx import copy_bundle, load_index, summary
from .runtime import diagnostics, output_path, simulation_settings, write_json
from .session import RecurDynSession


def parser():
    root = argparse.ArgumentParser(description="Control RecurDyn 2024 through its official Python ProcessNet SDK.")
    root.add_argument("--start", action="store_true", help="Start RecurDyn if no active instance is available")
    root.add_argument("--timeout", type=float, default=None, help="COM connection timeout in seconds")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="Read-only environment and COM diagnostics")
    commands.add_parser("start", help="Start or connect to RecurDyn")
    commands.add_parser("status", help="List open documents without modifying them")
    inspect = commands.add_parser("inspect", help="Read bodies and model-level parameters")
    inspect.add_argument("model", nargs="?", help="Omit to inspect the active document")
    scan_command = commands.add_parser("scan", help="Export/index a saved model; reuse a verified RDX cache")
    scan_command.add_argument("model")
    scan_command.add_argument("--output", required=True)
    scan_command.add_argument("--refresh", action="store_true")
    scan_command.add_argument("--limit", type=int, default=40)
    query_command = commands.add_parser("query", help="Query the offline index; optionally fill missing fields with API")
    query_command.add_argument("index")
    query_command.add_argument("--entity", help="Entity ID, unique name, SDK full name or hierarchy path")
    query_command.add_argument("--field", action="append", help="Property path or mass/value/text/local_frame/global_origin/global_frame/connections/stiffness/damping/free_length")
    query_command.add_argument("--api-missing", action="store_true")
    query_command.add_argument("--graph", action="store_true")
    query_command.add_argument("--limit", type=int, default=40)
    template = commands.add_parser("template", help="Make a reusable complete-model template from a verified index")
    template.add_argument("index")
    template.add_argument("--output", required=True)
    template.add_argument("--parameter", action="append", help="Expose selected PVs; default: numeric PVs without references")
    instance = commands.add_parser("instantiate", help="Copy a template, set parameters through API and save a new .rdyn")
    instance.add_argument("template")
    instance.add_argument("--output", required=True)
    instance.add_argument("--parameters", help="JSON file containing parameter selector: numeric value mappings")
    demo = commands.add_parser("demo", help="Create, simulate, and verify a free-fall model in a new workspace folder")
    demo.add_argument("--output", default=None)
    job = commands.add_parser("job", help="Run a JSON model-parameter-simulation job")
    job.add_argument("config")
    channels = commands.add_parser("channels", help="List available channels in a .rplt file")
    channels.add_argument("rplt")
    export = commands.add_parser("export", help="Export selected .rplt channels to CSV")
    export.add_argument("rplt")
    export.add_argument("--channel", action="append", required=True)
    export.add_argument("--output", required=True)
    api = commands.add_parser("api", help="Read installed SDK signatures; no RecurDyn launch required")
    api.add_argument("interface")
    api.add_argument("member", nargs="?")
    api.add_argument("--module", help="SDK file stem such as ProcessNet, Flexible or Control; omitted searches modules")
    api_find = commands.add_parser("api-search", help="Find installed Python SDK interfaces/members by name")
    api_find.add_argument("query")
    api_find.add_argument("--limit", type=int, default=15)
    api_find.add_argument("--module")
    commands.add_parser("docs-paths", help="Show configured SDK, HTML Help, CHM, official template and example paths")
    docs_extract = commands.add_parser("docs-extract", help="Copy/decompile local ProcessNet CHM into this workspace")
    docs_extract.add_argument("--output")
    docs_extract.add_argument("--timeout", type=int, default=120)
    docs_find = commands.add_parser("docs-search", help="Find local official pages and examples")
    docs_find.add_argument("query")
    docs_find.add_argument("--source", choices=["all", "processnet", "usage", "examples", "python"], default="all")
    docs_find.add_argument("--limit", type=int, default=10)
    docs_find.add_argument("--text", action="store_true")
    docs_find.add_argument("--examples-only", action="store_true")
    docs_read = commands.add_parser("docs-read", help="Read a configured local document, preserving Python code blocks")
    docs_read.add_argument("relative_path")
    docs_read.add_argument("--source", choices=["processnet", "usage", "examples", "python"], default="processnet")
    docs_read.add_argument("--max-chars", type=int, default=12000)
    docs_read.add_argument("--offset", type=int, default=0)
    script = commands.add_parser("run-script", help="Run a Python example/generated script inside this toolkit with its configured Python")
    script.add_argument("script")
    script.add_argument("script_args", nargs=argparse.REMAINDER)
    help_command = commands.add_parser("help-page", help="Read an HTML page from the extracted CHM")
    help_command.add_argument("relative_path")
    return root


def run_job(session, filename):
    job_file = Path(filename).resolve()
    settings = json.loads(job_file.read_text(encoding="utf-8-sig"))
    source = Path(settings["model"])
    if not source.is_absolute():
        source = job_file.parent / source
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    folder = output_path(settings["output_dir"])
    duration, steps = simulation_settings(settings["end_time"], settings["steps"])
    folder.mkdir(parents=True, exist_ok=False)
    # Open an independent file to avoid repurposing an already open source document.
    if source.suffix.lower() == ".rdx":
        staged = copy_bundle(source, folder / "input")
    else:
        staged = output_path(folder / ("model" + source.suffix.lower()))
        shutil.copy2(source, staged)
    doc = session.open_model(staged)
    target = staged if staged.suffix == ".rdyn" else session.save(doc, folder / "model.rdyn")
    changes = [session.set_parameter(doc, key, value) for key, value in settings.get("parameters", {}).items()]
    session.commit(doc)
    session.save(doc, target, overwrite=True)
    simulation = session.simulate(doc, end_time=duration, steps=steps, output_prefix=folder / "simulation")
    plot = session.open_plot(simulation["rplt"])
    names = session.channels(plot)
    write_json(folder / "channels.json", names)
    export = None
    if settings.get("channels"):
        export = session.export_csv(plot, settings["channels"], folder / "results.csv")
    report = {"source_model": str(source), "working_model": str(target), "changes": changes,
              "simulation": simulation, "export": export}
    write_json(folder / "job-result.json", report)
    return report


def main(argv=None):
    arguments = parser().parse_args(argv)
    try:
        if hasattr(arguments, "limit") and not 1 <= arguments.limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        session_factory = lambda: RecurDynSession(start=arguments.start, timeout=arguments.timeout)
        if arguments.command == "doctor":
            result = diagnostics()
            code = 0 if result["ready"] else 2
        elif arguments.command == "api":
            result, code = api_description(arguments.interface, arguments.member, arguments.module), 0
        elif arguments.command == "api-search":
            result, code = api_search(arguments.query, limit=arguments.limit, module=arguments.module), 0
        elif arguments.command == "docs-paths":
            result, code = documentation_status(), 0
        elif arguments.command == "docs-extract":
            result, code = extract_processnet(folder=arguments.output, timeout=arguments.timeout), 0
        elif arguments.command == "docs-search":
            result, code = search_documents(arguments.query, arguments.source, limit=arguments.limit, full_text=arguments.text, examples_only=arguments.examples_only), 0
        elif arguments.command == "docs-read":
            result, code = read_document(arguments.relative_path, arguments.source, max_chars=arguments.max_chars, offset=arguments.offset), 0
        elif arguments.command == "run-script":
            filename = output_path(arguments.script, overwrite=True)
            if filename.suffix.lower() != ".py" or not filename.is_file():
                raise ValueError("run-script requires an existing .py inside this toolkit")
            previous = sys.argv
            try:
                sys.argv = [str(filename), *arguments.script_args]
                runpy.run_path(str(filename), run_name="__main__")
            finally:
                sys.argv = previous
            return 0
        elif arguments.command == "help-page":
            result, code = help_text(arguments.relative_path), 0
        elif arguments.command == "scan":
            result, code = scan(arguments.model, arguments.output, session_factory, refresh=arguments.refresh, limit=arguments.limit), 0
        elif arguments.command == "query":
            if arguments.entity:
                result = hybrid_query(arguments.index, arguments.entity, arguments.field, session_factory,
                                      api_missing=arguments.api_missing, graph=arguments.graph, limit=arguments.limit)
            else:
                if arguments.field or arguments.api_missing or arguments.graph:
                    raise ValueError("--field/--api-missing/--graph require --entity")
                result = summary(load_index(arguments.index), limit=arguments.limit)
            code = 0
        elif arguments.command == "template":
            result, code = create_template(arguments.index, arguments.output, arguments.parameter), 0
        elif arguments.command == "instantiate":
            settings = json.loads(Path(arguments.parameters).read_text(encoding="utf-8-sig")) if arguments.parameters else {}
            if not isinstance(settings, dict):
                raise ValueError("Parameters JSON must contain an object of selector: number mappings")
            result, code = instantiate(arguments.template, arguments.output, settings, session_factory), 0
        else:
            with RecurDynSession(start=arguments.start or arguments.command in {"start", "demo"}, timeout=arguments.timeout) as session:
                command = arguments.command
                if command in {"start", "status"}:
                    result = session.status()
                elif command == "inspect":
                    doc = session.open_model(arguments.model) if arguments.model else session.active_document()
                    result = session.inspect(doc)
                elif command == "demo":
                    folder = arguments.output or "runs/demo_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
                    result = run_demo(session, folder)
                elif command == "job":
                    result = run_job(session, arguments.config)
                elif command == "channels":
                    result = session.channels(session.open_plot(arguments.rplt))
                elif command == "export":
                    result = session.export_csv(session.open_plot(arguments.rplt), arguments.channel, arguments.output)
                code = 0
        print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
        return code
    except Exception as error:
        print(json.dumps({"error": str(error), "type": type(error).__name__}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
