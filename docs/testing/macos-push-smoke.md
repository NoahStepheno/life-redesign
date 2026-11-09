# macOS 真机推送冒烟测试

本文是一份**由人在真实 Mac 上执行**的流程。推送(launchd 定时任务加系统通知)是目前唯一从未在真机上跑过的部分:自动化测试(`tests/test_notify.py`)只用 `--dry-run` 和假的 `launchctl`、`terminal-notifier`,见 `docs/testing/cli-e2e.md` 第 1 节。

术语沿用 `GLOSSARY.md`;行为规则见 `skill/PROTOCOL.md` 第 9 节(每天最多 3 条、沉默期只剩晚间、勿扰日与协议未完成不推送、默认文案不含用户私人内容)。

## 0. 先读这里

> **警告:这份流程会修改真实系统。** `notify install` 会在 `~/Library/LaunchAgents/` 写入三个 plist,并向当前登录用户的 launchd 注册三个任务;`notify fire`(不带 `--dry-run`)会弹出真实通知,并把"今天已发送"写进 `state.json`。

安全路径,按顺序:

1. **先只跑 `--dry-run`**(第 3 节)。`install --dry-run` 和 `uninstall --dry-run` 只打印将要写的 plist 与将要执行的 `launchctl` 命令,不碰系统。
2. **用一次性数据目录**(`LIFE_REDESIGN_HOME`,第 2 节),不要拿真实的 `~/.life-redesign` 做注入时间的试验。原因:注入未来日期后,CLI 会在数据目录里为"过去没打卡的日子"补写 `- 未记录` 日志并增加 Unrecorded 计数(`notify plan` 和 `notify fire --dry-run` 也会这样,见 5.2 的说明)。这些写入在真实数据上很难手工撤销。
3. **如果非要用真实数据目录**:先备份(2.3),并读完 11.3 的回滚。
4. **三个任务的标签固定**(`com.life-redesign.notify.morning|random|evening`),每个用户同一时间只能有一套。即使用了一次性数据目录,`install` 仍写进**真实的** `~/Library/LaunchAgents/`,并且**会覆盖已有的同名任务**(它们的 plist 里 `LIFE_REDESIGN_HOME` 会指向一次性目录)。如果你已经安装过正式版,测完请按第 10 节卸载、再对真实数据目录重新 `install`。
5. 出任何问题,直接跳到 11.2(手动清理)。

### 本文的验证状态标记

- **[已在无真实通知的环境验证]**:本文作者在 macOS 15.6.1 上,用一次性数据目录和一次性 HOME,只跑了 `--dry-run`、`notify plan`、`plutil -lint`,命令构造与输出已核对;**没有**安装任何任务,**没有**发送任何通知。
- **[未验证]**:需要真实 launchd / 真实通知中心,从未跑过。预期现象是依据代码与 Apple 文档惯例写的推断,**以你的实际观察为准,不一致就改本文**。
- **[待确认]**:系统行为本身不确定(权限、锁屏、专注模式),写的是已知与猜测,请记录实测结果。

## 1. 测什么、怎么看出通过

| 机制 | 代码里的事实 |
|---|---|
| 三个任务 | `com.life-redesign.notify.morning`、`.random`、`.evening`;plist 在 `~/Library/LaunchAgents/<标签>.plist`;`RunAtLoad` 为 false(安装时不会立刻弹) |
| 早/晚 | `StartCalendarInterval`(Hour/Minute 取自 `notify.times`),执行 `notify fire morning` / `fire evening`(不带 `--tick`) |
| 随机位 | launchd 不能在随机时刻触发,所以 `StartInterval` = 900 秒轮询,执行 `notify fire random --tick`;`--tick` 只在"计划时刻起 900 秒内"且"今天还没发过"时才真正发送 |
| 环境变量 | plist 的 `EnvironmentVariables` 固定写入 `LIFE_REDESIGN_HOME`(安装时 CLI 看到的数据目录)、`HOME`、`PATH`(含 `/opt/homebrew/bin`、`/usr/local/bin`、`~/.local/bin` 与系统目录;客户端是绝对路径时再加上它所在目录) |
| 展示 | 找得到 `terminal-notifier` 就用它,否则 `osascript -e 'display notification ... with title ...'`;标题固定 `Life Redesign` |
| 去重 | 发送成功才写 `state.json` 的 `notify.sent[槽位] = 日期`;只有 `--tick` 会读它。不带 `--tick` 的 `fire` 每次都会发 |
| 重装提示 | `notify.installed` 记录安装时的早、晚时间;`notify config` 输出里 `reinstall_required` 在它与当前时间不同时为 true(**不比较随机窗口**,随机任务的 plist 不含时间) |
| AI 晚间推送 | `notify config --ai on` 后,晚间推送先调用 `notify.client`(默认 `claude -p`,对 `claude` 追加只读参数),失败或无输出则回退模板 |

