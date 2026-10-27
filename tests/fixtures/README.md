# 纳入版本控制的会话存储基准样本

`session_store/` 是在本代码库之外生成、纳入版本控制的会话存储基准样本。回放使用固定的磁盘布局，而不是写入器刚刚生成的存储，因此，读取器若悄悄假定数据必定采用自身写入器的输出格式，就会在此处失败。

样本包含两个会话目录，以及根目录下的 `_memory.json`。主会话覆盖了全部十种记录类型，因此每条回放路径都有对应样本：

| 记录 | 样本内容 |
|---|---|
| `session_started` | 主会话中有两条，一条没有轮次 ID，一条带有轮次 ID；第二个会话中有一条 |
| `message_appended` | 四条：`system` 提示词、一条 `user` 消息、一条带 `reasoning_content` 的助手消息，以及一条带 `tool_calls` 的助手消息 |
| `tool_result` | 一条，将 `call-1`（`bash`）与 `/tmp/workspace` 配对 |
| `approval_decision` | 一条，值为 `once` |
| `checkpoint` | 一条，包含单个文件条目（`a.txt`，内容为 `old`，模式为 `420`） |
| `error` | 一条，内容为 `something failed` |
| `cancel` | 一条 |
| `compact` | 一条，包含 `summary`、`original_messages` 和 `kept_messages` |
| `reset` | 一条 |
| `context_replaced` | 一条，携带替换后的对话记录 |

第二个会话目录 `20260916T130000000000000` 仅包含一条 `session_started` 记录，使 `store.Store.list` 能看到多个会话，并按 `updated_at` 从新到旧排列。
`_memory.json` 包含 `remember this` 和 `and this`。

时间戳采用 RFC 3339，秒的小数部分精确到纳秒，去掉末尾的零：`2026-09-16T12:00:00.123456789Z` 保留全部九位，`2026-09-16T09:44:54.026498Z` 保留六位非尾零数字，`2026-09-16T12:00:01Z` 则完全省略小数部分。

权限模式位不属于样本契约：Git 仅保留可执行位，检出时文件和目录的权限由本地 umask 决定。回放不得依赖存储的权限模式。

## 重新生成

通过 `store.Store.append` 向新的根目录写入每种类型的记录，或直接编辑 JSONL，然后恢复上述时间戳的小数部分和第二个会话目录。不能用写入器端到端生成的存储替代：该写入器从微秒格式化秒的小数部分，最多六位，无法生成此处的完整布局。`tests/runtime/test_session_store.py` 会回放每种记录类型并列出两个会话；替换样本后必须运行该测试。
