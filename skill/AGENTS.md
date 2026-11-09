# Life Redesign — Agent 入口

适用于 Codex CLI、Gemini CLI、Cursor、opencode、Qwen Code 等能运行 shell 命令的 agent。

当用户提到重建人生、年度目标、反愿景、每日打卡、走偏、life redesign,或要求 `start` / `checkin` / `review` / `plan` / `notify` 时:

1. **先完整读取 [PROTOCOL.md](./PROTOCOL.md)**,它是唯一的协议来源。
2. 所有读写都通过随 skill 分发的命令行,**不要直接编辑数据目录里的任何文件**(见下)。
3. 先运行 `LR init`;若返回 `privacy_required: true`,先告知隐私并取得确认,再 `LR ack-privacy`。
4. 按 PROTOCOL 对应章节执行入口流程。

## 命令行与调用方式

命令行是 `scripts/life_redesign.py`(Python 3 标准库)。`<skill_dir>` 是**包含这份 AGENTS.md 的目录**(skill 目录被复制或软链接到哪里,脚本跟到哪里)。你的当前目录通常是用户的项目,所以**始终用绝对路径**调用,不要写相对路径,不要依赖 `cd` 或 shell 变量:

```
python3 "<skill_dir>/scripts/life_redesign.py" <命令> [参数]
```

下文简写为 `LR`。成功时标准输出一行 JSON;失败时退出码 1、标准错误 `error: <原因>`,且什么都没写入。

**禁止直接编辑数据目录 `~/.life-redesign/`(或 `$LIFE_REDESIGN_HOME`)里的任何文件**(`state.json`、`*.md`、`protocol/`、`log/`、`levers.jsonl` 等)。直接改会绕过追加式保护、Streak 计算、门禁和 Verdict 规则。命令行没有的操作就是不允许的操作;报错时读懂原因、补齐前置条件、如实告诉用户。

## 入口与命令

未指定入口时,`LR protocol status` 读 `phase`:`new` / `protocol_shelved` / `protocol_in_progress` → `start`;`active` → 今天没打卡则 `checkin`,否则问用户。

| 入口 | 主要命令(详见 PROTOCOL 对应章节) |
|---|---|
| `start`(第 5 节) | `LR protocol status` / `resume` / `redo`;`LR protocol answer <题号> --text "<原话>"`(题号 1.1–1.14、3.1–3.7、3.constraints,按序);`LR protocol confirm-feeling fresh\|faded`;`LR append anti-vision\|vision --text`、`LR append goals --year-goal/--month-project/--constraints`、`LR plan change daily-levers --text --why` |
| `checkin`(第 6 节) | `LR show anti-vision\|vision\|goals`;`LR checkin levers`;`LR streak status`;`LR checkin record --lever --levers-done --action-drift --action-reason --identity-protection --identity-reason --toward --toward-reason --verdict --verdict-reason --tomorrow-lever [--while-away]`;`LR checkin revise-verdict --new-fact --verdict` |
| `review`(第 8 节) | `LR review month` / `year`;`LR review save --kind month\|year --text`;`LR plan change ...` |
| `plan`(第 7 节) | `LR show ...`;`LR plan change <vision\|anti-vision\|year-goal\|month-project\|daily-levers\|constraints> --text --why` |
| `notify`(第 9 节) | `LR notify config` / `plan` / `fire <slot> --dry-run` / `install` / `uninstall`;`LR dnd list\|add\|remove <日期>` |

## 怎样把用户的回答交给命令行

答案类参数(`--text`、`--levers-done`、`--while-away`、`--tomorrow-lever`、`--new-fact`、`--why` 等)传**用户自己的原话**,不改写、不润色、不总结、不替用户补全。答案敷衍就追问到具体再记录。判定和各项评估由你基于用户陈述的事实给出。

## 不可违反的规则(完整版见 PROTOCOL 第 0 节)

- 不替用户写答案、愿景、身份宣言;答案敷衍就追问。
- 评判严格,不迎合;判定必须附理由;只有新事实才改判。
- 只追加、不覆盖、不删除。
- 出现危机迹象时停止按协议追问,建议寻求专业帮助。
- 通知不含私人内容;无头(后台)调用只读不写,不产生判定。
- 无 shell 的纯聊天 App:用 `LR snapshot` 的快照开聊,结束时产出更新块,由用户 `LR apply-block` 应用(PROTOCOL 第 10 节)。
