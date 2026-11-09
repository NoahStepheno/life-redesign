# CLI 端到端测试指南

本指南让你不读代码,就能验证 `skill/scripts/life_redesign.py` 的全部行为:先跑自动化测试套件,再用一个临时数据目录加注入时间,手工走完整套流程。每一步给出要执行的命令和**实际输出**,包括应当被拒绝的情况及其错误信息。

术语沿用仓库根目录的 `GLOSSARY.md`(Check-in、Verdict、Drift、Unrecorded、Escalation 等)。`streak`、`dnd` 是 CLI 的子命令名:前者统计连续走偏和连续未记录的天数,后者管理勿扰日。

本指南不涉及真实的 launchd 和真实系统通知(那属于另一份文档)。

## 1. 自动化测试套件

在仓库根目录运行:

```sh
python3 -m unittest discover
```

- 当前共 168 个测试,完整运行约 5 分钟(实测 353 秒,多数时间花在反复启动 CLI 子进程)。
- 迭代时只跑一个模块、一个类或一个用例(实测分别约 54 秒、13 秒、3 秒;`test_init` 约 2 秒):

```sh
python3 -m unittest tests.test_streak
python3 -m unittest tests.test_streak.DriftTest
python3 -m unittest tests.test_streak.DriftTest.test_three_drift_days_escalate
```

- 模块与大致职责:`test_init`(初始化、隐私确认、数据目录)、`test_protocol`(一天协议的续做、隔夜、搁置、重做)、`test_append`(追加式保护)、`test_plan`(计划变更)、`test_checkin`(Check-in 与改判)、`test_streak`(Drift、Unrecorded、Escalation、勿扰日)、`test_review`(月复盘、年复盘)、`test_blocks`(状态快照与更新块)、`test_notify`(推送计划与文案)。

### 为什么测试不会碰真实的用户目录

`tests/helpers.py` 里每个用例都在一个新建的临时目录里运行 CLI 子进程,并且:

- `LIFE_REDESIGN_HOME` 指向临时数据目录(CLI 默认写 `~/.life-redesign/`,设了它就改写别处)。
- `LIFE_REDESIGN_NOW` 固定当前时间,让"几天后"可以瞬间完成,结果可复现。
- `HOME` 被重定向到另一个临时目录,所以即使某处漏用了数据目录覆盖,也不会写到真实的家目录。
- 测试结束后临时目录被删除。

下面的手工流程用同样的两个环境变量。

### 自动化测试覆盖什么、不覆盖什么

| 自动化测试覆盖 | 只能人工试用(见第 4 节) |
|---|---|
| 本指南第 3 节的每一条命令及其拒绝情形 | AI 追问是否足够具体、判定是否严格(行为准则靠模型遵守,CLI 不检查) |
| 状态机、7 天搁置、隔夜"感受还在吗"、Streak、Escalation、勿扰日、Unrecorded 补记 | Part 2 白天的 6 条 Interrupt(按固定时间推送,没有 CLI 命令记录回答) |
| 追加式保护:禁止改写和删除的动词、标题注入、更新块的 `replace` / `delete` | 用户真实的隔夜感受、真实的一整天协议体验 |
| 月复盘和年复盘的统计口径 | 复盘中 AI 对"悄悄改动计划"的追问质量 |
| 推送计划、文案、预写内容,以及 launchd 与通知命令的构造(用假的 `launchctl` 和 `terminal-notifier`) | 真实 launchd 安装、真实系统通知弹出、`claude -p` 生成的晚间提醒(属于另一份文档) |
| 对话中粘贴状态快照、回贴更新块的格式校验 | 在真实聊天 App 里粘贴快照、把更新块贴回终端的完整手感 |

## 2. 手工流程的准备

下面所有块在**同一个终端会话**里按顺序执行。先进入仓库根目录,再运行准备块。它定义三个函数:

- `lr`:运行 CLI;命令失败时多打印一行 `[exit N]`,方便看清退出码。
- `clock`:设置 `LIFE_REDESIGN_NOW`,相当于拨动时钟。
- `ci`:一次完整的 Check-in,只需传入 Verdict 和理由,其余固定参数写在函数里。

所有参数列表都用函数或带引号的写法,没有依赖"不加引号的变量自动按空格拆分"(zsh 不这样做),所以 bash 和 zsh 通用。

```sh
export LIFE_REDESIGN_HOME=/tmp/life-redesign-e2e
CLI="$PWD/skill/scripts/life_redesign.py"
lr() { python3 "$CLI" "$@" || echo "[exit $?]"; }
clock() { export LIFE_REDESIGN_NOW="$1"; }
ci() {
  local verdict="$1" reason="$2"
  shift 2
  lr checkin record \
    --levers-done "写了 500 字,跑了步" \
    --action-drift no --action-reason "两项都完成" \
    --identity-protection no --identity-reason "没有" \
    --toward vision --toward-reason "今天更接近愿景里的周二" \
    --verdict "$verdict" --verdict-reason "$reason" \
    --tomorrow-lever "写 500 字" --tomorrow-lever "跑步 20 分钟" "$@"
}
```

### 安全地重置测试数据

测试数据只在 `/tmp/life-redesign-e2e`,不在 `~/.life-redesign/`。要从头再来,删掉这个目录即可。下面的写法先确认目录名,避免误删别处(这条命令是**你**手动重置测试目录,CLI 本身没有任何删除能力):

```sh
case "$LIFE_REDESIGN_HOME" in /tmp/life-redesign-e2e) rm -rf "$LIFE_REDESIGN_HOME" ;; esac
```

这是流程的第一步,执行后目录不存在,所以下一节的第一条命令会报"未初始化"。

## 3. 手工流程

### 3.1 初始化与隐私确认

初始化之前,任何命令都应报未初始化:

```sh
clock 2026-01-10T09:00:00
lr status
```

```output
error: not initialized: run `init` first
[exit 1]
```

