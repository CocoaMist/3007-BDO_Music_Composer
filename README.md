# BDO Music Composer

Current release candidate: **v0.3.0**

<p align="center">
  <img src="assets/icons/app_icon.png" width="160" alt="BDO Music Composer icon">
</p>

An unofficial Windows desktop workstation for arranging MIDI, editing notes, previewing user-supplied game samples, and exporting Black Desert Online v9 music scores.

中文简介：这是一个面向《黑色沙漠》作曲系统的本地 MIDI 编排工作站。从标准 MIDI 导入开始，可以在时间轴与钢琴卷帘中继续编辑音符、分配 BDO 乐器、调整奏法与力度、使用自己合法准备的音源包进行近似试听，最后从当前编辑模型导出 BDO v9 曲谱。

> [!IMPORTANT]
> This is an independent community project. It is not affiliated with, endorsed by, or supported by Pearl Abyss. No game assets are distributed in this repository. Users must supply their own legally obtained game files and audio extracts.

## 项目概览

BDO Music Composer 适合希望把已有 MIDI 整理为游戏曲谱、继续手工编排，或研究 BDO 乐器映射与奏法的玩家。所有工程、Owner ID、音源、自动保存和导出文件都留在本地；程序没有账号系统、遥测或上传功能。

```text
MIDI 导入 → 轨道与乐器映射 → 钢琴卷帘编辑 → 安全优化/试听 → 转换检查 → BDO v9 导出
```

## 功能实现

### MIDI 导入与工程管理

- 读取标准 MIDI 文件，解析轨道、速度、BPM、拍号、tempo 变化、踏板控制和歌词事件。
- 在可缩放时间轴中查看全部轨道，并支持静音、独奏、音量、乐器分配和播放位置控制。
- 自动保存当前工程，保留轨道映射、编辑后的音符、奏法、力度策略和导出设置。

### 音符编辑

- 提供钢琴卷帘编辑器，可新建、删除、移动和缩放音符。
- 支持多选、框选、复制、剪切、粘贴、撤销、重做和量化吸附。
- 绘制模式可在一次拖动中设置音符长度与初始力度；支持点击琴键试听、Alt 临时取消吸附、方向键微调和 `Ctrl+D` 复制。
- 可修改音高、起始时间、时值、力度及 BDO `ntype` 奏法。
- 手工编辑直接写回当前工程模型，导出时不会重新读取原始 MIDI 覆盖修改。

### MIDI 优化

- 支持单轨优化和全局优化，并读取完整歌曲的和声、节奏、配器及歌词上下文。
- 游戏安全模式保持音符数量、音高集合、轨道和乐器映射，不擅自新增或删除音符。
- 可处理力度平衡、轻微时序、软量化、音块修复和保守奏法建议。
- 优化结果可预览、查看报告并选择是否应用。

### BDO 乐器与奏法

- 将 MIDI 轨道映射到支持的《黑色沙漠》乐器。
- 支持轨道级和音符级奏法，并在导出时保存 `ntype`。
- 支持玛勒尼斯乐器的 Basic、Stereo、Super 和 Super Octave 音源模式。
- 转换检查会提示音域越界、未知打击乐映射、无效 FX、轨道合并和容量问题。

### 游戏音源试听

- 使用用户自行提取的 Wwise WAV 样本进行低延迟实时试听。
- 样本在播放前预载和解码，实时音频回调不读取磁盘文件。
- 支持精确事件帧调度、播放定位、有界声部池和输出限幅。
- 未经游戏内 A/B 验证的 DSP 和奏法会明确标记为近似效果。

### BDO v9 曲谱导出

- 从当前编辑器模型生成 BDO v9 曲谱，保留新增、删除、移动、缩放和奏法修改。
- 支持 Owner ID、角色名、BPM、移调、力度策略和游戏效果参数。
- 按每轨 730 个音符自动拆分，并生成每种乐器要求的空结尾轨道。
- 输出采用 BDO v9 二进制结构和 ICE 加密；非 `/4` 拍号会明确拒绝，不会静默错误导出。

### 界面与发布

- 界面支持简体中文、英语、日语和韩语。
- 可选择根据系统时区自动切换语言，也可以手动固定语言。
- 支持使用 PyInstaller 构建便携式 Windows 单文件程序。
- 软件不包含联网、遥测、账号登录或文件上传功能；MIDI、Owner ID、音源和导出文件均在本地处理。

### Optimizer packages

The optimization panel exposes algorithm, conservative/balanced/deep intensity,
track scope, explicit analysis, and preview application. Trusted local
algorithms can be distributed as one `.bdoopt` file; use the panel's algorithm
package button to open the install directory, copy the file there, and refresh.

### Lossless BDO v9 codec

The independent `bdo_codec` package can inspect and byte-for-byte round-trip an
unchanged v9 score, or canonically encode an edited document. It preserves both
velocity bytes, physical tracks, game track volume, eight settings bytes, and
opaque data with a fail-closed safety policy. See
[BDO v9 codec](docs/BDO_V9_CODEC.md) for its Python API, CLI, and private
in-game evidence workflow.

## Current status and limitations