通过标准:本文每个"预期"都与实际一致,或本文被改正;卸载后系统与数据目录里没有残留。

## 2. 准备

### 2.1 环境与函数(bash / zsh 通用)

在仓库根目录、**同一个终端会话**里执行。下面不依赖"不加引号的变量自动按空格拆分"。

```sh
export LIFE_REDESIGN_HOME=/tmp/life-redesign-smoke
CLI="$PWD/skill/scripts/life_redesign.py"
lr() { python3 "$CLI" "$@" || echo "[exit $?]"; }
clock() { export LIFE_REDESIGN_NOW="$1"; }
unclock() { unset LIFE_REDESIGN_NOW; }
```

**重要:plist 记住的是安装当时的两样东西。**

- 数据目录:取自安装时的 `LIFE_REDESIGN_HOME`(没设就是 `~/.life-redesign`)。launchd 启动的任务**不会**读你终端里的环境变量,只读 plist 里写死的这一份。所以"用一次性目录测试"必须在**设了 `LIFE_REDESIGN_HOME` 的终端里运行 `notify install`**,并用 `install --dry-run` 核对 plist 里的 `LIFE_REDESIGN_HOME`。
- 脚本路径:`ProgramArguments` 里是 `sys.executable`(安装时运行 CLI 的那个 python3 的绝对路径)和 CLI 脚本的绝对路径。把 skill 目录移动、删除(例如拿临时 worktree 测试后删掉它),任务就会找不到脚本。

**launchd 任务没有注入时间。** plist 里没有 `LIFE_REDESIGN_NOW`,所以由 launchd 启动的任务永远用真实时钟。想不等一天就测"早晨 / 随机窗口 / 晚上 / 沉默 / 勿扰 / 协议未完成",要**在终端里直接运行** CLI 并加 `clock ...`(第 5 节);要测"launchd 真的会在点上触发",只能把时间设成"几分钟之后"再等(第 6.3 节)。

### 2.2 初始化一次性数据目录并完成协议

```sh
rm -rf "$LIFE_REDESIGN_HOME"
clock 2026-01-15T09:00:00
lr init --ack-privacy
lr protocol resume > /dev/null
for q in 1.1 1.2 1.3 1.4 1.5 1.6 1.7 1.8 1.9 1.10 1.11 1.12 1.13 1.14 3.1 3.2 3.3 3.4 3.5 3.6 3.7 3.constraints; do
  lr protocol answer "$q" --text "答案 $q" > /dev/null
done
lr status
lr notify config
```

**[已在无真实通知的环境验证]** 实际输出(末两行):

```output
{"phase": "active", "privacy_required": false, "data_dir": "/tmp/life-redesign-smoke", "now": "2026-01-15T09:00:00"}
{"notify": {"client": "claude -p", "times": {"morning": "08:30", "evening": "21:30", "random_window": ["11:00", "17:00"]}, "show_user_text": false, "ai": false}, "reinstall_required": false}
```

(`data_dir` 随你设的目录而变。)

### 2.3 万一要用真实数据目录:先备份

```sh
cp -a ~/.life-redesign ~/.life-redesign.bak-smoke
ls -A ~/Library/LaunchAgents | grep life-redesign
```

第二条列出你**已经安装过**的正式任务(没有输出表示没装过)。如果有,把这些 plist 也备份:`mkdir -p ~/life-redesign-plist-bak && cp -a ~/Library/LaunchAgents/com.life-redesign.notify.*.plist ~/life-redesign-plist-bak/`。

### 2.4 记下基线

```sh
launchctl list | grep life-redesign
ls -A ~/Library/LaunchAgents | grep life-redesign
which terminal-notifier
python3 -c 'import sys; print(sys.executable)'
```

预期(干净的机器):前两条没有输出;`terminal-notifier` 没装时 `which` 报 not found,此后通知由 `osascript` 发出。把 `sys.executable` 的值记下来,第 3 节核对它与 plist 一致。

## 3. 先 dry-run:看清将要注册什么

```sh
lr notify install --dry-run
```

**[已在无真实通知的环境验证]** 预期:`dry_run` 为 true;`commands` 是三条 `launchctl bootstrap gui/<你的 uid> <plist 路径>`;`jobs` 里每项含 `label`、`path`、`plist`;**此时 `~/Library/LaunchAgents` 里不会多出任何文件**。

逐项核对 plist:

