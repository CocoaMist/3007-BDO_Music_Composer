# Optimization subsystem

`builtin.py` owns the BDO-safe production optimizer. `plugin_api.py` defines
optimizer API v1, `plugin_loader.py` discovers `.bdoopt` packages without
executing them, and `plugin_host.py` presents built-in and external algorithms
through one preview/apply workflow. `registry.py` remains the compatibility
registry for older in-process integrations.

## `.bdoopt` package

A package is a ZIP archive with this layout:

```text
manifest.json
payload/
  entry.py
resources/       # optional
models/          # optional
README.md        # optional
```

The schema-1 manifest declares `plugin_id`, `version`, `display_name`,
`description`, `api_version`, `entrypoint`, all three intensities, supported
scopes, capabilities, and `requires_safe_prepass`. The entrypoint uses
`module:function` syntax and returns an object implementing:

```python
class Plugin:
    def analyse(self, request, environment):
        return OptimizationPreview(...)
```

The request contains immutable track/note snapshots, the valid BDO instrument
set, and host limits. Oversized songs are rejected before plugin code runs.
Plugins return structured operations; they never receive the mutable editor
model and never commit edits. The host validates source fingerprints, target
scope, note wire values, supported BDO pitches, canonical drum routing,
derived-track budgets, and the single global-effect-write rule.

Packages are copied to `%LOCALAPPDATA%\BDO Music Composer\optimizer_plugins`.
`BDO_OPTIMIZER_DIR` and `BDO_OPTIMIZER_CACHE` are available for development and
tests. Discovery reads manifests only. Code is imported lazily from a SHA-256
isolated cache when analysis begins. Packages are trusted local code; the host
does not install dependencies or provide a sandbox.

## Compatibility registry

Existing callers may continue using `register_algorithm()` and
`optimize_tracks(..., algorithm=...)`. New distributable algorithms should use
optimizer API v1 and `.bdoopt` instead.