- The editor and BDO v9 serialization path are functional and covered by automated tests.
- The project is intentionally developed as a small BDO score laboratory for the maintainer and friends, not as a general DAW or commercial product.
- Conversion checks use a versioned, evidence-labelled game profile; issues can locate affected tracks/notes and destructive export changes are blocked.
- Exported BDO v9 files are structurally read back, and any two local scores can be compared without exposing private fields by default.
- In-game edit permission requires an Owner ID copied from a score saved by your own account.
- BDO v9 stores a `/4` meter representation; non-`/4` MIDI files are rejected instead of silently converted incorrectly.
- Wwise preview requires local extracted WAV files. Preview routing and some DSP-heavy articulations are approximate until verified by in-game A/B testing.
- Marnian source modes use the reserved contiguous instrument IDs documented in the code and tests.
- Original project code is available under the MIT License.
- MIDI import, MIDI-to-BDO adaptation, BDO v9 serialization, and ICE are maintained as independent project code under `bdo_midi/`, `bdo_export/`, and `bdo_codec/`.

## Quick start from source

Requirements: Windows, Python 3.12 recommended, and a working audio device for preview.

```powershell
git clone <your-repository-url>
cd BDO_Music_Composer
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-pyside.txt
.\.venv\Scripts\python.exe main.py
```

The GUI can import and edit MIDI without game audio. Configure extracted audio paths in the application before using real-time preview.

### Local sample packs

The application settings accept one user-created `.bdosamples` archive. A pack is a ZIP-compatible local container with a versioned manifest and SHA-256 verification. It is extracted to `sample_cache/` before playback, so the real-time callback never reads compressed files. Developers may still use `BDO_AUDIO_ROOT` for an unpacked local WAV tree.

Create a pack only from audio you are legally entitled to use:

```powershell
.\.venv\Scripts\python.exe -m bdo_sample_pack "D:\your-audio-root" "D:\private\my-samples.bdosamples"
```

`.bdosamples` files and extracted caches are ignored by Git. Do not upload them to this repository or attach them to a Release. The program has no sample-pack sharing or upload feature.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -m py_compile main.py project_paths.py pyside_bdo_gui.py i18n.py
```

The test suite covers optimizer safety, real-time audio behavior, export round trips, BDO v9 structure, Marnian mode IDs, and localization catalogs.

## Build the Windows executable

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

Output: `dist\BDO-Music-Composer.exe`.

The executable embeds the application icon, UI background, and the runtime MIDI/Wwise zone map. It does **not** embed extracted game audio, personal settings, Owner IDs, autosaves, or exported scores.

## Architecture at a glance

```mermaid
flowchart LR
    MIDI["MIDI file"] --> Parse["mido parser"]
    Parse --> Model["TrackState + Note model"]
    Model --> UI["PySide6 timeline / piano roll"]
    Model --> Optimize["Safe optimizer + theory context"]
    Optimize --> Model
    Model --> Preview["Real-time Wwise sample preview"]
    Model --> Export["BDO v9 serializer + ICE encryption"]
    Export --> Score["Game music score"]
```

Primary entry points:

- `main.py` — unified application entry point.
- `pyside_bdo_gui.py` — desktop UI, editor state, export orchestration, and autosave.
- `optimization/` — extensible optimization package, built-in pipeline, and algorithm registry.
- `bdo_midi_optimizer.py` — backward-compatible facade for older integrations.
- `bdo_midi/` — independent MIDI parser, immutable note model, instrument maps, and transforms.
- `bdo_export/` — current-editor/MIDI adaptation into canonical BDO v9 documents.
- `bdo_realtime_audio.py` — low-latency sample preview engine.
- `bdo_codec/` — independent BDO v9 lossless codec, validation, and CLI.
- `i18n.py` — runtime localization catalogs.

See [Architecture](docs/ARCHITECTURE.md), [AI Context](docs/AI_CONTEXT.md), and [Project Structure](docs/PROJECT_STRUCTURE.md) for deeper documentation.
The v0.3.0 clean-room boundary and validation gates are recorded in
[Independent MIDI-to-BDO implementation](docs/INDEPENDENT_MIDI_IMPLEMENTATION.md).

## Repository hygiene and privacy

The following must never be committed:

- `.pyside_bdo_gui.json`, `auto_save/`, `out/`, `build/`, and `dist/`;
- game scores containing a real Owner ID or character name;
- extracted PAZ, BNK, WEM, or WAV assets;
- local absolute paths, API keys, crash logs, and generated release archives.

Run this before publishing:

```powershell
git status --short
git ls-files out auto_save dist build
git grep -n -I -E "(C:\\Users\\|OPENAI_API_KEY|api[_-]?key|password)"
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

## Attribution

- [mido](https://mido.readthedocs.io/) for Standard MIDI parsing and writing.
- Historical community research, including Bishop-R's `midi-to-bdo`, which informed early project exploration; v0.3.0 contains no runtime or vendored source from that repository.
- iDevelopThings' [`bdo-data-extractor`](https://github.com/iDevelopThings/bdo-data-extractor) for the clear read-only PAZ, ICE, and LZ implementation used by the separate local sample-pack development tool.
- Players from **CN Server · Rainbow Club / 彩虹乐队** for their support, testing, and music exchange.
- Community research around Black Desert music-score files, instrument IDs, and game UI behavior.
- PySide6 / Qt and NumPy for the desktop and audio runtime.

Before public release, inspect the source archive and executable to confirm that
historical vendor modules and private/generated artifacts are absent.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). AI coding agents must read [AGENTS.md](AGENTS.md) before changing code.

## License

Original project code owned by CocoaMist is licensed under the [MIT License](LICENSE).

Third-party and vendored components retain their own license terms. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md); the root license does not claim ownership of or relicense upstream work.
