# 纯聊天 App 使用说明(ChatGPT、豆包、DeepSeek 等)

适用于没有文件访问、不能运行命令的聊天 App。配套文件:同目录下的 [system-prompt.md](./system-prompt.md)(开聊时整段粘贴的提示词)。本目录随技能分发,自包含;命令行是同一个技能目录里的 `scripts/life_redesign.py`。

## 先说清楚两个限制

1. **聊天里的 AI 看不到你的文件,也不能运行命令。** 它只能读你粘贴给它的"状态快照",只能输出文字。所以它不能保存任何东西:对话结束时它输出"更新块"(纯文本),**由你自己**存成文件,在本机用命令行 `apply-block` 应用。
2. **本流程不做"一天协议"**(第一次挖掘反愿景、愿景、设定第一版目标的整天流程)。那一步依赖命令行逐题落盘,请先在有命令行的环境里完成(见技能目录的 `PROTOCOL.md` 第 5 节)。没有做过的话,快照里 `vision` / `anti_vision` 是 `null`,`goals` 是 `{}`,AI 会让你先去完成它。

## 你需要什么

- 一台能运行 Python 3 的电脑(只用标准库),和这个技能目录。以下用变量 `LR` 指向脚本,换成你自己的实际路径:

```sh
LR="$HOME/.claude/skills/life-redesign/scripts/life_redesign.py"
```

- 第一次使用:`python3 "$LR" init`(创建数据目录 `~/.life-redesign/`,可用环境变量 `LIFE_REDESIGN_HOME` 改位置),并阅读隐私说明:你的记录只存在本机,但**你粘贴进聊天的内容会发送给该聊天 App 的服务商**。
- 下面的命令 bash 和 zsh 通用。

## 每次聊天的步骤

### 1. 导出并粘贴快照

```sh
python3 "$LR" snapshot
```

macOS 可以直接复制进剪贴板:`python3 "$LR" snapshot | pbcopy`。

先在新对话里粘贴 [system-prompt.md](./system-prompt.md) 的全部内容并发送,AI 会自我介绍并请你粘贴快照;然后粘贴快照输出的那一整段 JSON。真实的快照长这样(已完成协议、打卡一次后):

```json
{"generated": "2026-03-11T21:00:00", "vision": "每天写作、有体力的人\n\nIdentity Statement: ...", "anti_vision": "每天刷手机到凌晨、什么都没做的周二", "goals": {"Year Goal": "出版一本小册子", "Month Project": "写完 8000 字", "Constraints": "不牺牲睡眠", "Daily Levers": "早上写 500 字; 中午散步 20 分钟"}, "verdicts": [{"date": "2026-03-11", "verdict": "走偏"}], "streak": {"drift": 1, "unrecorded": 0, "escalation": false}}
```

### 2. 聊天

最常见的是"今晚打卡"。AI 会逐项追问(杠杆做了没有、有没有身份保护、更接近反愿景还是愿景),给出判定并写明理由。你反驳时,只有给出新的、可核对的事实它才会改判。

### 3. 要更新块,保存,应用

对话结束时对 AI 说"请给我更新块"。把它输出的代码块里的内容**原样**存成文本文件,例如 `update.txt`(用任何文本编辑器;注意不要让编辑器把引号变成弯引号、不要多加缩进),然后:

```sh
python3 "$LR" apply-block --file update.txt
```

也可以从标准输入传入(macOS 从剪贴板):`pbpaste | python3 "$LR" apply-block`,或 `python3 "$LR" apply-block < update.txt`。

成功时标准输出一行 JSON,含 `applied` 和(只要块里有日志)重算后的 `streak`:

```
{"applied": [{"file": "log/2026-03-11.md", "mode": "create"}], "streak": {"drift": 1, "unrecorded": 0, "escalation": false, "threshold": 3, "dnd_dates": []}}
```

失败时退出码 1,标准错误是 `error: <原因>`,**整批什么都没写入**。把完整错误贴回聊天,让 AI 改块再给你;不要为了通过而让 AI(或自己)编造原因或事实。

应用后,下次开聊重新运行 `snapshot`。

## 更新块的写法(与命令行一致,均已实测)

以下所有输出都是在一个已完成协议的临时数据目录里真实运行得到的。

### 合法的块

新建当天日志(`file` 带日期,`mode: create`;判定与理由是紧挨着的两行):

```
=== LIFE-REDESIGN UPDATE ===
file: log/2026-03-11.md
mode: create
---
# 2026-03-11
- Daily Levers: 早上写 500 字; 中午散步 20 分钟
- 完成情况: 早上写了 300 字,散步没去,晚上刷手机
- 行动偏离: 是 — 两项杠杆都没有完成
- 身份保护: 是 — 用户承认在躲
- 靠近反愿景: 靠近反愿景 — 晚上刷手机到很晚
- 判定: 走偏
- 判定理由: 两项杠杆未完成,用户承认在躲,晚上的行为靠近反愿景
=== END ===
```