| 任务 | 关键内容 | 实测(默认配置) |
|---|---|---|
| morning | `StartCalendarInterval` Hour 8 / Minute 30;参数 `notify fire morning` | 一致 |
| random | `StartInterval` 900;参数 `notify fire random --tick`;无 `StartCalendarInterval` | 一致 |
| evening | `StartCalendarInterval` Hour 21 / Minute 30;参数 `notify fire evening` | 一致 |
| 全部 | `RunAtLoad` false;`EnvironmentVariables` 含 `HOME`、`LIFE_REDESIGN_HOME`、`PATH` | 一致 |

检查清单(你来勾):

- [ ] `ProgramArguments[0]` 就是 2.4 里记下的 python3,且该文件存在、能运行
- [ ] 脚本路径指向一个**以后不会被移动或删除**的位置
- [ ] `LIFE_REDESIGN_HOME` 是你要测的那个目录
- [ ] 脚本所在位置不在 `~/Desktop`、`~/Documents`、`~/Downloads` 等受系统隐私保护(TCC)的目录下。**[待确认]** launchd 启动的进程读这些目录可能被拒绝,表现为任务"成功加载但从不弹通知"。保险起见把仓库放在 `~/projj`、`~/src` 之类的位置
- [ ] 每个 plist 过得了语法检查:把 `jobs[].plist` 存成文件后运行 `plutil -lint <文件>`,预期每个都输出 `<文件>: OK`(**[已在无真实通知的环境验证]**:三个 plist 均 OK)

再看卸载将做什么:

```sh
lr notify uninstall --dry-run
```

**[已在无真实通知的环境验证]** 预期:三条 `launchctl bootout gui/<uid>/<标签>`,`remove_files` 列出三个 plist 路径,不做任何改动。

## 4. 通知权限与专注模式(先做,否则后面的"没弹"分不清原因)

通知是否可见取决于系统设置,与本项目代码无关。已知与待确认:

| 项目 | 已知 / 推断 | 状态 |
|---|---|---|
| 谁来弹 | `osascript` 的通知被归到 **Script Editor(脚本编辑器)** 名下;`terminal-notifier` 则归到它自己 | 归属为常见现象 **[待确认]**,请在"系统设置 > 通知"里实际看列表里出现了谁 |
| 首次权限 | 第一次弹出时,系统可能询问是否允许该应用发送通知;也可能不询问而直接默认允许或默认拒绝 | **[待确认]** 记录你看到的 |
| 被关闭的后果 | 若该应用的通知被关闭,`osascript` 仍可能退出码 0。CLI 据此会写 `fired: true` 与 `notify.sent`,但你什么都没看到——所以**CLI 的 `fired: true` 不等于用户看见了通知** | 退出码行为 **[待确认]** |
| 提示样式 | 系统设置里把该应用设为"横幅"或"提醒"。横幅会自动消失;想确认弹出过,到通知中心(点屏幕右上角时间)里找 | — |
| 专注模式 / 勿扰 | 专注模式开着时,通知默认被静默、不弹出,只进通知中心 | **[待确认]** 是否进通知中心;请开/关一次各测一遍 |
| 锁屏 | 系统设置里每个应用有"锁定屏幕时显示预览 / 在锁定屏幕上显示"一类选项,可设为始终、解锁时或从不 | **[待确认]** 本项目的文案**默认不含私人内容**(`打开查看今日杠杆`),但随机位的打断问题与晚间提醒是预写文案;打开 `--show-user-text on` 后 Year Goal 与 Daily Levers 的原文**会出现在通知里**——此时锁屏预览设置很重要 |
| 本项目与"勿扰"的区别 | `dnd` 命令管的是**勿扰日**(整天不推送),与 macOS 专注模式无关;两者独立 | 已知 |

建议在 4.1 做一次权限弹窗处理:

### 4.1 授予权限

1. 运行下面这条,它会**弹出一条真实的测试通知**(只在你的终端手动运行,不涉及 launchd):

   ```sh
   osascript -e 'display notification "权限测试" with title "Life Redesign"'
   ```

   (如果你装了 `terminal-notifier`,CLI 会改用它;这时请改测 `terminal-notifier -title "Life Redesign" -message "权限测试"`。)
2. 若出现权限询问,点"允许"。若没有任何东西弹出:打开"系统设置 > 通知",在应用列表里找 Script Editor(或 terminal-notifier),把"允许通知"打开,样式选"横幅"或"提醒",再重试。
3. 记录:谁出现在列表里?是否出现过询问?锁屏时能否看到?(填第 12 节的表。)

## 5. 注入时间:不装任何任务,验证计划与文案

这一节**不会弹通知**:`fire` 全部带 `--dry-run`(显示将发送的内容但不发送,也不写 `notify.sent`)。launchd 不参与,所以可以任意注入时间。

### 5.1 辅助函数

```sh
f() { echo "## $LIFE_REDESIGN_NOW $*"; lr notify fire "$@"; }
```

### 5.2 先读这个副作用

