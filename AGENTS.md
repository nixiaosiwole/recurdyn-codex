# RecurDyn automation workspace

- When the user requests RecurDyn model reading, new modeling from described relationships, template reuse, parameter changes, simulation or result export, read `skills/recurdyn-control/SKILL.md` and use this workspace's Python toolkit. This local file route works without globally installing the skill.
- Use this opened folder as the toolkit root. All generated code/configuration/cache/results stay here; simulation/model variants go in new `runs/` folders. RecurDyn installation/Help files are read-only.
- Configure local paths using `initialize.ps1`, then run `rd.ps1 doctor`. Do not copy the original author's Python/conda paths or assume their environment name exists.
- For new modeling, read the skill's `references/model-building.md`, inspect the relevant `examples/modeling/` script, and query installed API/help before generating code. `docs-paths` locates `Bin/Python`, manuals and official examples; `initialize.ps1 -ExtractProcessNet` prepares searchable CHM HTML. Essential geometry, units, axes and loads come from the task specification.
- Use official ProcessNet Python, RDX indexing and targeted queries. Do not use mouse/keyboard automation for operations already covered by these tools.
- Preserve source models by staging copies. Follow the user's scope and this Codex session's execution permissions for host COM operations. A sandbox error alone is not grounds for changing registry or reinstalling RecurDyn.
- Before creating/editing/overwriting/moving/deleting any `.tex` file, ask the user and wait for confirmation.
