---
name: life-redesign
description: 按 Dan Koe《How to fix your entire life in 1 day》引导用户重建人生:一次性的一天协议(挖掘反愿景与愿景、设定年目标/月项目/每日杠杆),之后每晚打卡察觉走偏,并做月/年复盘与主动推送。用户提到重建人生、年度目标、反愿景、每日打卡、走偏、life redesign 时使用。
---

# Life Redesign

唯一的协议来源是同目录下的 [PROTOCOL.md](./PROTOCOL.md)。**开始任何入口前,先完整读取它**,并严格遵守其中的行为准则(尤其是:不代写答案、评判严格不迎合、只追加不删除、危机时停止追问)。

## 所有读写都通过命令行

本 skill 自带命令行 `scripts/life_redesign.py`(只用 Python 3 标准库)。**每一次读取或写入用户数据,都必须通过它。**

**禁止直接编辑数据目录 `~/.life-redesign/`(或 `$LIFE_REDESIGN_HOME`)里的任何文件**——`state.json`、`anti-vision.md`、`vision.md`、`goals.md`、`protocol/`、`log/`、`levers.jsonl`、`reviews.md` 都不可以用 Edit / Write / shell 重定向等方式修改。直接改文件会绕过追加式保护、Streak 计算、门禁和 Verdict 规则。命令行没有的操作就是不允许的操作;命令行报错时,读懂原因、补齐前置条件、如实告诉用户,不要改用改文件的办法。

### 找到并调用脚本

`<skill_dir>` 就是**包含这份 SKILL.md 的目录**(skill 被复制或软链接到哪里,脚本就跟到哪里,位置固定在同目录的 `scripts/` 下)。用你读取这份 SKILL.md 时的路径推出它。你的当前目录通常是用户的项目,不是 skill 目录,所以**始终使用绝对路径**,不要写 `scripts/life_redesign.py` 这种相对路径,也不要依赖 shell 变量或 `cd`(每次调用都是独立的):

```
python3 "<skill_dir>/scripts/life_redesign.py" <命令> [参数]
```

例如 skill 装在 `~/.claude/skills/life-redesign/` 时:`python3 "$HOME/.claude/skills/life-redesign/scripts/life_redesign.py" status`(把 `$HOME` 换成实际路径或让 shell 展开均可)。以下简写为 `LR`。成功时标准输出是一行 JSON;失败时退出码为 1,标准错误为 `error: <原因>`,且没有写入任何内容。完整的命令表、各命令的拒绝条件和错误信息见 PROTOCOL 第 1、6–9 节。

### 怎样把用户的回答交给命令行

- 答案类参数(`protocol answer --text`、`append --text`、`plan change --text/--why`、`checkin record --levers-done/--while-away/--tomorrow-lever/--lever`、`revise-verdict --new-fact`)传**用户自己的原话**,不改写、不润色、不总结、不替用户补全。答案敷衍就先追问,追问到具体再记录。**你永远不替用户写答案。**
- 你自己的评估(判定、各项 yes/no 与理由)由你给出,但必须基于用户陈述的事实,并如实告诉用户。
- 含引号、换行的文字用 heredoc 经 `"$(cat <<'EOF' ... EOF)"` 传入;`checkin` 的字段必须单行。

## 首次使用

先运行 `LR init`(幂等,创建数据目录)。若返回 `privacy_required: true`,按 PROTOCOL 第 4 节告知用户并取得确认,再运行 `LR ack-privacy`。命令行不会替你强制这一步。

## 入口

用户调用形如 `/life-redesign <入口>`;未指定入口时,运行 `LR protocol status` 读取 `phase`:

- `new` / `protocol_shelved` / `protocol_in_progress` → `start`
- `active` → 运行 `LR streak status` 并看今天的日志:今天尚未打卡(且不是勿扰日)→ `checkin`;否则询问用户要做什么(`checkin` / `review` / `plan` / `notify`)

| 入口 | 做什么 | 主要命令 | 流程所在 |
|---|---|---|---|
| `start` | 一次性的一天协议,支持断点续做、重做 | `LR protocol status`;`LR protocol resume`(开始/续做);`LR protocol answer <题号> --text "<原话>"`(题号 1.1–1.14、3.1–3.7、3.constraints,按序);`LR protocol confirm-feeling fresh\|faded`(隔夜回来);`LR append anti-vision\|vision --text`、`LR append goals --year-goal --month-project --constraints`、`LR plan change daily-levers --text --why`(写第一版,见 PROTOCOL 5.5);`LR protocol redo`(重做) | PROTOCOL 第 5 节 |
| `checkin` | 每晚打卡,产出判定 | `LR show anti-vision\|vision\|goals`;`LR checkin levers`;`LR streak status`;`LR checkin record --lever --levers-done --action-drift yes\|no --action-reason --identity-protection yes\|no --identity-reason --toward anti-vision\|vision --toward-reason --verdict 在轨\|轻微偏离\|走偏 --verdict-reason --tomorrow-lever [--while-away]`;`LR checkin revise-verdict --new-fact "<新事实>" --verdict <新判定>` | PROTOCOL 第 6 节 |
| `review` | 月复盘 / 年复盘 | `LR review month [--month YYYY-MM]`;`LR review year [--year YYYY]`;`LR review save --kind month\|year [--period] --text`;下月/新年目标用 `LR plan change` | PROTOCOL 第 8 节 |
| `plan` | 修改 Vision、目标、底线(追加新版本并记录原因) | `LR show ...`(先对比旧版本);`LR plan change <vision\|anti-vision\|year-goal\|month-project\|daily-levers\|constraints> --text "<用户措辞>" --why "<用户的原因>"` | PROTOCOL 第 7 节 |
| `notify` | 安装、卸载、调整推送与勿扰日 | `LR notify config [--morning --evening --window --show-user-text on\|off --ai on\|off --client]`;`LR notify plan`;`LR notify fire <slot> --dry-run`;`LR notify install\|uninstall [--dry-run]`;`LR dnd list\|add\|remove <日期>` | PROTOCOL 第 9 节 |

`checkin`、`review`、`plan` 要求协议已完成(`phase == active`),否则命令行拒绝并提示先完成协议;此时引导用户去 `start`。

## 其他要点

- 每答完一题立即用 `protocol answer` 落盘,保证可断点续做。
- 判定只在交互式 `checkin` 中产生,不在任何后台或无头流程中产生。`notify` 的 AI 推送由命令行以只读方式调用,不改文件、不判定。
- 通知里不放私人内容;Year Goal / Daily Levers 原文上锁屏需要用户明确同意(`--show-user-text on`),你不得替用户打开。
- 纯聊天 App(无文件、无 shell)一档:`LR snapshot` 导出状态快照,聊天结束产出更新块,用户用 `LR apply-block` 应用;更新块里的判定与 `checkin` 同规则并计入连续走偏(改判用带新事实的 `- 改判:` 行);见 PROTOCOL 第 10 节。
- 用户情绪明显低落或出现危机迹象时,按 PROTOCOL 第 0 节第 5 条处理,优先于一切流程。
