# 通用乐器奏法与 MIDI 优化规则

状态：2026-07-10。

本文件不描述任何游戏的效果名称，而是记录常见真实乐器奏法的音乐语境。程序把这些判断转换成 MIDI 的时值、力度、音程与乐句规则；只有目标乐器存在已验证的对应奏法时，才会写入目标格式。

## 共通原则

- **连奏（legato / tenuto）**：用于旋律连续、音符间没有可听见空隙、需要歌唱性时。默认不应额外处理。
- **断奏（staccato）**：既要短，也要和下一音留出可听见的空间；单纯短音不等于断奏。常用于舞曲、节奏型和轻巧伴奏。
- **重音（accent）**：是起音加强，不必缩短时值。算法优先以力度而非替换音色实现。
- **强重音（marcato）**：更强的起音并略带分离，适合段落开始、节拍重心和齐奏强调；不能密集套用。
- **滑音（glissando / slide）**：只用于有方向的连接，通常在相邻到小音程、间隔很小的音之间。和弦、重叠音、跳进旋律不自动加。
- **保持原演奏**：原 MIDI 若已经有明显力度起伏或离格节奏，默认视为人性化演奏，不做强量化或统一力度。

## 弦乐：小提琴、低音提琴、竖琴

### 弓弦乐器

- 连续旋律以连奏为默认；音符之间仅有很小间隔时可延长前音，但不跨越下一音起点。
- 断奏适合短而有明确间隔的节奏型；不能仅依据音符时值判断。
- 颤音需要真实的邻音往返或明确记号。程序要求“原音 - 半音/全音邻音 - 原音”的结构，避免把普通长音误变为颤音。
- 拨弦（pizzicato）、跳弓（spiccato）、弓根重音等，需要乐器音色库明确支持；没有可验证映射时只保留为建议。

### 竖琴

- 分解和弦、跨音区快速连续级进才可能是滑奏；普通旋律音阶不自动改滑奏。
- 和弦功能优先保留原音高与时值，避免把同拍和弦改成不同奏法。

## 木管与铜管：长笛、竖笛、单簧管、圆号

- 连奏依靠气流连续，适合歌唱旋律、级进音型与长线条。
- 吐音断奏适合有明确间隔的短音、舞曲节奏和重复音型。
- 重音应优先通过起音力度表达；铜管尤其需要保留后续的持续声音，不能把重音错误变成极短音。
- 乐句要留出“换气”空间。程序不会凭空删音或插休止，但把大于约一个拍子的空隙识别为乐句边界，以限制奏法密度。

## 键盘：钢琴

- 踏板服务于和声与连贯性，不是所有长音的默认效果。
- 自动踏板仅在一个长音实际跨到后续音符时建议；已有 MIDI CC64 的真实踏板信息应优先保留。
- 和弦内部的力度关系比统一加重更重要，因此力度润色保持同拍和弦各声部的相对大小。

## 吉他与贝斯

- 掌根闷音适用于短、重复、节奏明确的低中音 riff；不适合自由旋律长音。
- 击弦（slap）适用于高力度、短时值、带节奏推动力的 bass 音；不是“所有大声贝斯音”。
- 鬼音/X 音符用于节奏填充，往往落在十六分切分或主音前的弱拍；未经明确映射不新增音符，只可改已有的极短弱音。
- 泛音适合高音区稀疏点缀，不能覆盖主旋律或和弦。

## 打击乐

- 大鼓与军鼓常承担节拍骨架，力度可在强拍略加强，但保留原有 groove 优先。
- Crash 通常用于段落重音、转折或高潮，不应用作持续节拍声部。
- 军鼓滚奏、镲片滚奏适合渐强进入重拍或高潮；只能在已有快速重复音或明确滚奏音色映射时处理，不能由单一长音凭空生成。

## 已落实的程序机制

1. 以同拍起始时间识别和弦；同拍和弦不自动使用滑音、断奏或颤音。
2. 按大于 420 ms 的可听见间隔切分乐句；每句最多自动添加 3 个奏法。
3. 只有原始力度跨度不足 18 时才添加通用强弱拍曲线；已有明显动态时仅轻微强调小节起点。
4. 滑音要求无重叠、小音程、短连接；颤音要求邻音返回；闷音要求短重复 riff。
5. 所有自动改动先在“优化 MIDI”报告中预览；用户确认后才写入工程和导出文件。

## 参考资料

- Brass Techniques and Pedagogy, “Articulation on Brass Instruments”
  https://pressbooks.palni.org/brasstechniquesandpedagogy/chapter/articulation-on-brass-instruments/
- Dolmetsch Online, “Phrasing & Articulation”
  https://www.dolmetsch.com/musictheory21.htm
- Long Beach City College, “Melodic Analysis”
  https://lbcc.pressbooks.pub/intromtcls/chapter/chapter-8-melodic-analysis/
- Fender, “3 Keys to Ace Your Palm Muting”
  https://www.fender.com/articles/techniques/3-keys-to-ace-your-palm-muting
- Premier Guitar, “Slap Bass Fundamentals”
  https://www.premierguitar.com/on-bass-slap-bass-fundamentals
- Yamaha Music, “Snare Drum Rolls Teaching Tips”
  https://hub.yamaha.com/music-educators/instruments/perc/snare-drum-rolls-pedagogy/
- GigaMIDI Dataset paper：以力度与起始时间偏移识别表现性 MIDI
  https://arxiv.org/abs/2502.17726