被接受:`{"applied": [{"file": "log/2026-03-11.md", "mode": "create"}], "streak": {"drift": 1, ...}}`。

改判(只有新事实才行,原判定必须等于当天当前判定;追加一行):

```
=== LIFE-REDESIGN UPDATE ===
file: log/2026-03-11.md
mode: append
---
- 改判: 走偏 → 轻微偏离 — 因 晚上 9 点写完了 500 字,有保存记录 事实改判
=== END ===
```

被接受,`drift` 重算为 0。

修改计划(**必须以非空的 `_Reason: <原因>_` 行结尾**,且它是最后一行;`vision.md` / `anti-vision.md` 的正文是新版本全文且不写 `## 日期` 标题,`goals.md` 按 `### Year Goal` / `### Month Project` / `### Daily Levers` / `### Constraints` 小节写,没写的小节沿用旧版):

```
=== LIFE-REDESIGN UPDATE ===
file: goals.md
mode: append
---
### Month Project
写完 6000 字(把 8000 字下调,因为本月出差一周)
_Reason: 本月出差一周,实际可用时间少了四分之一_
=== END ===
```

被接受:`{"applied": [{"file": "goals.md", "mode": "append"}]}`,`show goals` 里这个版本带着这条 reason。`vision.md` 和 `anti-vision.md` 的块同理(实测均被接受)。

一次输出可以含多个块(例如一份日志加一项计划变更),实测被一起接受。

### 会被拒绝的写法(真实的错误信息)

| 写法 | 真实输出 |
|---|---|
| 改计划的块没有 `_Reason:` 结尾行 | `error: block 1: goals.md needs a reason: end the block with a non-empty line '_Reason: <why this is changing>_'` |
| `_Reason:` 行没有以 `_` 收尾(格式不对) | `error: block 1: anti-vision.md needs a reason: end the block with a non-empty line '_Reason: <why this is changing>_'` |
| 一天协议还没完成(`phase` 是 `new`、进行中或已搁置)时写任何块 | `error: update blocks are refused until the one-day protocol is complete: the protocol is not complete (phase: new): finish the protocol first (`protocol resume`, then answer every question)` |
| 日志日期晚于今天(`file: log/2099-01-01.md`,当时是 2026-03-11) | `error: block 1: log/2099-01-01.md is in the future (today is 2026-03-11): a log cannot be written ahead of its day` |
| 日志日期早于协议完成日(完成日是 2026-03-10) | `error: block 1: log/2026-03-09.md is before the protocol was completed (2026-03-10): there is no log for days before that` |
| 日志文件名不是日期(`file: log/notes.md`) | `error: block 1: log/notes.md is not a valid date: log files are named log/YYYY-MM-DD.md` |
| 沉默后(有未记录的天数)写新判定,但没有 `- 这几天发生了什么:` 行 | `error: block 1: you were silent: a block that writes a verdict must also say what happened in the missing days: add a non-empty line '- 这几天发生了什么: <what happened>' to the block` |
| `mode: replace` | `error: block 1: mode 'replace' not allowed; only create or append (records are append-only, ADR-0001)` |
| `mode: delete` | `error: block 1: mode 'delete' not allowed; only create or append (records are append-only, ADR-0001)` |
| 路径逃出数据目录(`file: log/../../etc/evil.md`) | `error: block 1: path 'log/../../etc/evil.md' is outside the data dir or malformed` |
| 目标是 `state.json`(`levers.jsonl`、`reviews.md` 同理) | `error: block 1: file 'state.json' is not an allowed target (vision.md, anti-vision.md, goals.md, log/*.md, protocol/*.md)` |
| `- 判定: 在轨` 后面没有紧跟 `- 判定理由:` | `error: block 1 (log/2026-03-12.md): '- 判定: 在轨' must be followed directly by a '- 判定理由: <reason>' line` |
| 当天已是走偏,悄悄追加 `- 判定: 在轨`(没有新事实) | `error: a check-in with verdict 走偏 is already recorded for this day; changing the verdict needs a new fact: use `checkin revise-verdict --new-fact "..." --verdict ...` (in an update block: a '- 改判: 走偏 → 在轨 — 因 <new fact> 事实改判' line)` |
| `- 改判:` 里的原判定不是当天当前判定 | `error: block 1 (log/2026-03-11.md): 改判 says the old verdict was 在轨 but the day's current verdict is 走偏` |
| 对没有判定的一天写 `- 改判:` | `error: block 1 (log/2026-03-10.md): no check-in recorded that day: nothing to revise` |
| 对已存在的文件用 `create` | `error: block 1: cannot create log/2026-03-11.md: file already exists (use mode: append)` |
| 正文里写 `## 2026-03-11` 之类的标题 | `error: block 1 body contains a version/section heading line ('## 2026-03-11'); headings are written only by the CLI` |
| 输入里没有任何块 | `error: no update block found (expected '=== LIFE-REDESIGN UPDATE ===' ... '=== END ===')` |
| `--file` 指向不存在的文件 | `error: cannot read ./nonexistent.txt: [Errno 2] No such file or directory: './nonexistent.txt'` |

