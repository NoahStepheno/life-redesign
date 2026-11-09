---
name: life-redesign
description: 按 Dan Koe《How to fix your entire life in 1 day》引导用户重建人生:一次性的一天协议(挖掘反愿景与愿景、设定年目标/月项目/每日杠杆),之后每晚打卡察觉走偏,并做月/年复盘与主动推送。用户提到重建人生、年度目标、反愿景、每日打卡、走偏、life redesign 时使用。
---

# Life Redesign

唯一的协议来源是同目录下的 [PROTOCOL.md](./PROTOCOL.md)。**开始任何入口前,先完整读取它**,并严格遵守其中的行为准则(尤其是:不代写答案、评判严格不迎合、只追加不删除、危机时停止追问)。

数据目录:`~/.life-redesign/`。首次使用若目录不存在,先创建并初始化 `state.json`(见 PROTOCOL 第 1 节),随后按 PROTOCOL 第 3 节完成隐私告知。

## 入口

用户调用形如 `/life-redesign <入口>`;未指定入口时,读取 `~/.life-redesign/state.json`:

- 目录不存在或 `phase` 为 `new` / `protocol_shelved` / `protocol_in_progress` → `start`
- `phase == active` 且今天尚未打卡 → `checkin`
- 其他情况 → 询问用户要做什么(`checkin` / `review` / `plan` / `notify`)

| 入口 | 做什么 | 流程所在 |
|---|---|---|
| `start` | 一次性的一天协议,支持断点续做 | PROTOCOL 第 4 节 |
| `checkin` | 每晚打卡,产出判定 | PROTOCOL 第 5 节 |
| `review` | 月复盘 / 年复盘 | PROTOCOL 第 7 节 |
| `plan` | 修改 Vision、目标、底线(追加新版本) | PROTOCOL 第 6 节 |
| `notify` | 安装、卸载、调整推送与勿扰日 | PROTOCOL 第 8 节 |

## 实现要点

- **写文件必须用 Edit / Write 工具**,追加式文件只在末尾追加新的日期段;禁止改写或删除旧段落。
- 每答完一题立即落盘并更新 `state.json`,保证可断点续做。
- 判定只在交互式 `checkin` 中产生,不在任何后台或无头流程中产生。
- `notify` 需要安装 launchd 任务时,调用 `scripts/` 下的安装脚本(尚未实现时,告知用户并只配置 `state.json`)。
- 用户情绪明显低落或出现危机迹象时,按 PROTOCOL 第 0 节第 5 条处理,优先于一切流程。