`notify plan` 与 `notify fire --dry-run` 都会先做"补记 Unrecorded"(代码里的 `notify_state()`):当注入的日期晚于上次互动,会往 `log/` 里**追加** `- 未记录` 并增加 `streak.unrecorded`。这是 5.7 沉默场景能成立的原因,但也说明它们**不是纯只读**。所以第 5 节只在一次性数据目录里做,并且**按下面的顺序**(时间只往前推)。

### 5.3 早晨(2026-01-16)

```sh
clock 2026-01-16T08:30:00
f morning --dry-run
lr notify plan --date 2026-01-16
```

**[已在无真实通知的环境验证]** 预期:`source` 为 `template`,`text` 为 `打开查看今日杠杆`(**不含任何用户文字**),`display_command` 为 `osascript -e 'display notification "打开查看今日杠杆" with title "Life Redesign"'`(装了 `terminal-notifier` 时是它)。`plan` 实测:2026-01-16 三条依次为 morning 08:30、random 12:48(`我正在走向我讨厌的生活,还是我想要的生活?`)、evening 21:30。随机时刻与问题只取决于日期,同一天永远相同;2026-01-15 的随机位是 11:05。

### 5.4 随机窗口与 `--tick` 的"到点"判定

规则:只有 `0 <= 现在 - 计划时刻 < 900 秒` 才算到点。用 2026-01-16 的随机时刻 12:48:

```sh
clock 2026-01-16T12:40:00
f random --dry-run --tick
f random --dry-run
clock 2026-01-16T12:50:00
f random --dry-run --tick
```

**[已在无真实通知的环境验证]** 预期依次:`skipped: "not due yet"`;不带 `--tick` 则无视时间直接给出内容(这是手动触发用的);12:50 在 12:48 之后 900 秒内,给出内容。再测边界(用早晨 08:30):`08:44:59` 仍到点,`08:45:00` 变成 `not due yet`。

注意:`--tick` 判定对早/晚也生效,但 launchd 只对随机位传 `--tick`。

### 5.5 晚上

```sh
clock 2026-01-16T21:30:00
f evening --dry-run --tick
```

**[已在无真实通知的环境验证]** 预期 `text` 为 `该打卡了:花几分钟记录今天。`,`source` 为 `template`。

### 5.6 显示用户原文(隐私开关)

先放入可辨认的内容,然后开关一次:

```sh
lr append goals --year-goal "SECRETGOAL" --month-project m --constraints c > /dev/null
lr plan change daily-levers --text "SECRETLEVER" --why r > /dev/null
clock 2026-01-16T08:30:00
f morning --dry-run
lr notify config --show-user-text on
f morning --dry-run
lr notify config --show-user-text off
f morning --dry-run
```

**[已在无真实通知的环境验证]** 预期:第一次与最后一次 `text` 仍是 `打开查看今日杠杆`,不含 `SECRET`;打开后是 `今日杠杆: SECRETLEVER | Year Goal: SECRETGOAL`。**一定要关回去**(PROTOCOL 规定默认关闭,AI 不得替用户打开)。真机上的对应步骤见 7.2。

### 5.7 勿扰日、沉默期

```sh
lr dnd add 2026-01-17
clock 2026-01-17T08:30:00
f morning --dry-run
lr notify plan --date 2026-01-17
clock 2026-01-20T08:30:00
lr notify plan
f morning --dry-run
clock 2026-01-20T21:30:00
f evening --dry-run
lr streak status
```

**[已在无真实通知的环境验证]** 预期:勿扰日 `skipped: "do-not-disturb date"`,计划 `pushes: []`、`reason: "do-not-disturb date"`。到 2026-01-20,16、18、19 三天没打卡(17 日是勿扰日,不计)→ `streak.unrecorded` 为 3,计划只剩晚间一条,`reason: "silence: unrecorded streak"`;早晨 `fire` 被跳过(`skipped: "silence: unrecorded streak"`),晚间照常给出内容。

### 5.8 协议未完成

用另一个全新的数据目录(只 `init`,不答题):

```sh
export LIFE_REDESIGN_HOME=/tmp/life-redesign-smoke-fresh
rm -rf "$LIFE_REDESIGN_HOME"
clock 2026-01-16T08:30:00
lr init --ack-privacy
lr notify plan
f morning --dry-run
export LIFE_REDESIGN_HOME=/tmp/life-redesign-smoke
```

**[已在无真实通知的环境验证]** 预期:`pushes: []`、`reason: "protocol not complete"`;`fire` 返回 `skipped: "protocol not complete"`。做完这一步别忘了把 `LIFE_REDESIGN_HOME` 切回去(最后一行)。注意:协议只开始(`protocol resume`)也仍是 `protocol not complete`(已验证)。

### 5.9 配置输入校验