初始化,然后确认隐私告知。`init` 可重复执行,不会破坏已有数据;`init --ack-privacy` 是合并写法。

```sh
lr init
lr ack-privacy
lr status
ls -A "$LIFE_REDESIGN_HOME"
```

```output
{"phase": "new", "privacy_required": true, "data_dir": "/tmp/life-redesign-e2e", "now": "2026-01-10T09:00:00"}
{"phase": "new", "privacy_required": false, "data_dir": "/tmp/life-redesign-e2e", "now": "2026-01-10T09:00:00"}
{"phase": "new", "privacy_required": false, "data_dir": "/tmp/life-redesign-e2e", "now": "2026-01-10T09:00:00"}
log
protocol
state.json
```

### 3.2 协议完成之前,日常入口全部被挡住

`phase` 不是 `active` 时,Check-in、`streak`、`review`、`plan` 都被拒绝,提示先完成一天协议。回答题目也要先 `protocol resume`。

```sh
lr protocol gate
lr checkin record --action-drift no --identity-protection no --toward vision
lr streak status
lr review month
lr plan change vision --text x --why y
lr protocol answer 1.1 --text hi
```

```output
error: the protocol is not complete (phase: new): finish the protocol first (`protocol resume`, then answer every question)
[exit 1]
error: the protocol is not complete (phase: new): finish the protocol first (`protocol resume`, then answer every question)
[exit 1]
error: the protocol is not complete (phase: new): finish the protocol first (`protocol resume`, then answer every question)
[exit 1]
error: the protocol is not complete (phase: new): finish the protocol first (`protocol resume`, then answer every question)
[exit 1]
error: the protocol is not complete (phase: new): finish the protocol first (`protocol resume`, then answer every question)
[exit 1]
error: protocol not started: run `protocol resume` first
[exit 1]
```

### 3.3 一天协议:逐题回答、当天续做

题目编号:`1.1` 到 `1.14` 是 Part 1(Excavation),`3.1` 到 `3.7` 加 `3.constraints` 是 Part 3(Synthesis)。Part 2 的 Interrupt 是定时推送,不通过 CLI 回答。共 22 题,必须按顺序。

```sh
lr protocol status
lr protocol resume
```

```output
{"phase": "new", "redo": false, "part": null, "question": null, "answered": 0, "total": 22, "feeling_check_required": false}
{"phase": "protocol_in_progress", "redo": false, "part": 1, "question": "1.1", "answered": 0, "total": 22, "feeling_check_required": false}
```

以下是应被拒绝的回答:乱序、不存在的题号、空文本、在文本里夹带标题行(防止伪造下一题)。

```sh
lr protocol answer 1.2 --text "hi"
lr protocol answer 9.9 --text "hi"
lr protocol answer 1.1 --text "   "
lr protocol answer 1.1 --text $'第一行\n## 1.2\n伪造的下一题'
```

```output
error: answer questions in order: current question is 1.1
[exit 1]
error: unknown question id '9.9' (valid: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8, 1.9, 1.10, 1.11, 1.12, 1.13, 1.14, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.constraints)
[exit 1]
error: --text is empty
[exit 1]
error: --text contains a version/section heading line ('## 1.2'); headings are written only by the CLI
[exit 1]
```

正常回答两题,然后同一天晚上回来继续:不需要任何确认,直接从断点往下答。

```sh
lr protocol answer 1.1 --text "我忍受了每天下午三点的空虚。"
lr protocol answer 1.2 --text "抱怨:工作、睡眠、体重。"
clock 2026-01-10T20:00:00
lr protocol status
lr protocol answer 1.3 --text "旁观者会说我想要安稳。"
```

```output
{"answered": "1.1", "next": "1.2", "file": "2026-01-10.md", "phase": "protocol_in_progress"}
{"answered": "1.2", "next": "1.3", "file": "2026-01-10.md", "phase": "protocol_in_progress"}
{"phase": "protocol_in_progress", "redo": false, "part": 1, "question": "1.3", "answered": 2, "total": 22, "feeling_check_required": false}
{"answered": "1.3", "next": "1.4", "file": "2026-01-10.md", "phase": "protocol_in_progress"}
```

### 3.4 隔夜回来:"那天的感受还在吗?"

第二天回来,`feeling_check_required` 变为 `true`,回答被拒绝,直到你确认感受。确认 `faded`(已淡去)会把旧段落改名为 `.discarded`(不删除),并从头重做;确认 `fresh` 则直接续做。

```sh
clock 2026-01-11T09:00:00
lr protocol status
lr protocol answer 1.4 --text "我不愿承认我很孤独。"
lr protocol confirm-feeling faded
ls "$LIFE_REDESIGN_HOME/protocol"
lr protocol answer 1.1 --text "重新回答:我忍受的是拖延。"
```

```output
{"phase": "protocol_in_progress", "redo": false, "part": 1, "question": "1.4", "answered": 3, "total": 22, "feeling_check_required": true}
error: overnight return: run `protocol confirm-feeling fresh|faded` first
[exit 1]
{"phase": "protocol_in_progress", "redo": false, "part": 1, "question": "1.1", "answered": 0, "total": 22, "feeling_check_required": false}
2026-01-10.discarded.md
{"answered": "1.1", "next": "1.2", "file": "2026-01-11.md", "phase": "protocol_in_progress"}
```

### 3.5 超过 7 天:搁置

最后一次活动是 1 月 11 日 09:00;到 1 月 19 日(超过 7 天)再进入,协议被搁置,旧答案改名为 `.archived`。搁置是在下一次任何协议命令时才发生的(惰性判定)。此后只能 `protocol resume` 从头开始。

```sh
clock 2026-01-19T09:00:00
lr protocol status
ls "$LIFE_REDESIGN_HOME/protocol"
lr protocol answer 1.1 --text "x"
lr protocol resume
```

