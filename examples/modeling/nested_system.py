"""Own build-only MKS example: root fixed body and a local revolute in Stage.

Stage's placement is (2,0,0) in the root. Link and its joint are created at
(.3,0,0) in Stage coordinates, so their global origin should be (2.3,0,0).
Stage.Ground is the base body inside Stage; no cross-subsystem joint is assumed.
"""
import argparse
from datetime import datetime
import json
import math

from recurdyn_control import RecurDynSession
from recurdyn_control.rdx import connection, parse_bundle, select_entity
from recurdyn_control.runtime import output_path, write_json


def frame(document, xyz):
    result = document.CreateReferenceFrame()
    result.SetOrigin(*xyz)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    folder = output_path(args.output)
    folder.mkdir(parents=True, exist_ok=False)
    with RecurDynSession(start=True) as session:
        sdk = session.sdk
        document = session.new_model("Codex_Nested_" + datetime.now().strftime("%H%M%S_%f"), "MKS")
        root = sdk.ISubSystem(document.Model)
        document.ModelProperty.GravityX = document.ModelProperty.GravityY = document.ModelProperty.GravityZ = 0
        anchor = sdk.IBody(root.CreateBodyBox("Anchor", frame(document, (0, 0, 0)), .1, .1, .1))
        root.CreateJointFixed("AnchorFixed", root.Ground, anchor, frame(document, (0, 0, 0)))
        stage = sdk.ISubSystem(root.CreateSubSystem(sdk.SubSystemType.General, "Stage", frame(document, (2, 0, 0))))
        link = sdk.IBody(stage.CreateBodyBox("Link", frame(document, (.3, 0, 0)), .2, .04, .04))
        joint = sdk.IJointRevolute(stage.CreateJointRevolute(
            "Hinge", stage.Ground, link, frame(document, (.3, 0, 0))))
        session.commit(document)
        document.Fit()
        saved = session.save(document, folder / "nested.rdyn")
        global_body = list(link.RefFrame.AtModel().GetOrigin())
        global_marker = list(joint.ActionMarker.RefFrame.AtModel().GetOrigin())
        expected = [2.3, 0, 0]
        if any(not math.isclose(a, b, abs_tol=1e-10) for values in (global_body, global_marker) for a, b in zip(values, expected)):
            raise RuntimeError(f"Subsystem placement was incorrectly applied: {global_body}, {global_marker}")
        bundle = output_path(folder / "bundle")
        bundle.mkdir()
        document.FileExport(str(bundle / "nested.rdx"), False)
        index = parse_bundle(bundle / "nested.rdx")
        index_file = write_json(folder / "index.json", index)
        endpoints = connection(index, select_entity(index, joint.FullName))
        if endpoints["BaseMarker"]["body"] != stage.Ground.FullName or endpoints["ActionMarker"]["body"] != link.FullName:
            raise RuntimeError("Nested connector ownership readback failed")
        report = {"status": "passed", "model": str(saved), "index": str(index_file),
                  "build_only": True, "simulation": None,
                  "coordinates": {"stage_in_root_m": [2, 0, 0], "link_in_stage_m": [.3, 0, 0],
                                  "expected_global_m": expected, "actual_body_global_m": global_body,
                                  "actual_joint_marker_global_m": global_marker},
                  "connections": endpoints,
                  "note": "This verifies hierarchy and frames, not dynamic behavior or cross-subsystem connections."}
        write_json(folder / "verification.json", report)
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
