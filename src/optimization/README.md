# Optimization subsystem

This is the canonical extension contract for deterministic, reviewable score
optimization.

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

Capability names are negotiated against the host-owned allowlist before code
is imported. Unknown or duplicate capabilities disable the bundle. The
negotiated set is exposed through `PluginEnvironment`; it is a compatibility
contract, not a sandbox or permission bypass.

Imported projects can already contain an out-of-map pitch, unsupported manual
articulation, or pre-normalization drum encoding. API v1 treats those values as
bounded source debt: an optimizer may preserve their pitch/type multiset while
cleaning timing or velocity, but may not add another incompatible value. A
track-instrument change and every derived track are validated strictly. The UI
reports preserved source debt and sends it to Conversion Check instead of
misreporting it as an optimizer-package failure.

Packages are copied to `%LOCALAPPDATA%\BDO Music Composer\optimizer_plugins`.
`BDO_OPTIMIZER_DIR` and `BDO_OPTIMIZER_CACHE` are available for development and
tests. Discovery reads manifests only. Code is imported lazily from a SHA-256
isolated cache when analysis begins. Packages are trusted local code; the host
does not install dependencies or provide a sandbox. Non-trusted future
extensions must use the bounded `ndjson-stdio` process contract instead of this
in-process loader.

## Compatibility registry

Existing callers may continue using `register_algorithm()` and
`optimize_tracks(..., algorithm=...)`. New distributable algorithms should use
optimizer API v1 and `.bdoopt` instead.