```output
{"phase": "protocol_shelved", "redo": false, "part": null, "question": null, "answered": 0, "total": 22, "feeling_check_required": false}
2026-01-10.discarded.md
2026-01-11.archived.md
error: protocol not started: run `protocol resume` first
[exit 1]
{"phase": "protocol_in_progress", "redo": false, "part": 1, "question": "1.1", "answered": 0, "total": 22, "feeling_check_required": false}
```

### 3.6 完成协议

先答完 Part 1(14 题,循环内输出丢弃),隔夜后确认感受还在,再答完 Part 3。最后一题回答后 `phase` 变为 `active`。

```sh
for q in 1.1 1.2 1.3 1.4 1.5 1.6 1.7 1.8 1.9 1.10 1.11 1.12 1.13 1.14; do
  lr protocol answer "$q" --text "第一部分答案 $q" > /dev/null
done
lr protocol status
clock 2026-01-20T09:00:00
lr protocol status
lr protocol confirm-feeling fresh
lr protocol confirm-feeling fresh
```

```output
{"phase": "protocol_in_progress", "redo": false, "part": 3, "question": "3.1", "answered": 14, "total": 22, "feeling_check_required": false}
{"phase": "protocol_in_progress", "redo": false, "part": 3, "question": "3.1", "answered": 14, "total": 22, "feeling_check_required": true}
{"phase": "protocol_in_progress", "redo": false, "part": 3, "question": "3.1", "answered": 14, "total": 22, "feeling_check_required": false}
error: no feeling check pending
[exit 1]
```

```sh
for q in 3.1 3.2 3.3 3.4 3.5 3.6 3.7; do
  lr protocol answer "$q" --text "第三部分答案 $q" > /dev/null
done
lr protocol status
lr protocol answer 3.constraints --text "不牺牲睡眠和家人时间。"
lr protocol status
lr protocol gate
```

```output
{"phase": "protocol_in_progress", "redo": false, "part": 3, "question": "3.constraints", "answered": 21, "total": 22, "feeling_check_required": false}
{"answered": "3.constraints", "next": null, "file": "2026-01-20.md", "phase": "active"}
{"phase": "active", "redo": false, "part": null, "question": null, "answered": 22, "total": 22, "feeling_check_required": false}
{"active": true}
```

协议完成后,再回答或 `resume` 都被拒绝;重做必须显式 `redo`:

```sh
lr protocol answer 1.1 --text "again"
lr protocol resume
ls "$LIFE_REDESIGN_HOME/protocol"
```

```output
error: protocol already complete; use `protocol redo` to redo it explicitly
[exit 1]
error: protocol already complete; use `protocol redo` to redo it explicitly
[exit 1]
2026-01-10.discarded.md
2026-01-11.archived.md
2026-01-19.md
2026-01-20.md
```

答完最后一题的那一刻,CLI 把用户的原话原样写成第一版计划文件(Anti-vision ← 3.3,Vision ← 3.4 加 1.13 的身份宣言,Year Goal / Month Project / Daily Levers / Constraints ← 3.5 / 3.6 / 3.7 / 3.constraints),并带来源标记 `_Reason: 来自一天协议_`;几个文件要么全部写入要么全部不写。快照此时已非空:

```sh
cat "$LIFE_REDESIGN_HOME/anti-vision.md"
cat "$LIFE_REDESIGN_HOME/vision.md"
cat "$LIFE_REDESIGN_HOME/goals.md"
lr show vision
```

```output
## 2026-01-20
第三部分答案 3.3
_Reason: 来自一天协议_
## 2026-01-20
第三部分答案 3.4

Identity Statement: 第一部分答案 1.13
_Reason: 来自一天协议_
## 2026-01-20
### Year Goal
第三部分答案 3.5

### Month Project
第三部分答案 3.6

### Constraints
不牺牲睡眠和家人时间。

### Daily Levers
第三部分答案 3.7
_Reason: 来自一天协议_
{"target": "vision", "current": {"date": "2026-01-20", "reason": "来自一天协议", "content": "第三部分答案 3.4\n\nIdentity Statement: 第一部分答案 1.13"}, "versions": [{"date": "2026-01-20", "reason": "来自一天协议", "content": "第三部分答案 3.4\n\nIdentity Statement: 第一部分答案 1.13"}]}
```

### 3.7 追加式保护:`append` 与 `plan`

三个文件(Anti-vision、Vision、目标)每次写入都追加一个带日期的新版本,当前版本是最后一段。协议完成时已经写下了第一版(见上一节),下面的 `append` 是在其后继续追加。

```sh
clock 2026-01-20T10:00:00
lr append anti-vision --text "五年后的周二:我在同一张桌子前醒来,依然拖延,依然孤独。"
lr append vision --text "三年后的周二:我在自己的工作室醒来,身体轻盈。我是那种说到做到的人。"
lr append goals --year-goal "年底前发布第一个付费产品" --month-project "完成产品原型" --constraints "不牺牲睡眠和家人时间"
lr append anti-vision --text "(第二版)十年后我仍在原地,没有人记得我做过什么。"
cat "$LIFE_REDESIGN_HOME/anti-vision.md"
lr show anti-vision
```

```output
{"target": "anti-vision", "date": "2026-01-20", "versions": 2}
{"target": "vision", "date": "2026-01-20", "versions": 2}
{"target": "goals", "date": "2026-01-20", "versions": 2}
{"target": "anti-vision", "date": "2026-01-20", "versions": 3}
## 2026-01-20
第三部分答案 3.3
_Reason: 来自一天协议_

## 2026-01-20
五年后的周二:我在同一张桌子前醒来,依然拖延,依然孤独。

## 2026-01-20
(第二版)十年后我仍在原地,没有人记得我做过什么。
{"target": "anti-vision", "current": {"date": "2026-01-20", "content": "(第二版)十年后我仍在原地,没有人记得我做过什么。"}, "versions": [{"date": "2026-01-20", "reason": "来自一天协议", "content": "第三部分答案 3.3"}, {"date": "2026-01-20", "content": "五年后的周二:我在同一张桌子前醒来,依然拖延,依然孤独。"}, {"date": "2026-01-20", "content": "(第二版)十年后我仍在原地,没有人记得我做过什么。"}]}
```

