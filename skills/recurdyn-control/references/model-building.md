# Build a model from the user's relationships

Use this route when the user describes bodies/joints/forces and expects Codex to write Python. The toolkit supplies installed-document lookup and executed examples; it does not contain a universal natural-language or JSON model compiler.

## Establish the mechanical specification

Turn the description into a compact entity/relationship table or a JSON specification under the toolkit. The example at `examples/modeling/relations.spec.json` shows useful fields. Identify:

- Unit system; gravity; geometry, initial placement, mass, centre of mass and inertia for each body.
- Joint type, base/action bodies, pivot/markers, axis, coordinate reference and remaining degrees of freedom.
- Motion displacement/velocity/acceleration, expression, angle units and initial conditions.
- Force attachment points, reference frame, force law, stiffness/damping/free length/preload and parameter dependencies.
- Subsystem ownership, external assets, simulation duration/output and verification criteria.

Ask for missing information that changes the requested behavior. Start independent documentation lookup while waiting. For a conceptual demonstration, use clearly stated example assumptions; for the user's engineering model, do not silently assign dimensions, units, load laws or cross-subsystem connections. If the user requests construction only, do not infer a simulation request.

## Locate authoritative code and help

Run `docs-paths` first. The actual Python API comes from the installation's `Bin/Python/Lib/recurdyn/*.py`; `Bin/Python/ProcessNetTemplate.py` is the official entry template. `ProcessNetHelp.chm` documents interfaces and contains Python `CoreExample` pages. The general usage help and installed case/PDF folders provide modeling context.

If help paths are absent, run `initialize.ps1` with the recipient's paths and `-ExtractProcessNet`. It records usage HTML, CHM, examples root and workspace HTML cache. It stages a CHM copy and extracts into this toolkit; installation files remain read-only. SDK lookup works without CHM extraction. Report a missing CHM when its semantics/examples are needed.

Use focused queries rather than importing a whole manual:

```powershell
.\rd.ps1 docs-paths
.\rd.ps1 api-search CreateJointRevolute --limit 5
.\rd.ps1 api ISubSystem CreateJointRevolute
.\rd.ps1 api IJointRevolute Motion
.\rd.ps1 api IMotion Condition
.\rd.ps1 api MotionCondition
.\rd.ps1 docs-search JointRevolute --source processnet --examples-only --limit 5
.\rd.ps1 docs-read Python/CoreExample/Methods/CoreExample_IJointRevolute.html
.\rd.ps1 docs-read ProcessNetTemplate.py --source python --max-chars 8000
.\rd.ps1 docs-search "revolute" --source usage --text --limit 5
```

Use returned paths for subsequent reads. `code_blocks` preserves original Python indentation; page text is condensed prose. Code blocks may be excerpts relying on `model_document` and `model`, not standalone programs. Official example dimensions do not establish a new model's units.

`api`/`api-search` inspect all installed SDK modules; `--module Control`, `--module Flexible`, etc. narrows lookup. Methods include signatures/docstrings; properties include documented types; enumerations include real member names/values. For example, this 2024 SDK uses `IBody.Izx`, `IForceSpring.SpringGraphic`, `MotionType.Standard`, and `MaterialInput.UserInput`. Do not generalize these to an unchecked version.

`docs-search --text` reads HTML/code and costs more time. General-help filenames are often cryptic, so content search can be necessary. PDF hits identify files; this command does not parse PDF content. Use an available PDF reader separately, preserving source files.

## Adapt executed examples and run code

Read only the relevant example:

| Example | What it demonstrates | Verification scope |
|---|---|---|
| `examples/modeling/hinge_motion_spring.py` | MKS, explicit mass/inertia, Ground-to-Link revolute, prescribed displacement, spring/damper and dependent PV | Saved connections/motion/PV; actual solver time; analytic translation trajectory |
| `examples/modeling/nested_system.py` | Root fixed body, translated Stage, local body/joint creation, typed API frame readback | Hierarchy, nested endpoints, global coordinates; build only |
| `rd.ps1 demo` / `recurdyn_control/demo.py` | Free-fall build/analysis/export | Analytic free-fall position |

Write new scripts in toolkit-owned `scripts/` or a new `runs/` folder. Use `RecurDynSession` and `session.sdk`; keep COM on the session thread. Launch through `run-script` to select the configured Python:

```powershell
.\rd.ps1 run-script examples/modeling/hinge_motion_spring.py --output runs/hinge_001
.\rd.ps1 run-script examples/modeling/hinge_motion_spring.py --output runs/hinge_build_001 --build-only
.\rd.ps1 run-script examples/modeling/nested_system.py --output runs/nested_001
.\rd.ps1 run-script scripts/my_mechanism.py --output runs/my_mechanism_001
```

`run-script` is for inspected/generated code; it is an execution convenience, not a sandbox. Scripts must use workspace output helpers and respect user scope. Examples connect/start on their own; the outer CLI `--start` does not alter a script's session.

In the examples, `CreateBodyBox` frames represent placement in the owning subsystem. Frames supplied to connectors represent points in that same subsystem; RecurDyn creates marker-local coordinates accordingly. Stage at root X=2 and Link at Stage X=.3 yield global X=2.3. Read back `AtModel()` for rotated/complex references. A subsystem's `Ground` is a scoped endpoint; do not substitute internal RDX Dummy/MotherBody names or assume cross-subsystem mating is supported.

Set gravity explicitly after creating a new model. With user-defined mass/inertia, set `MaterialInput.UserInput` and verify after commit/export: default material computation may replace values. Geometry, centre of mass and inertia assumptions must match. Check Motion and coefficient mode as well as numeric values; a stored constant is not necessarily active when a spline is enabled.

## Verify the generated result

Run commit/Validate, save a new .rdyn, export the complete RDX bundle and index it. Compare the specification with actual ownership, base/action markers, axes/frames, motion expression references, parameter bindings and saved physical properties. Use selective API readback where RDX cannot establish a global transformation or evaluated value.

When simulation is requested, check actual time, column lengths and finite values, and use a relevant physical reference/invariant. Prescribed motion checks kinematics but cannot independently validate a spring force law. Validate and solver completion do not establish physical correctness for arbitrary mechanisms.

Report the script, model, relationship specification, verification and unverified features. Contact, flexible data, CAD, toolkits and co-simulation need their own installed documentation/assets and checks. State concrete missing API evidence or engineering input rather than inventing interfaces.