整批原子:同一次输入里一个合法块加一个 `mode: replace` 块,整批被拒(`error: block 2: mode 'replace' not allowed; ...`),合法块也没有写入。

## 快照的局限(请照实理解)

- **只含最近 7 天的判定。** `verdicts` 只列出最近 7 天(含今天)里有判定的日子;更早的历史 AI 看不到。实测:快照生成日往前超过 7 天的判定不再出现。
- **没有 `phase`。** 不知道一天协议进行到哪、是否搁置。AI 只能根据 `vision` / `anti_vision` / `goals` 是否为空来推断,并向你确认。
- **只有当前版本。** 看不到 Vision / 目标的历史版本和当时的修改原因,所以"这次改得比上次容易吗"的对比只能基于当前文字加你的讲述。
- **只含当前的 Daily Levers 小节文字**,没有"明天的杠杆"(`levers.jsonl`)。
- **没有日志正文。** 看不到各天的完成情况、理由原文,只有判定值。
- 沉默多天时,`snapshot` 会像 `streak status` 一样先把缺的日子补成"未记录",所以 `unrecorded` 可能很大、`escalation` 为 `true`。

## 其他你应该知道的限制

- AI 无法核实你说的事实,也无法替你运行命令;它记不住上一场对话,每次都要重新粘贴提示词和快照。
- 更新块**不能**设置"明天的 Daily Levers"(那是命令行 `checkin record` 的功能);想改明天的杠杆,只能走"修改计划"改 `goals.md` 的 `### Daily Levers`(带原因)。
- 更新块对"沉默后回来先说发生了什么"也强制:沉默后(有未记录的天数,勿扰日不算)写新判定的块必须带非空的 `- 这几天发生了什么:` 行,否则整批拒绝(与命令行 `checkin record --while-away` 一致)。这一行要用你的原话,AI 仍应先问你。
- 命令行不检查判定与各项回答是否一致,不检查"新事实"是否真的新:这些靠 AI 的自觉和你的诚实。
- 日志日期会被检查:文件名必须是合法日期,不能晚于今天,不能早于协议完成日(完成当天允许)。但"今天"取你电脑的时钟,AI 在块里写错、但仍在这个范围内的日期(比如写成昨天)不会被发现。核对 AI 用的日期。
- 沉默期里被标成"未记录"的过去日子,日志文件已经存在(只有一行 `- 未记录`),给它补判定要用 `mode: append`,用 `create` 会被拒绝;快照看不出这些日期。
- 一天协议没有完成时,命令行拒绝所有更新块(`new`、进行中、已搁置都一样);先用命令行完成协议。重做协议期间不受影响。

## 没有命令行怎么办(手工退路)

如果你完全没法运行命令,仍然可以用同一套提示词聊天,但**失去命令行的所有保护**,请知情选择:

- 没有校验:格式写错、判定与理由不相邻、悄悄翻案、没写原因,都不会有人拦你。
- 没有 Streak 计算、未记录补记和 Escalation:连续走偏几天要你自己数。
- 没有一天协议的门禁。

可以这样手工保持"只追加、不覆盖、不删除":

1. 在手机或电脑上建一个笔记文件(备忘录、文档都行),按日期往**末尾**追加,不要回头改旧的内容。
2. 每次对话结束,让 AI 输出更新块,把块的正文(`---` 与 `=== END ===` 之间)原样追加到笔记里,前面写上日期和块里的 `file:`(例如"2026-03-11 log")。改计划时,把新版本连同 `_Reason: ...` 一并追加,不要覆盖旧版本。
3. 下次开聊,不用快照:把笔记里的**当前**反愿景、愿景、目标,以及**最近 7 天**的日志(日期、判定、理由)贴给 AI,并告诉它连续走偏和未打卡的天数,让它据此判断。AI 看不到的东西不要指望它记得。
4. 以后有了命令行,可以把笔记里的日志按块格式整理后用 `apply-block` 逐个导入(导入时仍受上述规则约束,例如判定必须带理由)。

这条退路是诚实的"能用但不受保护",不是等价替代。
