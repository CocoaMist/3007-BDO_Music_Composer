# 一起来改 ♪

欢迎。这里最看重的不是改动有多大，而是它有没有把用户正在编辑的曲子照顾好。

## 动手前

- 先读 [`AGENTS.md`](AGENTS.md) 和[接手手册](docs/AGENT_HANDOFF.md)。
- 按任务去[文档索引](docs/README.md)找对应领域，不用把整个 `docs/` 背下来。
- 游戏素材、私人曲谱、Owner ID、导出文件和提取音频不要进仓库。
- 关于格式、奏法或游戏行为的判断，要写清楚是实测、代码证据还是推断。
- 文档遵循[《文档说话方式》](docs/WRITING_STYLE.md)，少一点套话，多一点结论。

## 开发环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe main.py
```

Python 版本和完整依赖以 [`AGENTS.md`](AGENTS.md) 为准。

## 交改动前

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -q
.\.venv\Scripts\python.exe -m compileall -q src
.\.venv\Scripts\python.exe tools\check_repository_hygiene.py
git diff --check
```

界面、音频、导出或打包改动还有各自的专项检查，照
[`docs/AI_CONTEXT.md`](docs/AI_CONTEXT.md) 的验证矩阵补齐。测试通过不等于游戏里一定正确；
涉及曲谱结果时，请把仍未完成的游戏内验证写出来。

## 提交说明

讲清三件事就够了：为什么改、用户会看到什么、你怎么确认它没改坏别的地方。
如果有风险或没测到的环境，也一起写，藏着反而麻烦 ฅ^•ﻌ•^ฅ
