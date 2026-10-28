# 待完成工作（Gap）

Gap 是我们需要努力完成的事情。本文件集中维护这些工作：需要达成什么、当前缺少什么、怎样判断完成。每项工作关联目标依据和现状证据；开发节点的状态与依赖由 [flow](flow.md)维护，开发方法见[开发流程](development.md)。

工作可以是补齐能力、修复行为、明确尚未确定的需求，或完成必要验证。已有代码和检查结果用于说明工作依据，不能代替待完成事项及其完成条件。目标定义以[产品定义](design/product.md)、[项目愿景](design/vision.md)和[质量约束](design/constraints.md)为准。

## 已知待完成工作

以下按独立工作划分，ID 保持稳定，表格顺序不代表实施顺序；具体依赖见 Flow。当前清单是工作基线，后续继续补充；完成的条目直接从清单移除，关闭依据留在 [Flow 的验证证据](flow.md#验证证据) 中，本文件不保留归档。

| Gap | 需要完成的事情 | 目标依据 | 当前缺口与证据 | 完成条件 |
|---|---|---|---|---|
| G00 | 明确阶段目标和验收场景 | [产品定义](design/product.md)、[愿景评价方向](design/vision.md#如何判断是否接近愿景) | 已有产品定位与能力范围，最终场景、阶段优先级和验收标准尚未收敛 | 项目负责人确认目标场景、阶段范围及验收条件，各项均可追踪到实现和验证 |
| G02 | 实现当前 Turn 的 steering 和下一 Turn 的排队输入 | [输入归属](design/concepts.md#输入归属) | steering 已从运行时贯通到终端：`TurnPort.steer` 返回受理/拒绝回执，接纳与撤销由通知报告（见 [E10](flow.md#验证证据)）；排队输入也经过 Machine 并在下一 Turn 起点接纳，`TurnPort.queue` 返回受理/拒绝回执，取消时丢弃（见 [E13](flow.md#验证证据)），终端与 Web 均有入口、Web 入口由冒烟脚本验证（见 [E15](flow.md#验证证据)）；实现已由 [D14](flow.md#开发节点邻接表) 交付并经项目负责人验收（见 [E28](flow.md#验证证据)）。仍缺：真实终端按键与竞态验证，记在 [D13](flow.md#开发节点邻接表) | 输入归属及接纳路径按概念、运行时和应用接口规范实现，相关交互与竞态验证通过 |
| G05 | 建立验证环境并完成基线与阶段验收 | [质量验收](design/constraints.md#验证方式) | 应用此前在非 POSIX 平台上导入即失败，`tests/llm` 也因缺少依赖声明无法收集，两者已修复（见 [E12](flow.md#验证证据)）；验证环境现已建立，pytest、ruff、pyright 与 `npm` 均可执行：全仓 609 通过、7 失败、9 跳过、1 错误，覆盖率 80%，`ruff format --check` 通过，`ruff check` 只剩 4 条既有 `RUF001`，`pyright` 仍有 92 条（见 [E25](flow.md#验证证据)、[E26](flow.md#验证证据)）；剩余失败为沙箱临时目录 5 条与 Windows 进程组、析构告警 2 条，平台侧缺口见 [G14](#已知待完成工作)；验证环境与基线一项已由项目负责人随 [D01](flow.md#开发节点邻接表) 验收（见 [E28](flow.md#验证证据)），真实终端验收与阶段验收仍未执行（见 [E16](flow.md#验证证据)、[E26](flow.md#验证证据)） | 建立可执行验证环境，完成适用自动检查、平台隔离和终端验收；按确认的场景完成阶段产品验收并记录真实结果 |
| G07 | 按 Codex CLI 对标设计完善终端体验 | [UI 设计](design/ui.md)、[UX 设计](design/ux.md) | UI/UX 设计基线已由项目负责人验收（见 [E28](flow.md#验证证据)）；Web 界面按同一组设计与接口能力呈现，浏览器交互经真实 Edge 经 CDP 验收（见 [E20](flow.md#验证证据)、[E25](flow.md#验证证据)）。仍缺：[终端实现](../super_agent/tui/terminal.py)尚未按状态界面和运行中交互逐项对齐，真实终端交互未验收 | UI/UX 设计验收通过，终端按设计和终端规范对齐，自动检查及真实终端验收通过 |
| G09 | 为非 Linux 平台提供命令隔离沙箱 | [工具沙箱](spec/tools.md#沙箱)、[配置](spec/config.md#沙箱) | `strict` 依赖 Linux `bubblewrap`，非 Linux 平台当前在未显式设置时自动降级为 `off` 并提示 `sandbox_downgraded`，命令以完整权限运行；Windows 上的真隔离（Windows Sandbox / AppContainer / Job Objects）尚未实现，Job Objects 只能限资源、不能限文件访问。项目负责人已于 2026-10-29 决定实现该能力，不采用“明确不提供并接受风险”的收口方式；实施节点见 [D48](flow.md#开发节点邻接表) | 非 Linux 平台具备命令隔离机制，或明确决定不提供并记录风险接受的依据 |
| G13 | 移除 ACP 前端，让终端与 Web 功能对等 | [产品定义](design/product.md#前端与平台)、[应用接口规范](spec/application-interface.md) | ACP 包、CLI 入口、冒烟与测试引用已移除；5 组终端侧端口已并入 `frontend` 契约；Web 已具备 MCP、附件、仓库/诊断、扩展、记忆写入、Agent、压缩/分支/导出、工作流提示、指令文件与帮助的 HTTP 接口与工具面板。验收进展：完整 pytest 已在具备依赖的环境执行（609 通过、7 失败，失败为沙箱临时目录 5 条与 Windows 进程组、析构告警 2 条），工具面板已在真实浏览器经 CDP 验收（11 项检查通过），见 [E25](flow.md#验证证据)、[E26](flow.md#验证证据)；待办只剩 POSIX 环境的终端冒烟与真实按键验收（Windows 不提供终端） | 产品、架构、接口与包职责只描述两个前端；两端共用同一契约并暴露同一组用户操作；自动用例与真实浏览器/终端验收通过 |
| G14 | 对齐 Windows 平台上的工具链与路径语义 | [工具](spec/tools.md)、[运行时](spec/runtime.md)、[质量验收](design/constraints.md#验证方式) | 已修：`read_file` 按行读取时不再保留 CRLF 的回车符；权限策略把 Windows 驱动器相对路径（`/etc/passwd` → `C:\etc\passwd`）与绝对路径同样判为工作区外；`tests/conftest.py` 创建 `HOME` 后 Git Bash 不再打印 MSYS2 首启横幅；命令工具的 cwd 断言改用 `pwd -W` 与分隔符归一化，LSP 与工作区 display 用例不再按 POSIX 拼写断言，见 [E26](flow.md#验证证据)。仍缺：`run_command` 与 `bash` 固定调用 `bash -lc`，Windows 默认解析到未安装发行版的 WSL 占位程序，只有把 Git Bash 置于 PATH 前才可用，启动时也没有校验或提示；Windows 上进程组终止用例仍失败。证据见 [E25](flow.md#验证证据)、[E26](flow.md#验证证据) | Windows 上命令工具不依赖未声明的 shell，或启动时明确校验并提示；文件工具按行读取时把 CRLF 当作行尾；绝对路径守卫覆盖驱动器相对路径；相关用例在 Windows 上或通过、或按记录的依据跳过，平台失败从基线中清除 |

## 证据入口

以上未关闭缺口依据 2026-10-29 工作区源码和测试定义整理，尚未完成全产品验收。实际检查结果见 [Flow](flow.md#验证证据)，工作更新方法见[开发流程](development.md#开发前后的进度同步)。
