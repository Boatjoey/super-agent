# 待完成工作（Gap）

Gap 是我们需要努力完成的事情。本文件集中维护这些工作：需要达成什么、当前缺少什么、怎样判断完成。每项工作关联目标依据和当前缺口；开发节点的状态与依赖由 [flow](flow.md)维护，开发方法见[开发流程](development.md)。

工作可以是补齐能力、修复行为、明确尚未确定的需求，或完成必要验证。已有代码和检查结果用于说明工作依据，不能代替待完成事项及其完成条件。目标定义以[产品定义](design/product.md)、[项目愿景](design/vision.md)和[质量约束](design/constraints.md)为准。

## 已知待完成工作

以下按独立工作划分，ID 保持稳定，表格顺序不代表实施顺序；具体依赖见 Flow。当前清单是工作基线，后续继续补充；完成的条目直接从清单移除，本文件不保留归档。

| Gap | 需要完成的事情 | 目标依据 | 当前缺口 | 完成条件 |
|---|---|---|---|---|
| G09 | 为非 Linux 平台提供命令隔离沙箱 | [工具沙箱](spec/tools.md#沙箱)、[配置](spec/config.md#沙箱) | macOS 已于 2026-11-14 使用系统自带的 `sandbox-exec` 实现严格隔离，差异见[工具沙箱](spec/tools.md#沙箱)。仍缺：Windows 在未显式设置时自动降级为 `off` 并提示 `sandbox_downgraded`，命令以完整权限运行；Windows 上的真隔离（Windows Sandbox / AppContainer / Job Objects）尚未实现，Job Objects 只能限资源、不能限文件访问。项目负责人已于 2026-10-29 决定实现该能力，不采用“明确不提供并接受风险”的收口方式；实施节点见 [D107](flow.md#开发节点邻接表) | 非 Linux 平台具备命令隔离机制，或明确决定不提供并记录风险接受的依据 |
| G14 | 对齐 Windows 平台上的工具链与路径语义 | [工具](spec/tools.md)、[运行时](spec/runtime.md)、[质量验收](design/constraints.md#验证方式) | 已修：`read_file` 按行读取时不再保留 CRLF 的回车符；权限策略把 Windows 驱动器相对路径（`/etc/passwd` → `C:\etc\passwd`）与绝对路径同样判为工作区外；`tests/conftest.py` 创建 `HOME` 后 Git Bash 不再打印 MSYS2 首启横幅；命令工具的 cwd 断言改用 `pwd -W` 与分隔符归一化，LSP 与工作区 display 用例不再按 POSIX 拼写断言。仍缺：`run_command` 与 `bash` 固定调用 `bash -lc`，Windows 默认解析到未安装发行版的 WSL 占位程序，只有把 Git Bash 置于 PATH 前才可用，启动时也没有校验或提示；Windows 上进程组终止用例仍失败。 | Windows 上命令工具不依赖未声明的 shell，或启动时明确校验并提示；文件工具按行读取时把 CRLF 当作行尾；绝对路径守卫覆盖驱动器相对路径；相关用例在 Windows 上或通过、或按记录的依据跳过，平台失败从基线中清除 |
| G28 | 运行时引擎与会话改用显式组合 | [执行约束](design/software-architecture.md#执行约束)、[文件分工](spec/packages.md#文件分工)、[实现与重构](development.md#实现与重构) | `runtime/engine/engine.py` 的 `Engine` 由 `CommandsMixin`、`ActionLoopMixin`、`QueryMixin` 拼成，`runtime/session` 另有 `TurnMixin`、`PersistenceMixin`、`CheckpointMixin`、`ExportMixin`、`AttachmentsMixin`、`HistoryMixin`；成员依赖靠隐式共享，需要在 `TYPE_CHECKING` 中声明协议桩才能通过类型检查，也难以单独测试 | 引擎与会话拆为显式持有依赖的协作对象，不再使用 mixin；唯一调度权威、锁与提交顺序、取消与过期结果的语义符合[运行时规范](spec/runtime.md)，转移、引擎与并发压力测试覆盖改动；文件分工同步到[模块职责](spec/packages.md#文件分工) |
| G29 | 明确 `app` 包中组合根与设施适配器的边界 | [职责的严格判据](design/software-architecture.md#职责的严格判据)、[六边形边界的代码约束](spec/packages.md#六边形边界的代码约束) | `app` 同时容纳组合根、配置与指令文件适配器、出站设施和兼容导出，规范需要逐文件列表说明归属；包名与 `application` 相近，从名称看不出职责区别 | 项目负责人在“拆为独立的组合根包与设施包”和“在 `app` 内分子包”之间选定方案；先更新负责的设计与[模块职责](spec/packages.md)，再调整代码与依赖检查；启动顺序与用户行为不变 |
| G30 | 收敛 `Any` 并拆分超大文件 | [实现与重构](development.md#实现与重构)、[Python 约定](development.md#python-约定) | 生产代码有 196 处 `Any`，集中在协议、JSON 投影与流式回调；`application/agent_application.py`（689 行）、`store/store.py`（653 行）、`app/config.py`（621 行）各自承载多项职责 | `Any` 不超过 100 处，JSON 值与流式片段使用具名类型；上述文件按职责拆分，并同步[模块职责](spec/packages.md#文件分工)；行为与持久化格式不变 |
| G33 | 在三个平台上运行持续集成 | [前端与平台](design/product.md#前端与平台)、[验证方式](design/constraints.md#验证方式) | 持续集成只在 `ubuntu-latest` 上运行，macOS 与 Windows 上的工具、路径与沙箱行为没有自动验证 | 持续集成在 Linux、macOS、Windows 上运行适用检查；与平台相关的跳过都写明依据，没有静默跳过 |
| G35 | 建立性能基准与遥测汇总 | [遥测](spec/runtime.md#遥测)、[质量约束](design/constraints.md) | 没有启动耗时、长会话回放与流式通知去重的基准；`estimate_tokens` 是粗略估算，影响上下文压缩的时机；遥测 JSONL 没有按轮次与步骤汇总的耗时视图 | 基准可复现运行，结果有记录；token 估算用服务商返回的用量校正；可按轮次与步骤查看模型首 token、工具执行与审批等待耗时；涉及持久化格式的优化先更新[会话规范](spec/session.md) |
| G36 | 完善工程化门槛与发布流程 | [开发命令](development.md#开发命令)、[构建](development.md#构建)、[完成标准](development.md#完成标准) | 覆盖率检查没有下限；没有版本号、变更记录与发布流程的约定；`tools/web.py` 使用 `httpx`、`llm/openai.py` 使用 `httpx2`，两个 HTTP 客户端库并存，必要性未说明；没有提交前检查 | 覆盖率下限与[度量脚本](development.md#开发命令)的指标进入持续集成门禁；完成一次从打标签到安装后启动的发布演练；HTTP 客户端依赖的取舍有结论；开发流程文档同步更新 |
| G40 | Linux 严格沙箱在限制非特权用户命名空间的系统上可用或明确提示 | [工具沙箱](spec/tools.md#沙箱)、[验证方式](design/constraints.md#验证方式) | GitHub Actions 的 `ubuntu-latest`（Ubuntu 24.04）上，`bwrap --unshare-all` 在新网络命名空间中配置回环网卡失败（`loopback: Failed RTM_NEWADDR: Operation not permitted`），严格沙箱集成用例曾因此在持续集成中始终跳过；2026-11-15 起运行器放开该限制，用例在持续集成中实际运行且不允许跳过（运行 43712907491）。Ubuntu 24.04 默认的 AppArmor 非特权用户命名空间限制可能使普通 Linux 用户在严格模式下每条命令都失败，尚未在真实桌面或服务器上复现；Linux 启动时也不像 macOS 那样试运行一条命令 | 确认受影响的系统与条件；严格模式在这类系统上可用，或在启动时试运行并明确提示处理办法，而不是逐条命令失败 |
| G41 | 明确命令分类与网页文本提取的未决规则 | [配置：权限](spec/config.md)、[工具](spec/tools.md)、[授权与工作范围](design/constraints.md#授权与工作范围) | D100 的生成式测试发现以下行为没有规范依据：允许与拒绝前缀是否逐个匹配链式命令（当前 `git status; touch x` 命中 `git status` 的允许规则）；`deny_env` 是否覆盖子 shell 中的赋值（`(AWS_PROFILE=x aws …)` 当前未命中）；名称经计算得出的命令（`${X:-rm}`、`$(printf rm)`、`$'\x72m'`）按未知还是最严处理；macOS 不区分大小写，`RM` 等大写命令名会执行真实命令却不被分类；`npm i`、`find -delete`、`git branch -D`、`mkfs.ext4` 的基础分类；引号内的 `>` 目前被保守地按写入处理（`git log --format='%h -> %s'` 判为写入）；网页文本是否包含隐藏元素、`<template>` 与 `javascript:` 链接 | 项目负责人对上述行为作出决定并写入负责的规范；实现与生成式测试符合规范 |

## 说明

G09、G14 依据 2026-10-29 工作区源码和测试定义整理，G26 至 G39 依据 2026-11-14、G40、G41 依据 2026-11-15 的源码统计、文档核对、持续集成与测试结果整理，尚未完成全产品验收。工作更新方法见[开发流程](development.md#开发前后的进度同步)。