```sh
lr notify config --morning 25:00
lr notify config --window 17:00 11:00
lr notify config --client ""
```

**[已在无真实通知的环境验证]** 预期依次:`error: --morning must be HH:MM (24h)`、`error: --window start must be before end`、`error: --client must not be empty`,均 `[exit 1]`。

## 6. 真正安装并确认三个任务已加载

> 从这里开始修改真实系统。先确认 `echo "$LIFE_REDESIGN_HOME"` 是你要测的目录,并已读过第 0 节。

第 5 节的注入会把测试数据推到"沉默期"(`streak.unrecorded` 为 3,只剩晚间),不适合继续用。所以**重建一个干净的 active 数据目录**,并用真实时间:

```sh
unclock
rm -rf "$LIFE_REDESIGN_HOME"
lr init --ack-privacy
lr protocol resume > /dev/null
for q in 1.1 1.2 1.3 1.4 1.5 1.6 1.7 1.8 1.9 1.10 1.11 1.12 1.13 1.14 3.1 3.2 3.3 3.4 3.5 3.6 3.7 3.constraints; do
  lr protocol answer "$q" --text "答案 $q" > /dev/null
done
lr notify plan
```

预期 `lr notify plan` 今天有三条推送(morning / random / evening)。(此处未验证:协议答案按真实时间写入,与 2.2 只差时钟。)

### 6.1 安装

```sh
lr notify install
```

**[未验证]** 预期:返回 JSON,`failed` 为 `[]`,`results` 有三条且 `returncode` 都是 0;`~/Library/LaunchAgents` 里出现三个 plist;`lr notify config` 之后 `reinstall_required` 仍为 false。若有失败,命令以非零状态退出,`results[].stderr` 带 launchctl 的原话,`notify.installed` 不会被写入。

### 6.2 确认系统已加载

```sh
ls -l ~/Library/LaunchAgents | grep life-redesign
launchctl list | grep life-redesign
launchctl print "gui/$(id -u)/com.life-redesign.notify.morning"
launchctl print "gui/$(id -u)/com.life-redesign.notify.random"
launchctl print "gui/$(id -u)/com.life-redesign.notify.evening"
```

**[未验证]** 预期:

- 三个 plist 文件存在,属于当前用户。
- `launchctl list` 有三行含 `com.life-redesign.notify.*`;第一列(PID)是 `-` 表示当前没在运行,第二列是上次退出码(从未运行过为 `-` 或 `0`)。
- `launchctl print` 能打印出任务:应看到程序与参数、`environment` 里的 `LIFE_REDESIGN_HOME`,早晚任务能看到日历触发条件,随机任务能看到 900 秒间隔。具体字段名与排版 **[待确认]**,请把你看到的关键行记在第 12 节。
- 若 `launchctl print` 报 `Could not find service`,说明没加载成功,去第 11 节。

### 6.3 让 launchd 真的触发一次(三种办法,选合适的)

1. **立即触发,不等时间**:`launchctl kickstart -k "gui/$(id -u)/com.life-redesign.notify.morning"`(`-k` 表示若已在运行先杀掉重来)。早、晚两个任务不带 `--tick`,所以**无视当前时间,只要今天计划里有该槽位就弹**。随机任务带 `--tick`,不到点只会输出 `not due yet` 而不弹,这是正常的。
2. **等早/晚点**:用 `lr notify config --morning HH:MM`(设为**当前时间之后 2 到 3 分钟**),按 `reinstall_required` 提示重装(第 8 节),等到点看是否弹出。这是验证 `StartCalendarInterval` 的唯一办法。
3. **等随机位**:随机任务的 plist 不含时间,所以改窗口**不需要重装**。把窗口设成"刚刚过去的一小段",例如现在是 14:07:`lr notify config --window 14:00 14:06`,当天随机时刻必落在 14:00 到 14:06 之间,下一次 15 分钟轮询(或第 1 种办法的 kickstart)就会判定到点并弹出。测完把窗口改回:`lr notify config --window 11:00 17:00`。

触发后:

```sh
launchctl print "gui/$(id -u)/com.life-redesign.notify.morning"
```

**[未验证]** 预期:能看到运行次数(runs)增加、上次退出码(last exit code)为 0 一类的字段 **[待确认]**。注意:**plist 没有设置 `StandardOutPath` / `StandardErrorPath`,任务的输出会被丢弃**,弹不出时没有日志可看;排查用第 11.1 节的办法。

## 7. 手动触发各时段,核对真实通知

下面三小节在终端里直接运行(不经过 launchd),会**真的弹通知**。可以注入时间,也可以用真实时间(`unclock`)。

### 7.1 默认隐私文案

```sh
unclock
lr notify fire morning
lr notify fire random
lr notify fire evening
```