CLI 没有任何改写或删除能力。试图用这类动词或开关,会被拒绝,并说明原因(下面三条的错误信息相同,只是第一个词不同):

```sh
lr append vision --overwrite --text x
lr append vision --text x --force
lr delete
```

```output
error: '--overwrite' is not supported: records are append-only (ADR-0001). Use `append` to add a new dated version; old versions are never overwritten or deleted. The CLI never deletes anything: it only marks (renames) one-day-protocol segments, when a protocol is shelved or a feeling is confirmed faded. Archiving the whole data directory is done by hand.
[exit 1]
error: '--force' is not supported: records are append-only (ADR-0001). Use `append` to add a new dated version; old versions are never overwritten or deleted. The CLI never deletes anything: it only marks (renames) one-day-protocol segments, when a protocol is shelved or a feeling is confirmed faded. Archiving the whole data directory is done by hand.
[exit 1]
error: 'delete' is not supported: records are append-only (ADR-0001). Use `append` to add a new dated version; old versions are never overwritten or deleted. The CLI never deletes anything: it only marks (renames) one-day-protocol segments, when a protocol is shelved or a feeling is confirmed faded. Archiving the whole data directory is done by hand.
[exit 1]
```

其他被拒绝的写入:空内容、缺参数、用户文本里伪造版本标题或小节标题、用错参数。

```sh
lr append vision --text $'好的\n## 2020-01-01\n伪造的旧版本'
lr append vision --text ""
lr append vision
lr append goals --text x
lr append goals
lr append goals --year-goal $'a\n### Month Project\nb'
lr append vision --year-goal x
```

```output
error: --text contains a version/section heading line ('## 2020-01-01'); headings are written only by the CLI
[exit 1]
error: --text is empty
[exit 1]
error: --text is required
[exit 1]
error: goals takes --year-goal/--month-project/--constraints, not --text
[exit 1]
error: goals needs at least one of --year-goal, --month-project, --constraints
[exit 1]
error: --year-goal contains a version/section heading line ('### Month Project'); headings are written only by the CLI
[exit 1]
error: --year-goal is only valid for goals
[exit 1]
```

### 3.8 计划变更:必须说明原因

`plan change` 追加新版本并记下 `_Reason: ..._`,旧版本不动。`daily-levers` 只能通过 `plan` 写入。没有 `--why` 被拒绝,不存在的对象被 argparse 拒绝(退出码 2)。

```sh
lr plan change daily-levers --text $'写 500 字\n跑步 20 分钟' --why "初始杠杆"
lr plan change month-project --text "完成原型并给 3 个人看"
lr plan change month-project --why x
lr plan change delete
cat "$LIFE_REDESIGN_HOME/goals.md"
```

```output
{"object": "daily-levers", "date": "2026-01-20", "old": "第三部分答案 3.7", "new": "写 500 字\n跑步 20 分钟", "why": "初始杠杆", "versions": 3}
error: --why is required: say why this is changing
[exit 1]
error: --text is required
[exit 1]
usage: life_redesign plan change [-h] [--text TEXT] [--why WHY]
                                 {anti-vision,constraints,daily-levers,month-project,vision,year-goal}
life_redesign plan change: error: argument object: invalid choice: 'delete' (choose from 'anti-vision', 'constraints', 'daily-levers', 'month-project', 'vision', 'year-goal')
[exit 2]
## 2026-01-20
### Year Goal
第三部分答案 3.5

### Month Project
第三部分答案 3.6

### Constraints
不牺牲睡眠和家人时间。

### Daily Levers
第三部分答案 3.7
_Reason: 来自一天协议_

## 2026-01-20
### Year Goal
年底前发布第一个付费产品

### Month Project
完成产品原型

### Constraints
不牺牲睡眠和家人时间

### Daily Levers
第三部分答案 3.7

## 2026-01-20
### Year Goal
年底前发布第一个付费产品

### Month Project
完成产品原型

### Constraints
不牺牲睡眠和家人时间

### Daily Levers
写 500 字
跑步 20 分钟
_Reason: 初始杠杆_
```

### 3.9 每晚 Check-in 与 Verdict

Verdict 只有三档:在轨、轻微偏离、走偏,必须附理由。第一次打卡要传 `--lever`(今天的 Daily Levers);之后每次打卡用 `--tomorrow-lever` 设定明天的 Levers,明天可以不再传 `--lever`。

```sh
clock 2026-01-21T21:30:00
ci 在轨 "两项杠杆都有具体产出" --lever "写 500 字" --lever "跑步 20 分钟"
cat "$LIFE_REDESIGN_HOME/log/2026-01-21.md"
lr checkin levers --date 2026-01-22
lr checkin levers --date 2026-1-22
```

```output
{"date": "2026-01-21", "file": "log/2026-01-21.md", "verdict": "在轨", "tomorrow_date": "2026-01-22", "tomorrow_levers": ["写 500 字", "跑步 20 分钟"]}
# 2026-01-21
- Daily Levers: 写 500 字; 跑步 20 分钟
- 完成情况: 写了 500 字,跑了步
- 行动偏离: 否 — 两项都完成
- 身份保护: 否 — 没有
- 靠近反愿景: 靠近愿景 — 今天更接近愿景里的周二
- 判定: 在轨
- 判定理由: 两项杠杆都有具体产出
{"date": "2026-01-22", "levers": ["写 500 字", "跑步 20 分钟"]}
error: --date must be YYYY-MM-DD
[exit 1]
```

### 3.10 同日改判被拒绝,带新事实才能改判

当天已经有一个 Verdict 后,用 `checkin record` 给出**不同**的 Verdict 会被拒绝。必须用 `revise-verdict` 并给出新的事实。其他非法输入也在这里一并检查。

