# Life Redesign

一套让 AI 当"提问者和镜子"的人生重建工具:用一天时间挖出你不想要的生活和想要的生活,落成年目标、月项目和每日杠杆,之后每晚打卡,由 AI 严格地察觉你有没有走偏。

方法来自 Dan Koe 的文章 [How to fix your entire life in 1 day](https://x.com/thedankoe/status/2010751592346030461)。思路和问题都归功于原作者;本仓库不转载原文,请直接读原文。本项目只是把它做成一个可重复使用的引导流程(仓库里的 [docs/how-to-fix-your-entire-life-in-1-day.md](./docs/how-to-fix-your-entire-life-in-1-day.md) 是设计时参考的文本,以原帖为准)。

## 它解决什么问题

重建人生的文章读完很容易,难的是三件事:当天真的把答案写下来;之后每天对照它,而不是悄悄降低标准;走偏时有人指出来。Life Redesign 把这三件事做成流程:

- **一天协议(One-Day Protocol)**:早上挖掘(Excavation)、白天打断(Interrupt)、晚上综合(Synthesis),产出 Anti-vision(反愿景)、Vision(愿景)、Year Goal(年目标)、Month Project(月项目)、Daily Levers(每日杠杆)和 Constraints(底线)的第一版。
- **每晚 Check-in(打卡)**:逐项审问行动偏离、身份保护、靠近反愿景(合称 Drift,走偏),给出一条 Verdict(判定):在轨、轻微偏离、走偏,必须附理由。
- **察觉与复盘**:连续 3 天走偏或连续 3 天未记录(Unrecorded),触发 Escalation(升级追问);按月、按年复盘,用旧版本核对你的言行。
- **主动推送**:macOS 上可选的系统通知,默认只显示预写的问题。

术语的准确定义见 [GLOSSARY.md](./GLOSSARY.md)。

## 它不是什么

- **不是心理治疗工具。** 它是自我反思工具。出现自伤、自杀念头或严重抑郁迹象时,协议要求 AI 停止追问,建议你联系专业人士或当地危机热线。
- **AI 不会替你写答案。** 愿景、反愿景、目标、身份宣言都必须是你自己的话;答得敷衍,它会追问到具体。命令行记录的是你的原话。
- **判定是严格的,不是鼓励。** "在想""差不多""准备做"都不算完成;你反驳时,只有出现新的、可核对的事实才会改判,情绪和解释不算。
- **不是日记或待办软件。** 打卡的产出是判定,不是流水账。

## 安装

安装的就是仓库里的 `skill/` 目录:它自包含(协议、入口文件、命令行脚本、聊天 App 提示词包都在里面),只需要 Python 3.9 或更新版本(命令行只用标准库)。**不提供一键安装的 plugin**,请按下面的方式复制或软链接。

先克隆本仓库,假设克隆在 `~/life-redesign`:

```sh
git clone https://github.com/NoahStepheno/life-redesign.git ~/life-redesign
```

### Claude Code

把 `skill/` 目录复制或软链接成一个名为 `life-redesign` 的 skills 目录:[skill/SKILL.md](./skill/SKILL.md) 和 [skill/prompts/README.md](./skill/prompts/README.md) 的示例路径都是 `~/.claude/skills/life-redesign/`。

```sh
mkdir -p ~/.claude/skills
ln -s ~/life-redesign/skill ~/.claude/skills/life-redesign
# 或复制:cp -R ~/life-redesign/skill ~/.claude/skills/life-redesign
```

之后在 Claude Code 里用 `/life-redesign start`(或其他入口,见下文)。脚本位置固定在 skill 目录下的 `scripts/life_redesign.py`,skill 被复制或链接到哪里,它就跟到哪里。

### 其他 agent(Codex CLI、Gemini CLI、Cursor、opencode、Qwen Code 等)

凡是能运行 shell 命令的 agent,用 [skill/AGENTS.md](./skill/AGENTS.md) 作入口:把整个 `skill/` 目录放到你的 agent 能读到的位置(各家的具体目录和加载方式不同,请查对应文档,本仓库不替它们担保),并在该 agent 的指令文件里让它在用户提到重建人生、年度目标、反愿景、每日打卡、走偏时先读取 `AGENTS.md`。`AGENTS.md` 会指向唯一的协议来源 [skill/PROTOCOL.md](./skill/PROTOCOL.md)。

### 纯聊天 App(ChatGPT、豆包、DeepSeek 等)

聊天 App 看不到你的文件、不能运行命令,用法不同:你在聊天开头粘贴一份提示词,再粘贴本机导出的"状态快照";聊完让它输出"更新块",由你在本机用命令行应用。完整步骤见 [skill/prompts/README.md](./skill/prompts/README.md),提示词在 [skill/prompts/system-prompt.md](./skill/prompts/system-prompt.md)。注意:这条路径不做一天协议,需要先在有命令行的环境里完成。

## 五分钟上手:从开始协议到第一次打卡

下面用命令行直接演示。日常使用时由 agent 替你调用这些命令,你只需要回答问题;这里写出来是让你看清每一步发生了什么。为了先试用,可以让数据目录指向一个临时位置(不设置则默认 `~/.life-redesign/`):

```sh
export LIFE_REDESIGN_HOME=/tmp/lr-try
LR="$HOME/.claude/skills/life-redesign/scripts/life_redesign.py"   # 换成你的实际安装路径
```

1. 初始化并确认隐私告知(见下文"隐私"):

   ```sh
   python3 "$LR" init
   python3 "$LR" ack-privacy
   ```

   `init` 在全新环境里输出 `{"phase": "new", "privacy_required": true, ...}`,`ack-privacy` 之后 `privacy_required` 变为 `false`。确认这一步是 agent 的责任,命令行不会强制(见"已知限制")。

2. 开始一天协议:

   ```sh
   python3 "$LR" protocol resume
   ```

   输出 `{"phase": "protocol_in_progress", "question": "1.1", "answered": 0, "total": 22, ...}`。`protocol status` 随时可查进度。

3. 逐题回答,共 22 题(1.1–1.14、3.1–3.7、3.constraints),必须按顺序,每答一题就落盘:

   ```sh
   python3 "$LR" protocol answer 1.1 --text "你自己的原话"
   ```

   问题全文在 [skill/PROTOCOL.md](./skill/PROTOCOL.md) 第 5 节:早上挖掘是 Part 1,白天打断是 Part 2(没有题号,不通过命令行作答),晚上综合是 Part 3。这是为一整天设计的流程,中途可以停:当天继续;隔夜回来会先问"那天的感受还在吗?"(`protocol confirm-feeling fresh|faded`);超过 7 天未完成则搁置、旧答案被标记归档(不删除)。

4. 答完 `3.constraints`,`phase` 变为 `active`,命令行把你的原话原样写成第一版 `anti-vision.md`、`vision.md`、`goals.md`:

   ```sh
   python3 "$LR" show goals
   ```

5. 第一次打卡。先 `python3 "$LR" checkin levers` 读今天的 Daily Levers(首次为空列表,杠杆取自 `show goals` 的 Daily Levers 小节),再逐项对照并记录:

   ```sh
   python3 "$LR" checkin record \
     --lever "写 500 字" \
     --levers-done "写了 520 字" \
     --action-drift no --action-reason "杠杆完成" \
     --identity-protection no --identity-reason "没有这类行为" \
     --toward vision --toward-reason "今天做的事更接近 Vision" \
     --verdict 在轨 --verdict-reason "杠杆完成,无身份保护" \
     --tomorrow-lever "写 500 字"
   ```

   实际输出:`{"date": "2026-11-10", "file": "log/2026-11-10.md", "verdict": "在轨", "tomorrow_date": "2026-11-11", "tomorrow_levers": ["写 500 字"]}`。
   
   在真实使用中,`--levers-done` 与各项原话来自你;各项 yes/no、理由和判定由 AI 基于你陈述的事实给出,并如实告诉你。同一天再打一次卡时判定若不同,会被拒绝,必须带新事实用 `checkin revise-verdict --new-fact ... --verdict ...` 改判。

上面的命令序列已在一个一次性的数据目录里实际跑通(22 题用占位答案)。

## 五个入口

一个 skill、多个入口,共享同一份数据目录和同一份协议。在 Claude Code 里写成 `/life-redesign <入口>`;未指定入口时,agent 读 `protocol status` 的 `phase` 自行判断。

| 入口 | 做什么 | 参考 |
|---|---|---|
| `start` | 一次性的一天协议,支持断点续做和重做 | [PROTOCOL 第 5 节](./skill/PROTOCOL.md) |
| `checkin` | 每晚打卡,产出判定 | PROTOCOL 第 6 节 |
| `review` | 月复盘、年复盘 | PROTOCOL 第 8 节 |
| `plan` | 修改 Vision、目标、底线(追加新版本并记录原因) | PROTOCOL 第 7 节 |
| `notify` | 安装、卸载、调整推送与勿扰日 | PROTOCOL 第 9 节 |

`checkin`、`review`、`plan` 要求一天协议已完成(`phase` 为 `active`),否则命令行拒绝。

## 命令行总览

调用形式:`python3 <skill 目录>/scripts/life_redesign.py <命令> [参数]`。成功时退出码 0、标准输出一行 JSON;失败时退出码 1、标准错误 `error: <原因>`,并且什么都没有写入。以下与 `--help` 一致,各命令的拒绝条件见 [skill/PROTOCOL.md](./skill/PROTOCOL.md) 第 1、5–10 节。

| 命令 | 作用 |
|---|---|
| `init [--ack-privacy]` | 创建数据目录和初始状态(幂等) |
| `ack-privacy` | 记录已确认隐私告知 |
| `status` / `now` | 看阶段与隐私状态 / 看命令行当前使用的时间 |
| `protocol status` / `resume` / `redo` / `gate` | 协议进度 / 开始或续做 / 重做 / 门禁检查 |
| `protocol answer <题号> --text "..."` | 记录一题答案 |
| `protocol confirm-feeling fresh\|faded` | 隔夜回来后确认感受还在不在 |
| `show anti-vision\|vision\|goals` | 查看全部版本,当前版本是最后一个 |
| `append anti-vision\|vision --text "..."` | 追加新版本(第一版由协议自动写入) |
| `append goals [--year-goal ...] [--month-project ...] [--constraints ...]` | 追加目标新版本 |
| `plan change <anti-vision\|vision\|year-goal\|month-project\|daily-levers\|constraints> --text "..." --why "..."` | 修改计划:追加新版本并记录原因 |
| `checkin levers [--date YYYY-MM-DD]` | 读某天的 Daily Levers |
| `checkin record --lever ... --levers-done ... --action-drift yes\|no --action-reason ... --identity-protection yes\|no --identity-reason ... --toward anti-vision\|vision --toward-reason ... --verdict 在轨\|轻微偏离\|走偏 --verdict-reason ... --tomorrow-lever ... [--while-away ...]` | 记录今晚打卡与判定,设置明天的 Daily Levers(`--lever`、`--tomorrow-lever` 可重复) |
| `checkin revise-verdict --new-fact "..." --verdict ...` | 因新事实改判 |
| `streak status` | 读连续走偏、未记录和升级状态 |
| `dnd list` / `dnd add <日期>` / `dnd remove <日期>` | 管理勿扰日 |
| `review month [--month YYYY-MM]` / `review year [--year YYYY]` | 读复盘数据(只读) |
| `review save --kind month\|year [--period ...] --text "..."` | 保存复盘结论 |
| `notify config [--morning HH:MM] [--evening HH:MM] [--window 起 止] [--show-user-text on\|off] [--ai on\|off] [--client "<命令>"]` | 读或改推送设置 |
| `notify plan [--date YYYY-MM-DD]` | 某天的推送计划与文案(只读) |
| `notify fire morning\|random\|evening [--dry-run] [--tick]` | 发送(或预览)一条通知;`--tick` 供定时任务轮询用 |
| `notify install [--dry-run]` / `notify uninstall [--dry-run]` | 注册 / 卸载 macOS launchd 任务 |
| `snapshot` | 聊天 App 用:导出状态快照 |
| `apply-block [--file 文件]` | 聊天 App 用:应用更新块(文件或标准输入) |

## 推送(可选,仅 macOS)

默认每天最多 3 条:08:30(今天的 Daily Levers 入口)、11:00–17:00 随机一条打断问题、21:30 打卡提醒。协议完成前和勿扰日不推送;连续 3 天未记录后只保留晚间一条。先预览再安装:

```sh
python3 "$LR" notify plan
python3 "$LR" notify install --dry-run
```

要点:

- 推送由 macOS launchd 的三个任务实现,`notify install` 会向 `~/Library/LaunchAgents/` 写入三个 plist 并注册。
- **plist 里记录的是 Python 和脚本当时的绝对路径。** 不要在临时目录或 git worktree 里执行 `notify install`;skill 目录被移动后,以及修改了 `--morning` / `--evening`(`reinstall_required` 为 `true`)后,都要重新 `notify install`。
- 所有推送尝试都在数据目录的 `push.log` 追加一行结果(`sent`、`dry-run`、`skipped` 或 `failed`),不含任何用户原文;卸载不会删除它。
- AI 参与的晚间推送默认关闭,需要你同意后 `notify config --ai on`;它以只读方式调用无头客户端(默认 `claude -p`),不改文件、不产生判定,不可用时退化为固定文案。

## 数据目录与"只追加、不删除"

数据默认在 `~/.life-redesign/`,可用环境变量 `LIFE_REDESIGN_HOME` 指定别处。都是纯文本:

```
~/.life-redesign/
├── state.json                    # 协议进度、推送配置、计数(机器状态)
├── anti-vision.md                # 追加式,每个版本带日期
├── vision.md                     # 追加式
├── goals.md                      # Year Goal、Month Project、Daily Levers、Constraints,追加式
├── protocol/YYYY-MM-DD.md        # 一天协议的答案
├── log/YYYY-MM-DD.md             # 每日日志:杠杆完成情况、判定、理由
├── levers.jsonl                  # 每次打卡设置的"明天的 Daily Levers"
├── reviews.md                    # 保存的复盘结论
└── push.log                      # 推送结果(使用推送后出现)
```

**只追加、不覆盖、不删除。** 每次修改写入一个带日期的新版本,当前版本取最后一段,旧版本永不改写。这样复盘时才能拿三个月前的原话核对你今天的说法,而不是让你悄悄降低标准(原因见 [ADR-0001](./docs/adr/0001-append-only-records.md))。命令行不提供任何删除、覆盖操作。唯一会改动文件名的情形,是协议片段被标记为 `.archived.md`(搁置)或 `.discarded.md`(隔夜后你确认感受已淡去),内容原样保留。想归档整个数据目录,请自己把目录改名。

**不要直接编辑数据目录里的文件**(包括让 agent 去改)。直接改会绕过追加保护、连续走偏的计算、门禁和判定规则;需要改计划,用 `plan change`。([docs/design.md](./docs/design.md) 里写着数据"可手改",以 [skill/SKILL.md](./skill/SKILL.md) 和 PROTOCOL 的禁止为准。)

## 隐私

> 你的所有记录只存在本机 `~/.life-redesign/`,不会被上传到任何服务器。但对话内容,以及无头推送时读取的日志,会发送给你所选的模型服务商。系统通知里只会出现预写的问题,不会出现你的私人内容。

(这是协议第 4 节要求首次使用时告知的文字。)补充说明:

- 数据只存在本机。但你和 agent 或聊天 App 的对话内容会发给你所选的模型服务商;开启 AI 推送后,无头客户端读取的近 7 天日志也会发给服务商。
- 通知默认只有预写的问题或"打开查看今日杠杆"。Year Goal、Daily Levers 的原文上锁屏需要你明确同意(`notify config --show-user-text on`),默认关闭,agent 不应替你打开。
- `push.log` 永远不含用户原文。

## 已知限制

- **推送从未在真机上跑过。** 自动化测试只用 `--dry-run` 和假的 `launchctl`;真实流程见 [docs/testing/macos-push-smoke.md](./docs/testing/macos-push-smoke.md),尚未执行。因此"通知真的会弹出"目前没有验证。
- **聊天 App 提示词包没有在真实聊天 App 里试过。**
- **Agent 的行为(追问是否够具体、判定是否严格、会不会代笔、危机时是否停下)从未被人工验证。** 试用清单 [docs/testing/agent-trial-checklist.md](./docs/testing/agent-trial-checklist.md) 没有被走过。命令行的门禁、追加保护、必填项等有自动化测试,见 [docs/testing/cli-e2e.md](./docs/testing/cli-e2e.md)。
- 仅 macOS 支持推送(launchd);Linux 和 Windows 的推送暂不支持。命令行本身只需 Python 3.9+ 标准库。
- 三个未决的问题,仍是 open issue:
  - [#19](https://github.com/NoahStepheno/life-redesign/issues/19):命令行不强制隐私告知确认,没确认时其他命令照样能运行,只靠 agent 自觉先告知;是否强制尚未决定。
  - [#20](https://github.com/NoahStepheno/life-redesign/issues/20):设计里写协议当天白天推送 6 条打断问题并记录回应,命令行里没有对应实现,现在只能由 agent 在对话里口头提问。
  - [#24](https://github.com/NoahStepheno/life-redesign/issues/24):系统通知命令退出码为 0 就记为"已发送"。若你在系统里关闭了通知权限,可能一条都收不到,当天又不会重发;需要先在真机上观察。
- 数据目录在 launchd 任务里同样是安装当时的绝对路径,换位置要重装(见"推送")。

## 文档

- [docs/testing/cli-e2e.md](./docs/testing/cli-e2e.md):命令行的自动化测试和手工端到端指南
- [docs/testing/macos-push-smoke.md](./docs/testing/macos-push-smoke.md):macOS 真机推送冒烟测试(尚未在真机执行)
- [docs/testing/agent-trial-checklist.md](./docs/testing/agent-trial-checklist.md):agent 行为人工试用清单(尚未执行)
- [docs/design.md](./docs/design.md):设计方案
- [GLOSSARY.md](./GLOSSARY.md):术语表
- [docs/adr/0001-append-only-records.md](./docs/adr/0001-append-only-records.md):为什么只追加
- [skill/PROTOCOL.md](./skill/PROTOCOL.md):协议本身(行为准则、各入口流程、命令行约定)
- [skill/prompts/README.md](./skill/prompts/README.md):聊天 App 用法

## 仓库结构

仓库根目录是开发这个项目用的(术语表、设计文档、ADR、测试);用户安装的内容全部在自包含的 `skill/` 下:`SKILL.md`(Claude Code 入口)、`AGENTS.md`(其他 agent 入口)、`PROTOCOL.md`、`scripts/`、`prompts/`。