**[未验证]** 预期:每条命令返回 `"fired": true`,屏幕右上角依次弹出标题 `Life Redesign`、内容分别为:

- 早:`打开查看今日杠杆`
- 随机:六个打断问题之一(PROTOCOL 4.2),**不是**三条备选
- 晚:`该打卡了:花几分钟记录今天。`

核对"默认不含用户私人内容":三条通知里**不能出现你的 Year Goal、Daily Levers 或日志文字**。再确认:无论锁屏时预览如何设置,看到的都只是这些预写文案。

注意:不带 `--tick` 的 `fire` 随时可以再发(没有去重),也不看当前时间是否到点;随机位的内容是当天计划里的那个问题。

### 7.2 开启显示用户原文,验证,再关闭

```sh
lr notify config --show-user-text on
lr notify fire morning
lr notify config --show-user-text off
lr notify fire morning
```

**[未验证]** 预期:第一次通知内容是 `今日杠杆: <你的杠杆> | Year Goal: <你的 Year Goal>`;**检查锁屏时是否显示这些原文**(取决于 4 节的预览设置,记入第 12 节);第二次恢复为 `打开查看今日杠杆`。务必确认最后一次 `config` 输出里 `show_user_text` 为 false。

### 7.3 每天不超过 3 条、重复触发不重复推送

`--tick` 去重要用**真实发送**才能写入 `notify.sent`,所以用第 6 节重建的一次性数据目录(不要用做过第 5 节注入的,那份已进入沉默期),注入一个过去的日期,各发一遍,再各重复一遍:

```sh
clock 2026-01-16T08:30:00
lr notify fire morning --tick
clock 2026-01-16T12:50:00
lr notify fire random --tick
clock 2026-01-16T21:30:00
lr notify fire evening --tick
echo "--- 重复一遍 ---"
clock 2026-01-16T08:30:00
lr notify fire morning --tick
clock 2026-01-16T12:50:00
lr notify fire random --tick
clock 2026-01-16T21:30:00
lr notify fire evening --tick
```

**[未验证]** 预期:前三条各弹一次,共 3 条通知(`fired: true`);重复的三条都输出 `skipped: "already sent today"`,没有任何新通知。`state.json` 的 `notify.sent` 记录三个槽位的日期 `2026-01-16`。(判定"当天是否到点"依赖注入的时钟,而 `sent` 记录的是注入的日期,所以换一个日期会重新开始:再把时钟拨到 `2026-01-17T08:30:00` 发 morning 应能再次弹出。)

也就是:同一天同一槽位最多一条,三个槽位合计最多 3 条;沉默期与勿扰日更少(见第 5 节的 dry-run 结果,真机上不必重复发送)。

## 8. 修改推送时间 → 提示重装 → 重装

先确认已安装(第 6 节),再改时间:

```sh
lr notify config --evening 22:00
```

**[未验证]** 预期:输出里 `"reinstall_required": true`(此逻辑有自动化测试覆盖,但真机安装后的状态是第一次走)。此时系统里的晚间任务**仍然是旧时间**(plist 没变),这是 `reinstall_required` 要提醒的。核对:

```sh
lr notify install --dry-run
```

预期:晚间 plist 里 Hour 22 / Minute 0。然后重装:

```sh
lr notify install
lr notify config
```

**[未验证]** 预期:`install` 对已存在的 plist 先 `bootout` 旧任务再写新文件再 `bootstrap`;`failed` 为 `[]`;随后 `reinstall_required` 回到 false;`launchctl print "gui/$(id -u)/com.life-redesign.notify.evening"` 里的触发时间是 22:00。再把时间改回 21:30 并重装一次,或在第 10 节卸载。

只改随机窗口(`--window`)不会置 `reinstall_required`,因为随机任务不含时间,这是设计,不是遗漏。

## 9. AI 参与的晚间推送与回退

先决条件:你同意晚间推送使用 AI(`--ai on`,默认关)。**dry-run 也会真的运行客户端**(并读取近 7 天日志、可能联网计费),所以只在测试数据上做。

```sh
lr notify config --ai on
clock 2026-01-16T21:30:00
f evening --dry-run
```

**[已在无真实通知的环境验证]**(本机装了 `claude`)预期:`source` 为 `ai`,`text` 是一句中文打卡提醒(最多 120 字符),`client_command` 里提示词被显示成 `<prompt>`,并带 `--tools "" --disallowedTools Bash,Edit,Write,MultiEdit,NotebookEdit`(只读)。AI 文案内容每次不同。

不可用客户端回退:

```sh
lr notify config --client /nonexistent/claude
f evening --dry-run
lr notify config --client "claude -p"
lr notify config --ai off
```