```sh
ci 不错 "x" --lever "写 500 字"
ci 走偏 "我想改判" --lever "写 500 字"
ci 在轨 "" --lever "写 500 字"
lr checkin record --action-drift maybe --identity-protection no --toward vision
```

```output
error: --verdict must be one of: 在轨 / 轻微偏离 / 走偏
[exit 1]
error: a check-in with verdict 在轨 is already recorded today; changing the verdict needs a new fact: use `checkin revise-verdict --new-fact "..." --verdict ...`
[exit 1]
error: --verdict-reason is required and must not be empty
[exit 1]
usage: life_redesign checkin record [-h] [--lever LEVER]
                                    [--levers-done LEVERS_DONE] --action-drift
                                    {yes,no} [--action-reason ACTION_REASON]
                                    --identity-protection {yes,no}
                                    [--identity-reason IDENTITY_REASON]
                                    --toward {anti-vision,vision}
                                    [--toward-reason TOWARD_REASON]
                                    [--verdict VERDICT]
                                    [--verdict-reason VERDICT_REASON]
                                    [--tomorrow-lever TOMORROW_LEVER]
                                    [--while-away WHILE_AWAY]
life_redesign checkin record: error: argument --action-drift: invalid choice: 'maybe' (choose from 'yes', 'no')
[exit 2]
```

同一天用**相同**的 Verdict 再记一次是允许的,日志里追加一段"再次打卡"。然后是改判:没有新事实、Verdict 非法都被拒绝;给出新的事实才改判,改判以追加一行记录,原来的 Verdict 行仍然保留。

```sh
ci 在轨 "晚上又补了一次记录" --lever "写 500 字"
lr checkin revise-verdict --verdict 走偏
lr checkin revise-verdict --new-fact "我觉得应该改" --verdict 不错
lr checkin revise-verdict --new-fact "下午发现 500 字其实是复制来的,实际产出为 0" --verdict 走偏
cat "$LIFE_REDESIGN_HOME/log/2026-01-21.md"
lr streak status
```

```output
{"date": "2026-01-21", "file": "log/2026-01-21.md", "verdict": "在轨", "tomorrow_date": "2026-01-22", "tomorrow_levers": ["写 500 字", "跑步 20 分钟"]}
error: --new-fact (a new fact is required to revise a verdict) is required and must not be empty
[exit 1]
error: --verdict must be one of: 在轨 / 轻微偏离 / 走偏
[exit 1]
{"date": "2026-01-21", "previous": "在轨", "verdict": "走偏", "streak": {"drift": 1, "unrecorded": 0, "escalation": false, "threshold": 3, "dnd_dates": []}}
# 2026-01-21
- Daily Levers: 写 500 字; 跑步 20 分钟
- 完成情况: 写了 500 字,跑了步
- 行动偏离: 否 — 两项都完成
- 身份保护: 否 — 没有
- 靠近反愿景: 靠近愿景 — 今天更接近愿景里的周二
- 判定: 在轨
- 判定理由: 两项杠杆都有具体产出

## 21:30:00 再次打卡
- Daily Levers: 写 500 字
- 完成情况: 写了 500 字,跑了步
- 行动偏离: 否 — 两项都完成
- 身份保护: 否 — 没有
- 靠近反愿景: 靠近愿景 — 今天更接近愿景里的周二
- 判定: 在轨
- 判定理由: 晚上又补了一次记录

- 改判: 在轨 → 走偏 — 因 下午发现 500 字其实是复制来的,实际产出为 0 事实改判 (21:30:00)
{"drift": 1, "unrecorded": 0, "escalation": false, "threshold": 3, "dnd_dates": []}
```

### 3.11 连续 3 天走偏:Escalation

1 月 21 日(改判后)已经是走偏。再连续两天走偏,第三天 `escalation` 变为 `true`;之后一天的在轨 Verdict 把 Drift 计数清零并解除 Escalation。

```sh
clock 2026-01-22T21:30:00
ci 走偏 "又没做,和昨天同一个借口" --lever "写 500 字"
lr streak status
clock 2026-01-23T21:30:00
ci 走偏 "第三天,仍然没有任何产出" --lever "写 500 字"
lr streak status
clock 2026-01-24T21:30:00
ci 在轨 "两项都完成" --lever "写 500 字"
lr streak status
```

```output
{"date": "2026-01-22", "file": "log/2026-01-22.md", "verdict": "走偏", "tomorrow_date": "2026-01-23", "tomorrow_levers": ["写 500 字", "跑步 20 分钟"]}
{"drift": 2, "unrecorded": 0, "escalation": false, "threshold": 3, "dnd_dates": []}
{"date": "2026-01-23", "file": "log/2026-01-23.md", "verdict": "走偏", "tomorrow_date": "2026-01-24", "tomorrow_levers": ["写 500 字", "跑步 20 分钟"]}
{"drift": 3, "unrecorded": 0, "escalation": true, "threshold": 3, "dnd_dates": []}
{"date": "2026-01-24", "file": "log/2026-01-24.md", "verdict": "在轨", "tomorrow_date": "2026-01-25", "tomorrow_levers": ["写 500 字", "跑步 20 分钟"]}
{"drift": 0, "unrecorded": 0, "escalation": false, "threshold": 3, "dnd_dates": []}
```

CLI 只负责计数和 `escalation` 标志。Escalation 触发后"引用 Anti-vision 原话追问"是 AI 的行为,CLI 不检查(见第 4 节)。

### 3.12 勿扰日、沉默与 Unrecorded

勿扰日(`dnd`)不要求 Check-in,也永远不算 Unrecorded。其余没打卡的日子,在**下一次交互**时补记一条 `- 未记录`(追加新日志,不改动已有日志)。非法日期被拒绝,重复添加不报错。

```sh
clock 2026-01-25T10:00:00
lr checkin revise-verdict --new-fact "补充" --verdict 走偏
lr dnd list
lr dnd add 2026-01-26
lr dnd add 2026-13-40
lr dnd add 2026-01-26
lr dnd list
```

