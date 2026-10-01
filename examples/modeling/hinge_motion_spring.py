"""Own MKS example: Ground -> revolute -> driven Link, plus a linear spring.

Run using rd.ps1 run-script. Uses the recipient's installed official SDK.
Coordinates are in the root model frame; joint's unrotated Z axis is the axis.
"""
import argparse
from datetime import datetime
import json
import math

from recurdyn_control import RecurDynSession
from recurdyn_control.rdx import connection, parse_bundle, query, select_entity, summary
from recurdyn_control.runtime import finite_number, output_path, simulation_settings, write_json


def frame(document, x, y, z):
    result = document.CreateReferenceFrame()
    result.SetOrigin(x, y, z)
    return result


def build_and_check(folder, *, build_only=False, speed=.2, end_time=.2, steps=20):
    speed = finite_number(speed)
    end_time, steps = simulation_settings(end_time, steps)
    folder = output_path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    # This example documents its own assumptions rather than silently adopting
    # the last opened model's units/gravity/material.
    spec = {
        "units": {"length": "m", "mass": "kg", "time": "s", "motion_angle": "rad"},
        "gravity_m_per_s2": [0, 0, 0],
        "bodies": [{"name": "Ground", "fixed": True},
                   {"name": "Link", "center": [.1, 0, 0], "box": [.2, .04, .04], "mass_kg": .25}],
        "joint": {"name": "Hinge", "type": "revolute", "base": "Ground", "action": "Link",
                  "pivot": [0, 0, 0], "axis": [0, 0, 1]},
        "motion": {"joint": "Hinge", "condition": "displacement", "expression": f"{speed:.17g}*TIME"},
        "spring": {"name": "Spring", "base": "Ground", "action": "Link",
                   "base_point": [0, 1, 0], "action_point": [.2, 0, 0],
                   "stiffness_N_per_m": 200, "damping_N_s_per_m": 1,
                   "free_length_m": math.hypot(1, .2), "stiffness_parameter": "ScaledK"},
        "parameters": {"K": 100, "ScaledK": "2*K"},
        "note": "An ideal prescribed motion fixes the trajectory; this check does not validate spring reaction force."
    }
    write_json(folder / "relations.json", spec)
    with RecurDynSession(start=True) as session:
        sdk = session.sdk
        name = "Codex_Hinge_" + datetime.now().strftime("%H%M%S_%f")
        document = session.new_model(name, "MKS")
        root = sdk.ISubSystem(document.Model)
        document.ModelProperty.GravityX = 0
        document.ModelProperty.GravityY = 0
        document.ModelProperty.GravityZ = 0
        body = sdk.IBody(root.CreateBodyBox("Link", frame(document, .1, 0, 0), .2, .04, .04))
        # Uniform box inertia about its centre, aligned with its body frame.
        body.MaterialInput = sdk.MaterialInput.UserInput
        body.Mass.Value = .25
        body.Ixx.Value = .25 * (.04**2 + .04**2) / 12
        body.Iyy.Value = .25 * (.2**2 + .04**2) / 12
        body.Izz.Value = .25 * (.2**2 + .04**2) / 12
        body.Ixy.Value = body.Izx.Value = body.Iyz.Value = 0
        joint = sdk.IJointRevolute(root.CreateJointRevolute(
            "Hinge", root.Ground, body, frame(document, 0, 0, 0)))
        expression = root.CreateExpression("DriveAngle", spec["motion"]["expression"])
        joint.Motion.Type = sdk.MotionType.Standard
        joint.Motion.Condition = sdk.MotionCondition.MotionCondition_Displacement
        joint.Motion.Expression = expression
        joint.UseMotion = True
        root.CreateParametricValue("K", 100)
        scaled = root.CreateParametricValueWithText("ScaledK", "2*K")
        spring = sdk.IForceSpring(root.CreateForceSpring(
            "Spring", root.Ground, body, frame(document, 0, 1, 0), frame(document, .2, 0, 0)))
        spring.Stiffness.Coefficient.ParametricValue = scaled
        spring.Stiffness.UseSpline = False
        spring.Stiffness.UseExponentValue = False
        spring.Damping.Coefficient.Value = 1
        spring.Damping.UseSpline = False
        spring.Damping.UseExponentValue = False
        spring.FreeLength.Value = spec["spring"]["free_length_m"]
        spring.Preload.Value = 0
        spring.SpringGraphic.SpringDiameter.Value = .02
        spring.SpringGraphic.UseCoilRadius = True
        spring.SpringGraphic.CoilRadius.Value = .001
        spring.SpringGraphic.NCoil = 5
        session.commit(document)
        if not math.isclose(body.Mass.Value, .25) or not math.isclose(body.Izz.Value, .25 * (.2**2 + .04**2) / 12):
            raise RuntimeError("User mass/inertia was replaced by automatic material properties")
        document.Fit()
        saved = session.save(document, folder / "mechanism.rdyn")
        bundle = output_path(folder / "bundle")
        bundle.mkdir()
        document.FileExport(str(bundle / "mechanism.rdx"), False)
        index = parse_bundle(bundle / "mechanism.rdx")
        index_file = write_json(folder / "index.json", index)
        indexed_joint = select_entity(index, "Hinge")
        indexed_spring = select_entity(index, "Spring")
        for entity in (indexed_joint, indexed_spring):
            ends = connection(index, entity)
            if ends["BaseMarker"]["body"] != root.Ground.FullName or ends["ActionMarker"]["body"] != body.FullName:
                raise RuntimeError("Saved connector endpoints differ from the relationship specification")
        stiffness = query(index, "Spring", ["stiffness"])["fields"]["stiffness"]["value"]
        mass = query(index, "Link", ["mass"])["fields"]["mass"]["value"]
        motions = summary(index)["motions"]
        if not math.isclose(mass, .25) or not math.isclose(stiffness, 200) or not joint.UseMotion or joint.Motion.Expression.FullName != expression.FullName:
            raise RuntimeError("Parameter binding or prescribed motion readback failed")
        if not any(motion["owner_id"] == indexed_joint["id"] and motion["enabled"] is True
                   and motion["expression_id"] == select_entity(index, "DriveAngle")["id"] for motion in motions):
            raise RuntimeError("Exported motion does not reference the requested expression")
        report = {"status": "passed", "model": str(saved), "index": str(index_file),
                  "relations": str(folder / "relations.json"),
                  "structure_check": {"connector_endpoints": "passed", "motion_expression_reference": "passed",
                                      "effective_stiffness_N_per_m": stiffness, "mass_kg": body.Mass.Value},
                  "simulation": None, "physics_check": None}
        if not build_only:
            result = session.simulate(document, end_time=end_time, steps=steps, output_prefix=folder / "simulation")
            plot = session.open_plot(result["rplt"])
            names = session.channels(plot)
            write_json(folder / "channels.json", names)
            time_name = next(item for item in names if item.upper() == "TIME" or item.upper().endswith("/TIME"))
            x_name = next(item for item in names if item.endswith("/Link/Pos_TX"))
            y_name = next(item for item in names if item.endswith("/Link/Pos_TY"))
            times, xs, ys = [list(plot.GetPlotDataFromIndex(0, item)) for item in (time_name, x_name, y_name)]
            # Translation avoids assuming the plot database's rotation display unit.
            expected = [(.1 * math.cos(speed * t), .1 * math.sin(speed * t)) for t in times]
            error = max(math.hypot(x - ex, y - ey) for x, y, (ex, ey) in zip(xs, ys, expected))
            complete = len(times) == len(xs) == len(ys) == steps + 1
            report.update(simulation=result, export=session.export_csv(
                plot, [time_name, x_name, y_name], folder / "trajectory.csv"),
                physics_check={"complete": complete, "equation": "x=.1*cos(speed*t), y=.1*sin(speed*t)",
                               "speed_rad_per_s": speed, "max_position_error_m": error, "tolerance_m": 1e-6,
                               "scope": "Prescribed kinematics only; spring force is not independently checked"})
            if not complete or not math.isfinite(error) or error > 1e-6:
                report["status"] = "failed"
        write_json(folder / "verification.json", report)
        if report["status"] != "passed":
            raise RuntimeError(f"Driven-link trajectory verification failed: {report['physics_check']}")
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--speed", type=float, default=.2, help="Prescribed angular speed in rad/s")
    parser.add_argument("--end-time", type=float, default=.2)
    parser.add_argument("--steps", type=int, default=20)
    args = parser.parse_args()
    print(json.dumps(build_and_check(args.output, build_only=args.build_only, speed=args.speed,
                                    end_time=args.end_time, steps=args.steps), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