**[已在无真实通知的环境验证]** 预期:`source` 为 `template`,`text` 为 `该打卡了:花几分钟记录今天。`,命令成功退出,没有报错(`client_command` 仍会列出,因为命令构造成功,只是运行时找不到)。

真机上的 launchd 环境差异 **[未验证]**:launchd 的 `PATH` 来自 plist。想验证"客户端在 launchd 下也找得到":把 `--client` 设为绝对路径(例如 `which claude` 的结果加 ` -p`),重装(这会把它所在目录并入 plist 的 `PATH`),然后 `kickstart` 晚间任务(6.3 的办法 1)并观察是否弹出的是 AI 文案还是模板文案。两者都算"没坏",但模板意味着客户端在 launchd 里没跑通(例如登录状态在 launchd 环境不可用)。**[待确认]** `claude -p` 在 launchd 下能否访问钥匙串中的登录凭据。

## 10. 卸载,并确认没有残留

```sh
lr notify uninstall
```

**[未验证]** 预期:三条 `launchctl bootout` 的 `returncode` 都为 0,`failed` 为 `[]`,三个 plist 被删除,`notify.installed` 被移除。

核对"系统里没有残留":

```sh
launchctl list | grep life-redesign
for l in morning random evening; do launchctl print "gui/$(id -u)/com.life-redesign.notify.$l"; done
ls -A ~/Library/LaunchAgents | grep life-redesign
grep -c installed "$LIFE_REDESIGN_HOME/state.json"
```

预期:`launchctl list | grep` 无输出(grep 退出码 1);三条 `print` 都报找不到服务;`ls | grep` 无输出;`grep -c` 输出 0。

核对"数据目录里没有不想要的东西":

```sh
ls -A "$LIFE_REDESIGN_HOME"
ls -A "$LIFE_REDESIGN_HOME/log"
```

预期只有 `anti-vision.md`、`goals.md`、`log`、`protocol`、`state.json`、`vision.md`(以及你自己建的文件)。`log/` 里除你的日志外,可能有 5.2 所述的 `- 未记录` 补记。`state.json` 里的 `notify.sent` 会保留(它是"最后一次发送日期",不是任务)。

已知行为:如果任务本来就没装,`uninstall` 的三条 `bootout` 会失败,命令以非零状态退出——但它仍然会删除 plist 文件。这是无害的。

最后:如果你测试前已经装过正式版,回到真实数据目录重新安装(`unset LIFE_REDESIGN_HOME` 后 `lr notify install`,先 `--dry-run` 看)。

## 11. 出问题时:排查与手动清理

### 11.1 排查:任务加载了但不弹

按顺序:

1. 终端里直接 `lr notify fire evening --dry-run` 看内容是否正常、`skipped` 是什么原因(协议未完成、勿扰日、沉默期、未到点、今天已发)。
2. 终端里直接 `lr notify fire evening`(真发):能弹说明代码与通知权限没问题,问题在 launchd 环境;不能弹回第 4 节查权限与专注模式。
3. `launchctl print "gui/$(id -u)/com.life-redesign.notify.evening"` 看上次退出码、运行次数。退出码非 0:大概率是 python3 或脚本路径失效(plist 里的绝对路径)或脚本在受 TCC 保护的目录。
4. 用 plist 里的 python3 与脚本路径、并带上 plist 里的环境,手工跑一遍,复现 launchd 的最小环境:`env -i HOME="$HOME" LIFE_REDESIGN_HOME="$LIFE_REDESIGN_HOME" PATH=/usr/bin:/bin "<plist 里的 python3>" "<plist 里的脚本>" notify fire evening --dry-run`。
5. 查系统日志 **[待确认]**:`log show --last 15m --predicate 'process == "launchd"' | grep life-redesign`。
6. 注意 Mac 合盖睡眠时错过的 `StartCalendarInterval` 任务,一般在唤醒后补跑一次;随机任务的轮询在睡眠期间不运行,若计划时刻后 900 秒窗口全在睡眠中,**当天这条随机推送就丢了**(`--tick` 只接受 900 秒内的到点)。**[待确认]**。

### 11.2 手动清理(`notify uninstall` 失败时,或 CLI 已不可用时)

```sh
for l in morning random evening; do
  launchctl bootout "gui/$(id -u)/com.life-redesign.notify.$l"
done
rm -f ~/Library/LaunchAgents/com.life-redesign.notify.morning.plist
rm -f ~/Library/LaunchAgents/com.life-redesign.notify.random.plist
rm -f ~/Library/LaunchAgents/com.life-redesign.notify.evening.plist
launchctl list | grep life-redesign
ls -A ~/Library/LaunchAgents | grep life-redesign
```

`bootout` 对未加载的任务报错是正常的,继续往下。预期末两条无输出。如果 `launchctl list` 里还有残留,用旧接口再删一次:`launchctl remove com.life-redesign.notify.morning`(random、evening 同理)。

