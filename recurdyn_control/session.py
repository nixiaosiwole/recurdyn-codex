from __future__ import annotations

import csv
import math
from pathlib import Path
import subprocess
import time

from .runtime import WORKSPACE, config, finite_number, install_dir, load_sdk, output_path, simulation_settings


class RecurDynSession:
    """One COM apartment; connect and call methods from the same Python thread.

    Closing the session releases Python references, leaving RecurDyn and documents open.
    """

    def __init__(self, *, start=False, timeout=None):
        self.sdk = load_sdk()
        self.start = start
        self.timeout = finite_number(timeout if timeout is not None else config()["connect_timeout_seconds"], positive=True)
        self.application = None
        self._bridge = None
        self._initialized = False
        self._process = None
        self._plots = {}

    def __enter__(self):
        import pythoncom
        import pywintypes
        import win32com.client

        pythoncom.CoInitialize()
        self._initialized = True
        try:
            try:
                pywintypes.IID("RecurDyn.RDApplication")
            except pywintypes.com_error as error:
                raise RuntimeError("RecurDyn COM registration is unavailable in this execution context. "
                                   "Use the Windows host execution channel; do not infer that RecurDyn needs reinstalling from a sandbox failure.") from error
            deadline = time.monotonic() + self.timeout
            while True:
                try:
                    active = win32com.client.GetActiveObject("RecurDyn.RDApplication")
                    self._bridge = self.sdk.IRecurDynApp(active._oleobj_)
                    self.application = self.sdk.IApplication(self._bridge.RecurDynApplication)
                    break
                except pywintypes.com_error as error:
                    if not self.start:
                        raise RuntimeError("Cannot attach to RecurDyn. Use 'rd.ps1 start' on the Windows host. "
                                           f"COM detail: {error}") from error
                    if self._process is None:
                        executable = install_dir() / "Bin" / "RecurDyn.exe"
                        # STARTUPINFO avoids a foreground window for the background helper.
                        startup = subprocess.STARTUPINFO()
                        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startup.wShowWindow = 0
                        self._process = subprocess.Popen([str(executable)], cwd=str(WORKSPACE), startupinfo=startup)
                    if time.monotonic() >= deadline:
                        raise TimeoutError("RecurDyn COM did not become available. Check startup, license, and Windows execution context.") from error
                    pythoncom.PumpWaitingMessages()
                    time.sleep(0.5)
            connected = Path(self.application.GetInstallationPath()).resolve()
            if connected not in {install_dir(), install_dir() / "Bin"}:
                raise RuntimeError(f"Connected to a different RecurDyn installation: {connected}")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        self._plots.clear()
        self.application = None
        self._bridge = None
        if self._initialized:
            import pythoncom
            pythoncom.CoUninitialize()
            self._initialized = False

    def status(self):
        documents = self.application.ModelDocumentCollection
        active = self.application.ActiveModelDocument
        return {
            "application": self.application.Name,
            "version": self.application.Version,
            "processnet_version": self.application.ProcessNetVersion,
            "install_dir": self.application.GetInstallationPath(),
            "models": [item.Name for item in documents],
            "active_model": None if active is None else active.Name,
        }

    def active_document(self):
        document = self.application.ActiveModelDocument
        if document is None:
            raise RuntimeError("There is no active model document.")
        return self.sdk.IModelDocument(document)

    def open_model(self, filename):
        path = Path(filename).resolve()
        if not path.is_file() or path.suffix.lower() not in {".rdyn", ".rdx"}:
            raise ValueError(f"Expected an existing .rdyn or .rdx model: {path}")
        document = self.application.OpenModelDocument(str(path))
        if document is None:
            raise RuntimeError(f"RecurDyn could not open: {path}")
        return self.sdk.IModelDocument(document)

    def new_model(self, name, units="MKS"):
        if any(item.Name == name for item in self.application.ModelDocumentCollection):
            raise ValueError(f"A model document named {name} is already open.")
        return self.sdk.IModelDocument(self.application.NewModelDocumentWithUnitSystem(name, getattr(self.sdk.UnitSystem, units)))

    def inspect(self, document):
        model = self.sdk.ISubSystem(document.Model)
        units = document.Unit
        return {
            "name": document.Name,
            "model_file": document.GetPath(self.sdk.PathType.WorkingDocument),
            "working_folder": document.GetPath(self.sdk.PathType.WorkingFolder),
            "bodies": [{"name": body.Name, "full_name": body.FullName, "mass": body.Mass.Value} for body in model.BodyCollection],
            "parameters": [{"name": item.Name, "value": item.Value, "text": item.Text} for item in model.ParametricValueCollection],
            "subsystems": [item.Name for item in model.SubSystemCollection],
            "units": {"length": self.sdk.UnitLength(units.UnitLength).name,
                      "mass": self.sdk.UnitMass(units.UnitMass).name,
                      "time": self.sdk.UnitTime(units.UnitTime).name},
        }

    def commit(self, document):
        if not document.Validate():
            raise RuntimeError("RecurDyn model validation failed.")
        document.Redraw()
        document.UpdateDatabaseWindow()
        document.SetModified()
        document.SetUndoHistory("Codex Python ProcessNet")

    def save(self, document, filename, *, overwrite=False):
        path = output_path(filename, overwrite=overwrite)
        if path.suffix.lower() != ".rdyn":
            raise ValueError("Save target must be a .rdyn file.")
        path.parent.mkdir(parents=True, exist_ok=True)
        if not document.FileSave(str(path), overwrite):
            raise RuntimeError(f"RecurDyn FileSave returned false: {path}")
        if not path.is_file():
            raise RuntimeError(f"Save target was not created: {path}")
        return path

    def set_parameter(self, document, name, value):
        value = finite_number(value)
        model = self.sdk.ISubSystem(document.Model)
        if "@" in name:
            pieces = name.split("@")
            if pieces[-1] != model.FullName:
                raise KeyError(f"Parameter belongs to another model: {name}")
            owner = model
            for subsystem_name in reversed(pieces[1:-1]):
                owner = self.sdk.ISubSystem(owner.SubSystemCollection.Item(subsystem_name))
            local = pieces[0].split(".")
            if len(local) == 2:
                body_name, parameter_name = local
                ground, dummy = owner.Ground, owner.DummyBody
                if ground is not None and body_name == ground.Name:
                    owner = self.sdk.IBody(ground)
                elif dummy is not None and body_name == dummy.Name:
                    owner = self.sdk.IBody(dummy)
                else:
                    owner = self.sdk.IBody(owner.BodyCollection.Item(body_name))
            elif len(local) == 1:
                parameter_name = local[0]
            else:
                raise ValueError("Unsupported parameter ownership chain; use the indexed template workflow")
            parameter = self.sdk.IParametricValue(owner.ParametricValueCollection.Item(parameter_name))
            if parameter.FullName != name:
                raise KeyError(f"Parameter full name did not match: {name}")
            previous = parameter.Value
            parameter.Value = value
            return {"name": parameter.FullName, "before": previous, "after": parameter.Value}
        def collect(subsystem):
            result = list(subsystem.ParametricValueCollection)
            bodies = list(subsystem.BodyCollection) + [subsystem.Ground, subsystem.DummyBody]
            unique_bodies = {body.FullName: body for body in bodies if body is not None}
            for body in unique_bodies.values():
                result.extend(body.ParametricValueCollection)
            for sub in subsystem.SubSystemCollection:
                result.extend(collect(self.sdk.ISubSystem(sub)))
            return result
        candidates = list({item.FullName: item for item in collect(model) if name == item.Name}.values())
        if not candidates:
            raise KeyError(f"Parameter not found: {name}")
        if len(candidates) != 1:
            raise ValueError(f"Ambiguous parameter {name}; use full name: " + ", ".join(item.FullName for item in candidates))
        parameter = self.sdk.IParametricValue(candidates[0])
        previous = parameter.Value
        parameter.Value = value
        return {"name": parameter.FullName, "before": previous, "after": parameter.Value}

    def simulate(self, document, *, end_time, steps, output_prefix):
        end_time, steps = simulation_settings(end_time, steps)
        prefix = output_path(output_prefix)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        if list(prefix.parent.glob(prefix.name + "*")):
            raise FileExistsError(f"Simulation output prefix is already in use: {prefix}")
        # Save before running so RecurDyn's working folder is a workspace directory.
        working_model = Path(document.GetPath(self.sdk.PathType.WorkingDocument)).resolve()
        output_path(working_model, overwrite=True)
        if prefix.parent != working_model.parent:
            raise ValueError("Simulation prefix must be in the saved model's working folder.")
        prop = document.ModelProperty.DynamicAnalysisProperty
        prop.SimulationTime.Value = end_time
        prop.SimulationStep.Value = steps
        prop.MatchSolvingStepSize = True
        document.UseOutputFileName = True
        # ProcessNet accepts a filename here, not an absolute path (Error 1048503).
        document.SetOutputFileName(prefix.name)
        self.commit(document)
        self.save(document, working_model, overwrite=True)
        previous_results = {path.resolve(): path.stat().st_mtime_ns for path in prefix.parent.rglob("*.rplt")}
        previous_message = self.application.GetOutputMessage()
        started = time.monotonic()
        # Official synchronous API. AnalysisStart is the asynchronous variant.
        document.Analysis(self.sdk.AnalysisMode.Dynamic)
        rplt = Path(document.GetPath(self.sdk.PathType.RecentRPLTFile))
        if not rplt.is_file() or not rplt.resolve().is_relative_to(prefix.parent):
            raise RuntimeError("Analysis returned without a workspace .rplt result. " + self.application.GetOutputMessage())
        if previous_results.get(rplt.resolve()) == rplt.stat().st_mtime_ns:
            raise RuntimeError("Analysis did not produce a new result; the previous .rplt cannot verify completion.")
        plot = self.open_plot(rplt)
        names = self.channels(plot)
        time_channel = next((name for name in names if name.upper() == "TIME" or name.upper().endswith("/TIME")), None)
        if time_channel is None:
            raise RuntimeError("Solver result has no time channel; completion cannot be verified.")
        times = list(plot.GetPlotDataFromIndex(0, time_channel))
        if not times or not all(math.isfinite(value) for value in times) or not math.isclose(times[-1], end_time, rel_tol=1e-7, abs_tol=1e-8):
            raise RuntimeError(f"Solver did not reach requested end time {end_time}; last time: {times[-1] if times else None}")
        message = self.application.GetOutputMessage()
        if message.startswith(previous_message):
            message = message[len(previous_message):]
        log_path = output_path(prefix.parent / (prefix.name + "_messages.txt"))
        with log_path.open("x", encoding="utf-8") as stream:
            stream.write(message)
        return {"end_time": end_time, "steps": steps, "elapsed_seconds": time.monotonic() - started,
                "rplt": str(rplt.resolve()), "rows": len(times), "final_time": times[-1], "message_log": str(log_path)}

    def open_plot(self, filename):
        path = Path(filename).resolve()
        if not path.is_file() or path.suffix.lower() != ".rplt":
            raise ValueError(f"Expected an existing .rplt file: {path}")
        if str(path) in self._plots:
            return self._plots[str(path)]
        plot = self.application.OpenPlotDocument(str(path))
        if plot is None:
            raise RuntimeError(f"Could not open plot file: {path}")
        self._plots[str(path)] = self.sdk.IPlotDocument(plot)
        return self._plots[str(path)]

    def channels(self, plot):
        return list(plot.GetPlottableNameList(0))

    def export_csv(self, plot, channels, filename):
        if not channels:
            raise ValueError("Select at least one result channel.")
        path = output_path(filename)
        names = self.channels(plot)
        missing = [name for name in channels if name not in names]
        if missing:
            raise ValueError(f"Unknown result channels: {missing}. Use the channels command.")
        columns = [list(plot.GetPlotDataFromIndex(0, name)) for name in channels]
        if not columns[0] or any(len(column) != len(columns[0]) for column in columns):
            raise RuntimeError("Result columns are empty or differ in length.")
        if any(not math.isfinite(value) for column in columns for value in column):
            raise RuntimeError("Result contains nonfinite values.")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(channels)
            writer.writerows(zip(*columns))
        return {"csv": str(path), "rows": len(columns[0]), "channels": channels}
