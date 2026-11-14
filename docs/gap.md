# 待完成工作（Gap）

Gap 是我们需要努力完成的事情。本文件集中维护这些工作：需要达成什么、当前缺少什么、怎样判断完成。每项工作关联目标依据和当前缺口；开发节点的状态与依赖由 [flow](flow.md)维护，开发方法见[开发流程](development.md)。

工作可以是补齐能力、修复行为、明确尚未确定的需求，或完成必要验证。已有代码和检查结果用于说明工作依据，不能代替待完成事项及其完成条件。目标定义以[产品定义](design/product.md)、[项目愿景](design/vision.md)和[质量约束](design/constraints.md)为准。

## 已知待完成工作

以下按独立工作划分，ID 保持稳定，表格顺序不代表实施顺序；具体依赖见 Flow。当前清单是工作基线，后续继续补充；完成的条目直接从清单移除，本文件不保留归档。

| Gap | 需要完成的事情 | 目标依据 | 当前缺口 | 完成条件 |
|---|---|---|---|---|
| G09 | 为非 Linux 平台提供命令隔离沙箱 | [工具沙箱](spec/tools.md#沙箱)、[配置](spec/config.md#沙箱) | macOS 已于 2026-11-14 使用系统自带的 `sandbox-exec` 实现严格隔离，差异见[工具沙箱](spec/tools.md#沙箱)。仍缺：Windows 在未显式设置时自动降级为 `off` 并提示 `sandbox_downgraded`，命令以完整权限运行；Windows 上的真隔离（Windows Sandbox / AppContainer / Job Objects）尚未实现，Job Objects 只能限资源、不能限文件访问。项目负责人已于 2026-10-29 决定实现该能力，不采用“明确不提供并接受风险”的收口方式；实施节点见 [D107](flow.md#开发节点邻接表) | 非 Linux 平台具备命令隔离机制，或明确决定不提供并记录风险接受的依据 |
| G14 | 对齐 Windows 平台上的工具链与路径语义 | [工具](spec/tools.md)、[运行时](spec/runtime.md)、[质量验收](design/constraints.md#验证方式) | 已修：`read_file` 按行读取时不再保留 CRLF 的回车符；权限策略把 Windows 驱动器相对路径（`/etc/passwd` → `C:\etc\passwd`）与绝对路径同样判为工作区外；`tests/conftest.py` 创建 `HOME` 后 Git Bash 不再打印 MSYS2 首启横幅；命令工具的 cwd 断言改用 `pwd -W` 与分隔符归一化，LSP 与工作区 display 用例不再按 POSIX 拼写断言。仍缺：`run_command` 与 `bash` 固定调用 `bash -lc`，Windows 默认解析到未安装发行版的 WSL 占位程序，只有把 Git Bash 置于 PATH 前才可用，启动时也没有校验或提示；Windows 上进程组终止用例仍失败。 | Windows 上命令工具不依赖未声明的 shell，或启动时明确校验并提示；文件工具按行读取时把 CRLF 当作行尾；绝对路径守卫覆盖驱动器相对路径；相关用例在 Windows 上或通过、或按记录的依据跳过，平台失败从基线中清除 |
| G25 | 建立优化工作的度量基线，并集中取得顶层决策 | [完成标准](development.md#完成标准)、[验收](development.md#验收)、[质量约束](design/constraints.md) | 度量脚本、基线归档与对外名称清单已就绪，见[开发命令](development.md#开发命令)与[对外名称与兼容入口](spec/packages.md#对外名称与兼容入口)；G29、G31、G32 的取舍已于 2026-11-14 确认，结论记录在 [Flow](flow.md#开发节点邻接表)。仍缺：度量上报步骤尚未在 GitHub Actions 的实际运行中确认 | 基线数据已归档且可复现；上述指标可自动统计并在持续集成中上报；对外名称清单说明每个兼容入口直接删除还是经过废弃周期；G19、G29、G31、G32 的待确认事项已有结论 |
| G26 | 代码标识符遵循 PEP 8 命名 | [Python 约定](development.md#python-约定) | 生产代码有 148 处函数定义、50 种实例属性使用 camelCase（如 `tui/update.py`、`runtime/execution/policy.py` 各 12 处，`runtime/execution/command_analyzer.py` 10 处），不符合命名约定；静态检查未启用命名规则，无法阻止新增违规 | 生产代码与测试的标识符全部符合 [Python 约定](development.md#python-约定)，命名规则纳入静态检查且没有豁免；JSON 键仍由 `json_field` 声明，持久化格式与 Web 协议不变，既有会话记录可正常回放 |
| G27 | 移除内部对兼容门面与重复导出的依赖 | [代码依赖与接口约束](spec/packages.md#代码依赖与接口约束) | `app` 中 4 个模块和测试共 29 处从根 `super_agent.runtime` 门面导入；`app/agent_application.py`、`app/tui_adapter.py`、`app/workflows.py` 只做重新导出，仍被引用 10 处；`runtime/machine`、`runtime/execution`、`runtime/session` 各有一个 `aliases.py`，共 205 行；依赖检查没有禁止内部导入门面 | 内部模块与测试只从拥有类型的包导入；兼容模块按 G25 的对外名称清单删除，或保留并在[模块职责](spec/packages.md)中注明理由；依赖检查新增禁止内部导入门面的规则，含正例与反例 |
| G28 | 运行时引擎与会话改用显式组合 | [执行约束](design/software-architecture.md#执行约束)、[文件分工](spec/packages.md#文件分工)、[实现与重构](development.md#实现与重构) | `runtime/engine/engine.py` 的 `Engine` 由 `CommandsMixin`、`ActionLoopMixin`、`QueryMixin` 拼成，`runtime/session` 另有 `TurnMixin`、`PersistenceMixin`、`CheckpointMixin`、`ExportMixin`、`AttachmentsMixin`、`HistoryMixin`；成员依赖靠隐式共享，需要在 `TYPE_CHECKING` 中声明协议桩才能通过类型检查，也难以单独测试 | 引擎与会话拆为显式持有依赖的协作对象，不再使用 mixin；唯一调度权威、锁与提交顺序、取消与过期结果的语义符合[运行时规范](spec/runtime.md)，转移、引擎与并发压力测试覆盖改动；文件分工同步到[模块职责](spec/packages.md#文件分工) |
| G29 | 明确 `app` 包中组合根与设施适配器的边界 | [职责的严格判据](design/software-architecture.md#职责的严格判据)、[六边形边界的代码约束](spec/packages.md#六边形边界的代码约束) | `app` 同时容纳组合根、配置与指令文件适配器、出站设施和兼容导出，规范需要逐文件列表说明归属；包名与 `application` 相近，从名称看不出职责区别 | 项目负责人在“拆为独立的组合根包与设施包”和“在 `app` 内分子包”之间选定方案；先更新负责的设计与[模块职责](spec/packages.md)，再调整代码与依赖检查；启动顺序与用户行为不变 |
| G30 | 收敛 `Any` 并拆分超大文件 | [实现与重构](development.md#实现与重构)、[Python 约定](development.md#python-约定) | 生产代码有 196 处 `Any`，集中在协议、JSON 投影与流式回调；`application/agent_application.py`（689 行）、`store/store.py`（653 行）、`app/config.py`（621 行）各自承载多项职责 | `Any` 不超过 100 处，JSON 值与流式片段使用具名类型；上述文件按职责拆分，并同步[模块职责](spec/packages.md#文件分工)；行为与持久化格式不变 |
| G31 | 为 Web 界面增加访问认证 | [前端与平台](design/product.md#前端与平台)、[质量约束](design/constraints.md)、[应用接口](spec/application-interface.md) | Web 服务没有认证，只依赖默认监听回环地址；同机其他进程、DNS 重绑定或跨站请求都能访问可触发工具执行的接口；`--host` 可以绑定到非回环地址 | 项目负责人确认认证取舍后，先更新负责的设计、[应用接口](spec/application-interface.md)与[配置](spec/config.md)规范；未认证请求与跨源请求被拒绝，绑定非回环地址时必须启用认证；终端前端不受影响 |
| G32 | 统一沙箱降级规则的规范表述 | [配置：沙箱](spec/config.md#沙箱)、[工具沙箱](spec/tools.md#沙箱) | `tools.md` 规定不受支持的平台必须显式设置 `sandbox.mode: off` 才能启动；`config.md` 规定未显式设置时默认 `strict` 自动降级为 `off` 并记录 `sandbox_downgraded`，只有显式 `strict` 按不支持处理；两处规范互相矛盾 | 项目负责人确认降级策略后，只在负责文档保留一处正文，另一处改为链接；实现与测试符合确认后的规则 |
| G33 | 在三个平台上运行持续集成 | [前端与平台](design/product.md#前端与平台)、[验证方式](design/constraints.md#验证方式) | 持续集成只在 `ubuntu-latest` 上运行，macOS 与 Windows 上的工具、路径与沙箱行为没有自动验证 | 持续集成在 Linux、macOS、Windows 上运行适用检查；与平台相关的跳过都写明依据，没有静默跳过 |
| G34 | 加深命令分类与工具输出的安全测试 | [工具](spec/tools.md)、[质量约束](design/constraints.md) | `runtime/execution/command_analyzer.py` 的 shell 分类没有生成式测试，引号、子 shell、重定向与变量展开的组合缺少覆盖；MCP 与 Web 工具输出中夹带提示注入的情形没有用例 | 上述场景有生成式或专门用例覆盖；发现的问题按[修复 bug](development.md#修复-bug)流程处理 |
| G35 | 建立性能基准与遥测汇总 | [遥测](spec/runtime.md#遥测)、[质量约束](design/constraints.md) | 没有启动耗时、长会话回放与流式通知去重的基准；`estimateTokens` 是粗略估算，影响上下文压缩的时机；遥测 JSONL 没有按轮次与步骤汇总的耗时视图 | 基准可复现运行，结果有记录；token 估算用服务商返回的用量校正；可按轮次与步骤查看模型首 token、工具执行与审批等待耗时；涉及持久化格式的优化先更新[会话规范](spec/session.md) |
| G36 | 完善工程化门槛与发布流程 | [开发命令](development.md#开发命令)、[构建](development.md#构建)、[完成标准](development.md#完成标准) | 覆盖率检查没有下限；没有版本号、变更记录与发布流程的约定；`tools/web.py` 使用 `httpx`、`llm/openai.py` 使用 `httpx2`，两个 HTTP 客户端库并存，必要性未说明；没有提交前检查 | 覆盖率下限与 G25 的度量指标进入持续集成门禁；完成一次从打标签到安装后启动的发布演练；HTTP 客户端依赖的取舍有结论；开发流程文档同步更新 |
| G37 | 让 `tests/build` 下的用例被收集运行 | [测试](development.md#测试)、[完成标准](development.md#完成标准) | pytest 默认的 `norecursedirs` 包含 `build`，`tests/build/test_build_local.py` 从未被收集，构建脚本的用例长期没有执行，也没有检查发现这一点 | 该目录的用例被收集并通过，或迁移到会被收集的目录；测试目录被整体跳过时有检查明确失败 |
| G38 | 在配置规范中补齐钩子事件与 Web 启动参数 | [配置](spec/config.md) | 钩子事件名只存在于 `app/extensions.py` 的 `HOOK_EVENTS`，[扩展](spec/config.md#扩展)没有列出；[命令行参数](spec/config.md#命令行参数与环境变量)表缺少 `--web`、`--host`、`--port` | 规范列出全部钩子事件与上述参数；测试比对规范与实现的清单，格式变化时明确失败 |
| G39 | Linux 严格沙箱隐藏真实 home 目录 | [工具沙箱](spec/tools.md#沙箱)、[授权与工作范围](design/constraints.md#授权与工作范围) | `tools/sandbox_linux.py` 只读挂载宿主根目录，只替换 `/tmp` 与 `/var/tmp`，并把 `HOME` 指向临时目录；真实 `/home/<user>` 仍可按绝对路径读取，包括保存服务商密钥的 `~/.superagent/settings.json` 与 `~/.ssh`。macOS 严格沙箱已拒绝读取 home | 严格沙箱内按绝对路径读取真实 home 失败，工作区位于 home 下时仍可读写；Linux 集成用例覆盖并在持续集成中运行 |

## 说明

G09、G14 依据 2026-10-29 工作区源码和测试定义整理，G25 至 G39 依据 2026-11-14 的源码统计与文档核对整理，尚未完成全产品验收。工作更新方法见[开发流程](development.md#开发前后的进度同步)。
