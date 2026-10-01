from datetime import datetime
import csv
import math

from .runtime import output_path, write_json


def run_demo(session, folder):
    folder = output_path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    name = "Codex_FreeFall_" + datetime.now().strftime("%H%M%S_%f")
    doc = session.new_model(name, "MKS")
    model = session.sdk.ISubSystem(doc.Model)
    frame = doc.CreateReferenceFrame()
    frame.SetOrigin(0.0, 1.0, 0.0)
    model.CreateBodyBox("FallingBox", frame, 0.1, 0.1, 0.1)
    gravity = 9.80665
    gravity_parameter = model.CreateParametricValue("GravityY", -9.81)
    doc.ModelProperty.GravityX = 0.0
    doc.ModelProperty.GravityZ = 0.0
    doc.ModelProperty.GravityYIDouble.ParametricValue = gravity_parameter
    parameter_change = session.set_parameter(doc, "GravityY", -gravity)
    session.commit(doc)
    doc.Fit()
    model_file = session.save(doc, folder / "freefall.rdyn")
    before = session.inspect(doc)
    write_json(folder / "model.json", before)
    result = session.simulate(doc, end_time=0.2, steps=20, output_prefix=folder / "simulation")
    plot = session.open_plot(result["rplt"])
    names = session.channels(plot)
    write_json(folder / "channels.json", names)
    # Discover the actual result names rather than assuming a plot database prefix.
    time_channel = next((item for item in names if item.upper() == "TIME" or item.upper().endswith("/TIME")), None)
    y_channel = next((item for item in names if item.endswith("/FallingBox/Pos_TY")), None)
    if time_channel is None or y_channel is None:
        raise RuntimeError(f"Expected free-fall channels were not found: {names[:20]}")
    export = session.export_csv(plot, [time_channel, y_channel], folder / "freefall.csv")
    with (folder / "freefall.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))[1:]
    samples = [(float(t), float(y)) for t, y in rows]
    expected = [1.0 - 0.5 * gravity * t * t for t, _ in samples]
    max_error = max(abs(y - truth) for (_, y), truth in zip(samples, expected))
    # Compare actual solver results with a closed-form physics solution.
    complete = len(samples) == 21 and math.isclose(samples[-1][0], 0.2, abs_tol=1e-8)
    report = {
        "status": "passed" if complete and max_error < 1e-5 else "failed",
        "connection": session.status(), "model": str(model_file),
        "parameter_change": parameter_change,
        "simulation": result, "export": export,
        "physics_check": {"equation": "y(t) = 1 - 0.5 * 9.80665 * t^2", "units": "m, kg, s",
                          "expected_final_y": expected[-1], "actual_final_y": samples[-1][1],
                          "max_absolute_error_m": max_error, "tolerance_m": 1e-5, "complete": complete},
    }
    write_json(folder / "verification.json", report)
    if report["status"] != "passed":
        raise RuntimeError(f"Free-fall physics verification failed: {report['physics_check']}")
    return report
