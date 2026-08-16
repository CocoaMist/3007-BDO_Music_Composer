# Marnian Muse：只通过扩展包见面

Marnian Muse 是独立的无界面引擎，只以标准 `.bdoopt` 包接入。Music Composer 管
API v1、发现、校验、预览应用和 BDO 约束；算法、数据、报告、音频参考和模型权重
仍归独立项目。

The standalone project builds the package with:

```powershell
marnian-build-bdoopt path\to\marnian-muse.bdoopt
```

The generated archive contains the runtime engine, default profile, package
entry adapter, and README. It must not contain corpus MIDI, downloaded audio,
research reports, local paths, or training data.

Copy the archive to the directory opened by the optimizer panel's
`算法包目录` button. Discovery reads only `manifest.json`; engine code is
extracted and imported only after the user selects Marnian Muse and explicitly
starts analysis. Its manifest requests the built-in game-safe prepass and
global scope. All preview changes are validated and applied by the host.

Removing the `.bdoopt` file removes Marnian Muse from the next refreshed
algorithm list without affecting Music Composer's built-in safe optimizer.