这些命令只处理这三个固定标签,不会碰别的任务。

### 11.3 回滚:用过真实数据目录时

CLI 对数据只追加、不覆盖,所以回滚就是用备份(2.3)整体还原:

```sh
ls -A ~/.life-redesign.bak-smoke
mv ~/.life-redesign ~/.life-redesign.after-smoke
cp -a ~/.life-redesign.bak-smoke ~/.life-redesign
```

确认 `~/.life-redesign` 内容正确后,才可以手动删除 `~/.life-redesign.after-smoke`。要点:

- 受影响的只有:`state.json` 的 `notify.*`(配置、`installed`、`sent`)、注入时间期间被补写的 `log/*.md` 里的 `- 未记录`,以及 `streak.unrecorded`。
- 若只想还原通知设置而保留测试期间的真实记录,不要整体还原,而是按 `lr notify config` 手动改回 `--morning/--evening/--window/--client/--ai/--show-user-text`,并手工检查 `log/` 里新增的 `- 未记录` 日志。
- 如果测试前你装过正式版,别忘了用备份的 plist 或重新 `install` 恢复。

## 12. 观察记录表(由你填写)

"预期"来自本文;"状态"列:V = 本文作者已用 dry-run 验证,U = 未验证需你在真机核对。

| # | 步骤 | 预期 | 状态 | 实际观察 | 一致? |
|---|---|---|---|---|---|
| 1 | 2.4 基线 | 无已安装任务与 plist | U | | |
| 2 | 3 `install --dry-run` | 三条 bootstrap,三个 plist,`plutil -lint` 均 OK,系统无变化 | V | | |
| 3 | 3 plist 内容 | morning 8:30、evening 21:30、random StartInterval 900 `--tick`、RunAtLoad false、含 `LIFE_REDESIGN_HOME` | V | | |
| 4 | 3 `uninstall --dry-run` | 三条 bootout,列出三个 plist 路径 | V | | |
| 5 | 4.1 首次通知权限 | 出现询问或需手动在系统设置打开;记录归属应用 | U | | |
| 6 | 4 专注模式开启时 | 通知不弹出(是否进通知中心?) | U | | |
| 7 | 4 锁屏 | 预览显示行为(三种设置各记录) | U | | |
| 8 | 5.3 早晨 dry-run | `打开查看今日杠杆`,无用户文字 | V | | |
| 9 | 5.4 随机窗口 | 12:40 not due yet,12:50 给内容;08:44:59 到点、08:45:00 不到点 | V | | |
| 10 | 5.5 晚间 | `该打卡了:花几分钟记录今天。` | V | | |
| 11 | 5.6 显示原文开关 | 开后含原文,关后恢复 | V | | |
| 12 | 5.7 勿扰日 | 无推送,reason 为 do-not-disturb | V | | |
| 13 | 5.7 沉默期 | 只剩晚间,早晨 skipped | V | | |
| 14 | 5.8 协议未完成 | 无推送,reason 为 protocol not complete | V | | |
| 15 | 6.1 `install` | `failed: []`,三个 plist 出现 | U | | |
| 16 | 6.2 `launchctl list/print` | 三个任务已加载 | U | | |
| 17 | 6.3 kickstart morning | 弹出 `打开查看今日杠杆` | U | | |
| 18 | 6.3 等早/晚点 | 到点触发 | U | | |
| 19 | 6.3 窗口法触发随机位 | 下一次轮询内弹出一个打断问题 | U | | |
| 20 | 7.1 三个时段默认文案 | 无私人内容 | U | | |
| 21 | 7.2 显示原文后再关闭 | 通知含原文;锁屏是否显示;关后恢复 | U | | |
| 22 | 7.3 去重与每日上限 | 3 条通知;重复 3 次全部 already sent today | U | | |
| 23 | 8 改晚间时间 | `reinstall_required: true`;重装后 false、系统时间更新 | U | | |
| 24 | 9 AI 晚间推送 | `source: ai` | V(dry-run) | | |
| 25 | 9 客户端不可用 | 回退模板文案 | V | | |
| 26 | 9 launchd 下的 AI 客户端 | AI 文案或模板;记录 | U | | |
| 27 | 10 `uninstall` | 全部 returncode 0,plist 被删 | U | | |
| 28 | 10 无残留 | 无已加载任务、无 plist、数据目录无多余文件 | U | | |
| 29 | 11.2 手动清理 | 能清除加载的任务与 plist | U | | |

走完后,把与"预期"不一致之处直接改在本文里(每个 U 步骤的预期都应变成实测结论),并在顶部状态标记处注明测试日期、macOS 版本、是否安装了 `terminal-notifier`。