```output
error: no check-in recorded today: nothing to revise
[exit 1]
{"dnd_dates": []}
{"dnd_dates": ["2026-01-26"]}
error: date must be YYYY-MM-DD
[exit 1]
{"dnd_dates": ["2026-01-26"]}
{"dnd_dates": ["2026-01-26"]}
```

从 1 月 24 日之后,用户 25 日(普通日)、26 日(勿扰日)、27、28 日都没有打卡。27 日上午看:25 日已经是 Unrecorded,26 日不算。

```sh
clock 2026-01-27T10:00:00
lr streak status
cat "$LIFE_REDESIGN_HOME/log/2026-01-25.md"
ls "$LIFE_REDESIGN_HOME/log"
```

```output
{"drift": 0, "unrecorded": 1, "escalation": false, "threshold": 3, "dnd_dates": ["2026-01-26"]}
# 2026-01-25
- 未记录
2026-01-21.md
2026-01-22.md
2026-01-23.md
2026-01-24.md
2026-01-25.md
```

`notify plan` 只是计算推送计划,不发送任何东西。勿扰日的计划为空:

```sh
lr notify plan --date 2026-01-26
```

```output
{"date": "2026-01-26", "pushes": [], "reason": "do-not-disturb date"}
```

到 29 日,25、27、28 日三天未记录,`unrecorded` 达到 3,`escalation` 为 `true`,并且推送计划只剩晚间一条(沉默期)。沉默后回来打卡,CLI 要求先说明这几天发生了什么(`--while-away`)。

```sh
clock 2026-01-29T10:00:00
lr streak status
lr notify plan
ci 在轨 "回来了,两项完成" --lever "写 500 字"
ci 在轨 "回来了,两项完成" --lever "写 500 字" --while-away "出差加感冒,断网四天"
cat "$LIFE_REDESIGN_HOME/log/2026-01-28.md" "$LIFE_REDESIGN_HOME/log/2026-01-29.md"
lr streak status
```

```output
{"drift": 0, "unrecorded": 3, "escalation": true, "threshold": 3, "dnd_dates": ["2026-01-26"]}
{"date": "2026-01-29", "pushes": [{"slot": "evening", "time": "21:30", "text": "该打卡了:花几分钟记录今天。"}], "reason": "silence: unrecorded streak"}
error: you were silent: first say what happened in the missing days (--while-away "...") before checking in
[exit 1]
{"date": "2026-01-29", "file": "log/2026-01-29.md", "verdict": "在轨", "tomorrow_date": "2026-01-30", "tomorrow_levers": ["写 500 字", "跑步 20 分钟"]}
# 2026-01-28
- 未记录
# 2026-01-29
- Daily Levers: 写 500 字
- 完成情况: 写了 500 字,跑了步
- 行动偏离: 否 — 两项都完成
- 身份保护: 否 — 没有
- 靠近反愿景: 靠近愿景 — 今天更接近愿景里的周二
- 判定: 在轨
- 判定理由: 回来了,两项完成
- 这几天发生了什么: 出差加感冒,断网四天
{"drift": 0, "unrecorded": 0, "escalation": false, "threshold": 3, "dnd_dates": ["2026-01-26"]}
```

勿扰日也允许用户自愿打卡,照常记录:

```sh
clock 2026-01-30T08:00:00
lr dnd add 2026-01-30
clock 2026-01-30T21:30:00
ci 在轨 "勿扰日自愿打卡" --lever "写 500 字"
lr streak status
```

```output
{"dnd_dates": ["2026-01-26", "2026-01-30"]}
{"date": "2026-01-30", "file": "log/2026-01-30.md", "verdict": "在轨", "tomorrow_date": "2026-01-31", "tomorrow_levers": ["写 500 字", "跑步 20 分钟"]}
{"drift": 0, "unrecorded": 0, "escalation": false, "threshold": 3, "dnd_dates": ["2026-01-26", "2026-01-30"]}
```

### 3.13 月复盘与年复盘

先用 `plan change` 追加两次计划变更(各带原因),再复盘。复盘命令只读,统计口径:有 Verdict 的天按 Verdict 算;协议完成日及之前不计;勿扰日单独列出;今天及以后算"待定"。

```sh
clock 2026-01-31T21:30:00
lr plan change month-project --text "把原型给 3 个人看并收集反馈" --why "原型不给人看没有反馈"
ci 轻微偏离 "跑步只跑了 5 分钟,但有具体原因:下雨" --lever "写 500 字"
clock 2026-02-01T10:00:00
lr plan change year-goal --text "年底前拿到第一个付费用户" --why "发布产品的范围太大"
lr review month --month 2026-01
lr review month --month 2026-13
```

```output
{"object": "month-project", "date": "2026-01-31", "old": "完成产品原型", "new": "把原型给 3 个人看并收集反馈", "why": "原型不给人看没有反馈", "versions": 4}
{"date": "2026-01-31", "file": "log/2026-01-31.md", "verdict": "轻微偏离", "tomorrow_date": "2026-02-01", "tomorrow_levers": ["写 500 字", "跑步 20 分钟"]}
{"object": "year-goal", "date": "2026-02-01", "old": "年底前发布第一个付费产品", "new": "年底前拿到第一个付费用户", "why": "发布产品的范围太大", "versions": 5}
{"kind": "month", "month": "2026-01", "days_in_period": 31, "days_in_scope": 10, "counts": {"on_track": 3, "minor_drift": 1, "drifted": 3, "unrecorded": 3}, "dnd_days": ["2026-01-26"], "excluded": {"before_activation": 20, "future_or_today_pending": 0, "dnd": 1}, "plan_changes": [{"object": "anti-vision", "date": "2026-01-20", "reason": null}, {"object": "anti-vision", "date": "2026-01-20", "reason": null}, {"object": "goals", "date": "2026-01-20", "reason": null, "sections": ["Year Goal", "Month Project", "Constraints"]}, {"object": "goals", "date": "2026-01-20", "reason": "初始杠杆", "sections": ["Daily Levers"]}, {"object": "vision", "date": "2026-01-20", "reason": null}, {"object": "goals", "date": "2026-01-31", "reason": "原型不给人看没有反馈", "sections": ["Month Project"]}], "plan_unchanged": false, "plan_message": null}
error: --month must be YYYY-MM
[exit 1]
```

