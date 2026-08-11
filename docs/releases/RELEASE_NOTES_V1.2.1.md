# BDO Music Composer v1.2.1

[中文](#中文) | [English](#english)

## 中文

v1.2.1 将试听音源简化为两个明确入口：**内置通用音源**与**音源包**。
音源包可随时重新选择并在本机记忆；切换音源包或样本目录时会正确清理旧缓存，
不再继续播放上一个音源。兼容音源包支持 16-bit 与 24-bit PCM WAV。

### 主要变化

- 设置中仅保留“内置通用音源”和“音源包”两种试听来源。
- 修复切换音源包后仍复用旧解码样本的问题。
- 增加有界的 16-bit、24-bit PCM WAV 解码，文件读取与解码仍在音频回调之外完成。
- 外部音源包缺失或无效时回退到内置试听，不改变工程与乐谱数据。

### 可选 CC0 音源包

独立下载的 `BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`
选取以下 CC0 开放音源中的未改动 WAV 字节：

- [VSCO 2 Community Edition](https://github.com/sgossner/VSCO-2-CE)，
  revision `6dd651d55dde97fd4028699be9d4481f26917891`；
- [Versilian Community Sample Library](https://github.com/sgossner/VCSL)，
  revision `c1ea7bcc3c7309650ab0da9d15c9cd1fbc4a4c7e`；
- [FreePats CC0 instrument banks](https://freepats.zenvoid.org/)。

包内 `manifest.json` 逐槽记录来源、上游相对路径和 SHA-256。它不包含
Black Desert 客户端音频，只用于近似编辑试听，不代表游戏原声或 A/B 验证结果。

### 发行资产与验证

- `BDO-Music-Composer.exe`：`183,154,508` 字节；SHA-256
  `4f616988b9c9648e7b921dc1e1b802fd198a632a17c1c54d6c93b08c6306fc18`。
- `BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`：
  `753,225,838` 字节；SHA-256
  `82cea29f1316b943571663e4150b31e353da4ab9f556141ed65b6598a384db63`。
- 本地完整套件 1,205 项测试通过、1 项跳过；GitHub Windows CI 通过。
- 正式构建的依赖许可清单、冻结 Basic Pitch/CPU 推理和 10 秒 GUI 启动自检通过。
- 音源包 1,465 个清单记录均通过大小与 SHA-256 校验。

本版本未使用 Authenticode 发布者签名，Windows SmartScreen 可能显示“未知发布者”。
本项目是非官方社区工具，与 Pearl Abyss 无隶属关系。

## English

v1.2.1 reduces preview audio to two explicit choices: **Built-in General
Source** and **Sample Pack**. The selected pack can be changed at any time and
is remembered locally. Changing the pack or sample root now invalidates stale
decoded samples instead of continuing to play the previous source. Compatible
packs support 16-bit and 24-bit PCM WAV files.

### Highlights

- Reduced Settings to the Built-in General Source and Sample Pack choices.
- Fixed stale decoded-sample reuse after switching sample packs.
- Added bounded 16-bit and 24-bit PCM WAV decoding while keeping file I/O and
  decoding outside the audio callback.
- Invalid or missing external packs fall back to built-in preview without
  changing project or score data.

### Optional CC0 sample pack

The separately downloadable
`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples` selects unmodified
WAV bytes from these CC0 sources:

- [VSCO 2 Community Edition](https://github.com/sgossner/VSCO-2-CE), revision
  `6dd651d55dde97fd4028699be9d4481f26917891`;
- [Versilian Community Sample Library](https://github.com/sgossner/VCSL),
  revision `c1ea7bcc3c7309650ab0da9d15c9cd1fbc4a4c7e`;
- [FreePats CC0 instrument banks](https://freepats.zenvoid.org/).

The pack's `manifest.json` records the source, upstream relative path, and
SHA-256 for every slot. It contains no Black Desert client audio and provides
approximate editing preview only; it is not game-original or A/B-verified
sound.

### Release assets and verification

- `BDO-Music-Composer.exe`: `183,154,508` bytes; SHA-256
  `4f616988b9c9648e7b921dc1e1b802fd198a632a17c1c54d6c93b08c6306fc18`.
- `BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`:
  `753,225,838` bytes; SHA-256
  `82cea29f1316b943571663e4150b31e353da4ab9f556141ed65b6598a384db63`.
- All 1,205 local tests passed with one skipped; GitHub Windows CI passed.
- The public dependency inventory, frozen Basic Pitch/CPU inference, and
  ten-second GUI startup self-test passed.
- All 1,465 sample-pack manifest records passed size and SHA-256 verification.

This release is not Authenticode publisher-signed, so Windows SmartScreen may
show an unknown-publisher warning. This is an unofficial community tool and is
not affiliated with Pearl Abyss.
