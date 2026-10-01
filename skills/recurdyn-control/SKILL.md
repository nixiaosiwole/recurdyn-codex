---
name: recurdyn-control
description: Automate RecurDyn through its installed Python SDK and this local toolkit. Read RDYN/RDX structure, reuse templates, simulate/export, and write new modeling scripts from body/joint/force relationships using local help and runnable examples.
---

# RecurDyn control

Use the toolkit's `rd.ps1` and official ProcessNet Python SDK. Use the toolkit directory explicitly provided by the user; otherwise locate `rd.ps1`, `recurdyn_control/` and `recurdyn-config.json` in the opened workspace (possibly under `train/`). Do not assume another person's installation or Python paths. If the toolkit is absent, explain that installing this skill alone does not install its Python tools.

## Choose the existing operation

| Request | Route |
|---|---|
| Environment/setup | `initialize.ps1`, then `doctor` |
| Start/connect or open-model status | `start`, `status` |
| Saved-model structure, connections, Motion/Force, PV dependencies | `scan`, then targeted `query` |
| Missing evaluated PV values or global frames | `query --field ... --api-missing` |
| Create a variant of an existing model | `template`, then `instantiate` |
| Change numeric PVs, simulate and optionally export | Write a JSON job, then `job` |
| Discover/export result channels | `channels`, then `export` |
| Demonstrate end-to-end control | `demo`, checks analytic free fall |
| Locate SDK, manuals and official Python examples | `docs-paths`, `docs-extract`, `api-search`, `docs-search`, `docs-read` |
| Build from described body/joint/force relationships | Read model-building reference, resolve specification, verify installed API/examples, write Python, then `run-script` |

Read [references/commands.md](references/commands.md) for command syntax and JSON schema when invoking a route. Model-specific contact, flexibility, CAD import, optimization and solver-step coupling are extensions rather than verified turnkey operations.

For new-model requests, read [references/model-building.md](references/model-building.md). It connects described relationships to installed SDK/help lookup, own executed Python examples and structural/physical verification.

## Runtime and output

- Run commands with the toolkit root as working directory. Its launcher selects the configured Python directly. Baseline verified on Windows 64-bit Python 3.10.13, pywin32 and RecurDyn 2024 / ProcessNet 10.2.45533.2024; check other versions locally.
- If unconfigured, inspect local Python/conda candidates and RecurDyn paths. `initialize.ps1` can detect a unique suitable installation/environment and configure help paths; supply explicit paths if ambiguous. `-ExtractProcessNet` extracts a local CHM copy into toolkit HTML. It does not install Python, packages or software.
- Run `doctor`. A sandbox COM-registration failure does not establish a broken installation. Use an authorized Windows host execution context for actual COM operations; preserve the execution permissions of that Codex session.
- Do not modify installation/Help files. Stage model changes in a new toolkit `runs/` directory. Preserve the source model. Match numbers to model units and disambiguate same-named objects using IDs/full names/paths.
- Use existing tool operations first. For new scripts, `from recurdyn_control import RecurDynSession`; call SDK methods through `session.sdk` and COM on the same thread. Verify signatures, property types and enum names with `api`/`api-search`, semantics/examples with local help. Use `run-script` for inspected/generated toolkit Python.

## Read models efficiently

- Prefer the saved file's complete RDX bundle and indexed queries. `scan` returns `index.json`; keep the full index/XML local and return summaries or selected fields. Never send the thumbnail/XML dump as the default.
- RDX export has `.rdx`, `.data`, `.hier` and geometry companions. Let the toolkit copy/verify the bundle. A lone `.rdx` is insufficient for this 2024 format.
- `local_frame` retains stored coordinates and reference properties; it is not a global transformation. Request `global_origin`/`global_frame` when that distinction matters.
- Preserve field provenance (`rdx`, `rdx_arithmetic`, `api`, `missing`). API supplementation is limited to adapted fields. Do not invent values for unknown formulas/types.
- Use valid cache snapshots; changed source files/companions require a fresh scan. A source model's unsaved UI edits are outside the saved-file snapshot.

## Modify and verify

- `instantiate` copies the complete template, changes exposed numeric PVs and checks hierarchy, references, unmodified formulas and saved parameter values. Default template parameters exclude referenced formulas; explicitly selecting a dependent PV replaces its own formula when set numerically.
- `job` stages a copy before editing. It runs synchronous dynamic analysis. Result-channel names must come from `channels`/the real plot database, rather than guesses.
- Accept simulation completion only when a new result exists and its actual time channel reaches the requested end time. Inspect values and run an appropriate physical check when a reference solution is available. Report model validity separately from solver completion.
- For parameter sweeps, create distinct job outputs and run sequentially; there is no built-in optimizer or parallel-solver scheduler.
- If external CAD/flexible data/DLLs/toolkits are referenced, preserve/report them and verify the concrete model; do not promise a self-contained template solely from copying the RDX bundle.