核对数字:1 月 21 到 31 日里,在轨 3 天(24、29、30),轻微偏离 1 天(31),走偏 3 天(21 到 23),未记录 3 天(25、27、28),勿扰 1 天(26);20 天在协议完成日(20 日)及之前,不计入。注意 2 月 1 日的 `year-goal` 变更属于 2 月,不在 1 月的 `plan_changes` 里。

保存复盘结论(追加到 `reviews.md`),然后看年复盘:

```sh
lr review save --kind month --period 2026-01 --text "本月最大偏离是 1 月 21 至 23 日连续走偏,原因是身份保护。"
lr review save --kind month --period 2026-1 --text x
lr review save --kind quarter --text x
lr review year --year 2026
cat "$LIFE_REDESIGN_HOME/reviews.md"
```

```output
{"kind": "month", "period": "2026-01", "date": "2026-02-01", "file": "reviews.md", "reviews": 1}
error: --period must be YYYY-MM
[exit 1]
usage: life_redesign review save [-h] --kind {month,year} [--period PERIOD]
                                 [--text TEXT]
life_redesign review save: error: argument --kind: invalid choice: 'quarter' (choose from 'month', 'year')
[exit 2]
{"kind": "year", "year": 2026, "days_in_period": 365, "days_in_scope": 10, "counts": {"on_track": 3, "minor_drift": 1, "drifted": 3, "unrecorded": 3}, "dnd_days": ["2026-01-26"], "excluded": {"before_activation": 20, "future_or_today_pending": 334, "dnd": 1}, "year_goal_history": [{"date": "2026-01-20", "text": "第三部分答案 3.5", "reason": "来自一天协议"}, {"date": "2026-01-20", "text": "年底前发布第一个付费产品", "reason": null}, {"date": "2026-02-01", "text": "年底前拿到第一个付费用户", "reason": "发布产品的范围太大"}], "plan_changes": [{"object": "anti-vision", "date": "2026-01-20", "reason": null}, {"object": "anti-vision", "date": "2026-01-20", "reason": null}, {"object": "goals", "date": "2026-01-20", "reason": null, "sections": ["Year Goal", "Month Project", "Constraints"]}, {"object": "goals", "date": "2026-01-20", "reason": "初始杠杆", "sections": ["Daily Levers"]}, {"object": "vision", "date": "2026-01-20", "reason": null}, {"object": "goals", "date": "2026-01-31", "reason": "原型不给人看没有反馈", "sections": ["Month Project"]}, {"object": "goals", "date": "2026-02-01", "reason": "发布产品的范围太大", "sections": ["Year Goal"]}], "offer_redo_protocol": true}
## 2026-02-01 月复盘 2026-01
本月最大偏离是 1 月 21 至 23 日连续走偏,原因是身份保护。
```

年复盘的 `offer_redo_protocol: true` 表示要询问用户是否重做一天协议;用户可以拒绝。重做必须显式 `protocol redo`:

```sh
lr protocol redo
lr protocol redo
```

```output
{"phase": "active", "redo": true, "part": 1, "question": "1.1", "answered": 0, "total": 22, "feeling_check_required": false}
error: a redo is already in progress; use `protocol resume`
[exit 1]
```

### 3.14 状态快照与更新块(B 档)

没有文件和 shell 的聊天 App 里,用户先粘贴状态快照,对话结束后把 AI 输出的更新块贴回本地。`snapshot` 导出快照:

```sh
lr snapshot
```

```output
{"generated": "2026-02-01T10:00:00", "vision": "三年后的周二:我在自己的工作室醒来,身体轻盈。我是那种说到做到的人。", "anti_vision": "(第二版)十年后我仍在原地,没有人记得我做过什么。", "goals": {"Year Goal": "年底前拿到第一个付费用户", "Month Project": "把原型给 3 个人看并收集反馈", "Constraints": "不牺牲睡眠和家人时间", "Daily Levers": "写 500 字\n跑步 20 分钟"}, "verdicts": [{"date": "2026-01-29", "verdict": "在轨"}, {"date": "2026-01-30", "verdict": "在轨"}, {"date": "2026-01-31", "verdict": "轻微偏离"}], "streak": {"drift": 0, "unrecorded": 0, "escalation": false}}
```

更新块从标准输入读(也可以 `lr apply-block --file 文件名`)。`create` 新建文件,`append` 追加到已有文件。多个块先整体校验,全部合法才写入。

```sh
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: log/2026-02-01-note.md
mode: create
---
今天在聊天 App 里复盘了一遍。
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: log/2026-02-01-note.md
mode: create
---
再创建一次
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: log/2026-02-01-note.md
mode: append
---
补充一句。
=== END ===
EOF
cat "$LIFE_REDESIGN_HOME/log/2026-02-01-note.md"
```

```output
{"applied": [{"file": "log/2026-02-01-note.md", "mode": "create"}]}
error: block 1: cannot create log/2026-02-01-note.md: file already exists (use mode: append)
[exit 1]
{"applied": [{"file": "log/2026-02-01-note.md", "mode": "append"}]}
今天在聊天 App 里复盘了一遍。
补充一句。
```

对 `vision.md`、`anti-vision.md`、`goals.md` 的 `append` 块是追加一个新的带日期版本(CLI 写标题),`goals.md` 的块必须按小节写,没写的小节会从当前版本带过来:

```sh
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: goals.md
mode: append
---
### Month Project
做出可收费的第一版
=== END ===
EOF
tail -14 "$LIFE_REDESIGN_HOME/goals.md"
```

