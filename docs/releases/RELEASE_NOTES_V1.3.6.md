# BDO Music Composer v1.3.6 ♪

发布日期：2026-08-16

## 中文

这次把多轨编排里真正缺的那块补回来了：Track 和 Clip 可以各自调整力度，
全轨道调整也不会再偷偷覆盖它们。简单说，选谁就改谁，撤销、保存、试听和导出
看到的是同一份结果 `(｡•̀ᴗ-)✧`

### 这版改了什么

- Track 支持独立力度百分比，按住 Shift 可以多选 Track 后一起调整。
- Clip 支持独立力度百分比和力度基数，多选 Clip 时按共同百分比修改。
- 全轨道、Track、Clip 三层调整会组合到音符上，不再互相抵消或套用旧基线。
- 百分比真正写入对应音符，同时保留可恢复基线，因此能够撤销、追溯和重新调整。
- Clip 左下角显示“名称 · 音块数量 · 力度百分比”，文字固定在可见内容上方。
- 整理了播放栏：滑杆更长，吸附收进左侧工具区，视图控制靠右。
- 重写项目 README 和文档入口，少一点套话，少一点东一块西一块。

### 导出与兼容

BDO v9 导出读取正在编辑的音符，不会回头使用最初导入的 MIDI。压力样本经过
“导出 → 导入 → 再导出”后字节一致；Clip 的编辑辅助信息不会写进游戏曲谱，
游戏文件保存的是最终音符结果。

### 关于稳定版

如果游戏内部的曲谱机制没有变化，v1.3.6 大概率会先作为暂时的长期稳定版维护。
之后优先修兼容性和确实影响写谱的问题，不为了凑版本号频繁更新。能安稳写歌，
比数字一直往上跳重要一点 ฅ^•ﻌ•^ฅ

### 下载前知道这些

- 这是非官方工具，与 Pearl Abyss 没有隶属或合作关系。
- 正式包不含游戏客户端音频、用户工程、Owner ID、缓存或私有密钥。
- Windows 包未必带 Authenticode 签名，系统首次运行时可能显示信誉提示。
- 真正的最终校验仍然是在你的游戏客户端里打开并试听曲谱。

---

## English

Version 1.3.6 restores the missing part of multitrack editing: Track and Clip
velocity can be adjusted independently, and the global control no longer
silently overwrites scoped edits.

### What changed

- Track velocity percentages, including Shift multi-selection.
- Clip velocity percentages, multi-selection, and a separate Clip velocity base.
- Composable global, Track, and Clip edits built from recoverable note baselines.
- Undo/redo, autosave, preview, and BDO export all follow the same edited notes.
- Compact Clip labels and a cleaner, better-spaced transport bar.
- A shorter documentation path with a direct, Chinese-first project voice.

### Stability note

If the game's score mechanics do not change, v1.3.6 will likely remain the
temporary long-term stable release. Future updates will focus on compatibility
and problems that materially affect score writing instead of increasing the
version number for its own sake.

BDO Music Composer is unofficial and is not affiliated with Pearl Abyss.
