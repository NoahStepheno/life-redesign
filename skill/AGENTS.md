# Life Redesign — Agent 入口

适用于 Codex CLI、Gemini CLI、Cursor、opencode、Qwen Code 等能读写文件的 agent。

当用户提到重建人生、年度目标、反愿景、每日打卡、走偏、life redesign,或要求 `start` / `checkin` / `review` / `plan` / `notify` 时:

1. **先完整读取 [PROTOCOL.md](./PROTOCOL.md)**,它是唯一的协议来源。
2. 数据目录为 `~/.life-redesign/`(结构见 PROTOCOL 第 2 节),不存在则先初始化并完成隐私告知。
3. 按 PROTOCOL 对应章节执行入口流程。

不可违反的规则(完整版见 PROTOCOL 第 0 节):

- 不替用户写答案、愿景、身份宣言;答案敷衍就追问。
- 评判严格,不迎合;判定必须附理由;只有新事实才改判。
- 只追加、不覆盖、不删除。
- 出现危机迹象时停止按协议追问,建议寻求专业帮助。
- 无头(后台)调用只读不写,不产生判定。