```output
{"applied": [{"file": "goals.md", "mode": "append"}]}

## 2026-02-01
### Year Goal
年底前拿到第一个付费用户

### Month Project
做出可收费的第一版

### Constraints
不牺牲睡眠和家人时间

### Daily Levers
写 500 字
跑步 20 分钟
```

### 3.15 更新块的各种非法形式

下面每一块都应被拒绝,且**不写入任何东西**。

`replace` 和 `delete` 模式、对已存在文件 `create`:

```sh
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: vision.md
mode: replace
---
x
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: vision.md
mode: delete
---
x
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: vision.md
mode: create
---
x
=== END ===
EOF
```

```output
error: block 1: mode 'replace' not allowed; only create or append (records are append-only, ADR-0001)
[exit 1]
error: block 1: mode 'delete' not allowed; only create or append (records are append-only, ADR-0001)
[exit 1]
error: block 1: cannot create vision.md: file already exists (use mode: append)
[exit 1]
```

越出数据目录、不允许的目标文件、对不存在的日志 `append`、空内容:

```sh
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: ../outside.md
mode: create
---
x
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: /etc/passwd
mode: append
---
x
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: state.json
mode: append
---
x
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: log/2026-02-09.md
mode: append
---
x
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: log/2026-02-02.md
mode: create
---

=== END ===
EOF
```

```output
error: block 1: path '../outside.md' is outside the data dir or malformed
[exit 1]
error: block 1: path '/etc/passwd' is outside the data dir or malformed
[exit 1]
error: block 1: file 'state.json' is not an allowed target (vision.md, anti-vision.md, goals.md, log/*.md, protocol/*.md)
[exit 1]
error: block 1: cannot append to log/2026-02-09.md: file does not exist (use mode: create)
[exit 1]
error: block 1: body is empty
[exit 1]
```

格式残缺:缺结束行、缺 `mode`、缺 `---` 分隔行、缺 `file`、完全没有块:

```sh
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: log/2026-02-02.md
mode: create
---
没有结束行
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: log/2026-02-02.md
---
x
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: log/2026-02-02.md
mode: create
x
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
mode: create
---
x
=== END ===
EOF
echo "只是一段普通文字" | lr apply-block
```

```output
error: block 1: missing '=== END ===' terminator
[exit 1]
error: block 1: missing 'mode' header
[exit 1]
error: block 1: unrecognised header line 'x' (headers are 'file:' and 'mode:', then a '---' line)
[exit 1]
error: block 1: missing 'file' header
[exit 1]
error: no update block found (expected '=== LIFE-REDESIGN UPDATE ===' ... '=== END ===')
[exit 1]
```

追加式文件里伪造版本标题或未知小节,以及一次提交多个块时只要有一个非法就整批不写入(第一块合法,第二块用了 `replace`,第一块指定的日志文件最终没有出现):

```sh
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: vision.md
mode: append
---
## 2020-01-01
伪造的旧版本
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: goals.md
mode: append
---
### Hobbies
x
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: goals.md
mode: append
---
没有小节标题
=== END ===
EOF
lr apply-block <<'EOF'
=== LIFE-REDESIGN UPDATE ===
file: log/2026-02-03.md
mode: create
---
合法的第一块
=== END ===
=== LIFE-REDESIGN UPDATE ===
file: vision.md
mode: replace
---
x
=== END ===
EOF
ls "$LIFE_REDESIGN_HOME/log" | tail -3
lr apply-block --file /tmp/no-such-file.txt
```

```output
error: block 1 body contains a version/section heading line ('## 2020-01-01'); headings are written only by the CLI
[exit 1]
error: block 1: unknown goals section 'Hobbies'
[exit 1]
error: block 1: goals content must be under a '### Year Goal|Month Project|Daily Levers|Constraints' section
[exit 1]
error: block 2: mode 'replace' not allowed; only create or append (records are append-only, ADR-0001)
[exit 1]
2026-01-30.md
2026-01-31.md
2026-02-01-note.md
error: cannot read /tmp/no-such-file.txt: [Errno 2] No such file or directory: '/tmp/no-such-file.txt'
[exit 1]
```

## 4. 只能人工试用的部分

CLI 记录事实、计数、拒绝非法写入,但下面这些靠模型和真实环境,没有自动化断言,需要人工试:

- **提问质量**:用户答得空泛时 AI 是否追问具体细节;Verdict 是否严格、是否附了站得住的理由;用户反驳时,没有新事实是否维持原判(CLI 只保证"改判必须带 `--new-fact`",不判断那条事实是否真的是新事实)。
- **Escalation 的追问内容**:`escalation` 为 `true` 时,AI 是否引用 Anti-vision 原话追问、是否询问调整 Month Project。
- **Part 2 白天的 Interrupt**:六条固定问题在协议当天按固定时间推送,回答记在协议文件里;CLI 没有命令记录它们。
- **隔夜感受**:`confirm-feeling fresh|faded` 只是记录你的选择,"感受是否还在"需要你自己判断。
- **危机优先**:出现自伤迹象时停止按协议追问(行为准则,不可自动测)。
- **B 档聊天全程**:模型能否按格式写出合法的更新块,用户粘贴时有没有改动格式。
- **真实 launchd 与真实通知**:安装计划任务、系统通知实际弹出、`claude -p` 生成晚间提醒文案,都不在本指南范围,见另一份文档。

## 5. 清理

流程结束后删除测试数据目录,并取消注入时间,免得影响之后的真实使用:

```sh
case "$LIFE_REDESIGN_HOME" in /tmp/life-redesign-e2e) rm -rf "$LIFE_REDESIGN_HOME" ;; esac
unset LIFE_REDESIGN_HOME LIFE_REDESIGN_NOW
ls /tmp/life-redesign-e2e 2>&1
```

```output
ls: /tmp/life-redesign-e2e: No such file or directory
```
