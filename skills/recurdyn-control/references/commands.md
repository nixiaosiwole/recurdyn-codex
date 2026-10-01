# Command recipes

Use PowerShell in the toolkit root. `--start` is a global argument placed before the command; output paths are relative to the toolkit root and new output folders must not already exist.

```powershell
.\initialize.ps1 -PythonExecutable 'C:\envs\recurdyn\python.exe' -RecurDynInstallDir 'C:\Program Files\FunctionBay, Inc\RecurDyn 2024' -ExtractProcessNet
.\rd.ps1 doctor
.\rd.ps1 start
.\rd.ps1 status
.\rd.ps1 --start scan 'C:\Models\mechanism.rdyn' --output runs\scan_001
.\rd.ps1 query runs\scan_001\index.json --limit 20
.\rd.ps1 query runs\scan_001\index.json --entity 'entity ID from catalog' --field connections --graph
.\rd.ps1 query runs\scan_001\index.json --entity 'body ID from catalog' --field mass --field global_frame --api-missing
.\rd.ps1 template runs\scan_001\index.json --output runs\template_001
.\rd.ps1 --start instantiate runs\template_001\template.json --output runs\instance_001 --parameters examples\my_parameters.json
.\rd.ps1 --start job examples\my_job.json
.\rd.ps1 channels 'runs\job_001\model_01\simulation.rplt'
.\rd.ps1 export 'actual result path returned by job' --channel 'actual channel name' --output runs\selected_results.csv
.\rd.ps1 api ISubSystem CreateJointRevolute
.\rd.ps1 api-search CreateForceSpring --limit 5
.\rd.ps1 api MaterialInput UserInput
.\rd.ps1 api IControlCoSim HostProgram --module Control
.\rd.ps1 docs-paths
.\rd.ps1 docs-extract
.\rd.ps1 docs-search JointRevolute --source processnet --examples-only --limit 5
.\rd.ps1 docs-read Python/CoreExample/Methods/CoreExample_IJointRevolute.html
.\rd.ps1 docs-read ProcessNetTemplate.py --source python
.\rd.ps1 run-script examples/modeling/hinge_motion_spring.py --output runs/hinge_001
.\rd.ps1 demo --output runs\demo_001
```

Replace illustrative paths and selectors; IDs belong to each snapshot. `scan` with a complete RDX source is offline. Query/template/API/document lookup do not need COM unless supplementation is requested. `docs-extract` uses Windows HTML Help; installation files stay read-only. CHM/SDK are read from the local installation, not bundled.

Documentation configuration keys: `documentation.recurdyn_help_index`, `processnet_chm`, `examples_root`, `processnet_html_dir`. They default to the selected installation's Help files and toolkit `.reference/processnet`. `docs-search --source` accepts processnet/usage/examples/python/all; default searches paths, `--text` searches HTML/code contents. `docs-read` preserves Python in `code_blocks`, exposes truncation and accepts `--offset` / `--max-chars`. PDF matches only locate files.

`docs-extract` reuses a verified CHM hash/page-count cache. If an existing directory lacks metadata or is incomplete, use `--output .reference/processnet_new` and configure `processnet_html_dir` to that location; it never overwrites an unverified cache.

`run-script` takes an existing .py inside the toolkit, then passes remaining arguments to it. It selects the configured Python; each script manages its own RecurDyn session/start and verification. Read [model-building.md](model-building.md) for new models described as mechanical relationships.

Query fields: an exact property path, or `connections`, `mass`, `value`, `local_frame`, `stiffness`, `damping`, `free_length`. API fields: global frames for Body/Marker/SubSystem, Body mass, PV value/text and Expression text. Missing unsupported fields remain explicitly missing. `--entity document` accesses `MODEL/...` and `SETTINGS/...` properties.

Numeric instance parameters JSON:

```json
{"Speed@MyModel": 20.0}
```

Job JSON:

```json
{
  "model": "C:\\Models\\mechanism.rdyn",
  "output_dir": "runs/job_001",
  "parameters": {"Speed@MyModel": 20.0},
  "end_time": 1.0,
  "steps": 100,
  "channels": []
}
```

The relative model path is resolved against the job JSON file, while output_dir is relative to the toolkit. Empty channels runs the solver and saves channels.json; discover exact channel names and export afterwards. Runtime/physical validity can depend on model-specific options; this job interface configures duration/steps and numeric PV values, not every solver setting.
