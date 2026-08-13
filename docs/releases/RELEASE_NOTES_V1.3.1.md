# BDO Music Composer v1.3.1

[中文](#中文) | [English](#english)

## 中文

v1.3.1 是多音轨 Clip 完整性修复版本，重点解决一个轨道包含多个 Clip 时，
从轨道入口编辑会错误进入最后一个 Clip、应用后破坏时间位置的问题。编辑事务现在
明确绑定目标 Clip，并在应用前检查目标是否已被其他操作修改，避免覆盖较新的内容。

### 主要变化

- 多 Clip 轨道从轨道入口编辑时明确选择目标，不再隐式使用最后一个 Clip。
- Clip 编辑只替换目标内容，保留同轨其他 Clip 的音符、位置与控制数据。
- 为 Clip 编辑加入并发指纹校验；目标发生变化时拒绝过期编辑，同轨其他 Clip 的独立变化不受影响。
- 新建空轨道自动带有一个一小节的空 Clip，使后续编辑始终使用一致的数据模型。
- 剃刀切分立即生成两份独立、完整且按边界裁切的 Clip 内容。
- 修正 Clip 投影在预览、验证、合并、可见统计与力度曲线编辑中的时间和索引一致性。
- 带 Clip 的轨道禁用不安全的整轨优化入口，引导用户在目标 Clip 内编辑。
- 补充多音轨导入、复制粘贴、合并、编辑提交和速度曲线的回归覆盖。

### 可选 CC0 音源包（复用 v1.2.1 资产）

本版本继续兼容 v1.2.1 已发布的
[`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`](https://github.com/CocoaMist/3007-BDO_Music_Composer/releases/download/v1.2.1/BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples)。
已有本地副本无需重新下载。该包仅包含独立许可的 CC0 近似试听素材，
不含 Black Desert 客户端音频。

## English

v1.3.1 is a multitrack Clip integrity release. It fixes a serious case where
opening a track containing multiple Clips implicitly edited the last Clip and
then displaced timeline content when the draft was applied. Editor transactions
now target an explicit Clip and verify that target before committing stale work.

### Highlights

- Track-level editing of a multi-Clip track now asks for an explicit target instead of silently choosing the last Clip.
- Clip editing replaces only the target content and preserves sibling Clips, positions, and control data.
- Optimistic Clip fingerprint checks reject stale target edits while allowing independent sibling changes.
- New empty tracks receive a one-measure empty Clip so later editing uses one consistent model.
- Razor splits immediately create two independent, complete Clips cropped to their respective bounds.
- Preview, validation, merge, visible statistics, and velocity editing now share consistent projected Clip timing and authored indexes.
- Unsafe whole-track optimization is disabled for Clip-backed tracks and directs the user to the target Clip editor.
- Expanded regression coverage for multitrack import, copy/paste, merge, editor commits, and velocity curves.

### Optional CC0 sample pack (reused v1.2.1 asset)

This release remains compatible with the v1.2.1
[`BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples`](https://github.com/CocoaMist/3007-BDO_Music_Composer/releases/download/v1.2.1/BDO-Approximate-CC0-Full-Coverage-v4-Compact.bdosamples)
asset. Existing local copies do not need to be downloaded again. The pack
contains independently licensed CC0 material for approximate preview only,
not Black Desert client audio.
