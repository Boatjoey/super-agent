# 待完成工作（Gap）

Gap 是我们需要努力完成的事情。本文件集中维护这些工作：需要达成什么、当前缺少什么、怎样判断完成。每项工作关联目标依据和当前缺口；开发节点的状态与依赖由 [flow](flow.md)维护，开发方法见[开发流程](development.md)。

工作可以是补齐能力、修复行为、明确尚未确定的需求，或完成必要验证。已有代码和检查结果用于说明工作依据，不能代替待完成事项及其完成条件。目标定义以[产品定义](design/product.md)、[项目愿景](design/vision.md)和[质量约束](design/constraints.md)为准。

## 已知待完成工作

以下按独立工作划分，ID 保持稳定，表格顺序不代表实施顺序；具体依赖见 Flow。当前清单是工作基线，后续继续补充；完成的条目直接从清单移除，本文件不保留归档。

| Gap | 需要完成的事情 | 目标依据 | 当前缺口 | 完成条件 |
|---|---|---|---|---|
| G05 | 建立验证环境并完成基线与阶段验收 | [质量验收](design/constraints.md#验证方式) | 应用此前在非 POSIX 平台上导入即失败，`tests/llm` 也因缺少依赖声明无法收集，两者已修复；POSIX 验证环境已建立，pytest、ruff、pyright 与 `npm` 均可执行：全仓 650 通过、1 跳过（跳过项为非 Linux 严格沙箱用例），覆盖率 82%，`./scripts/verify.sh` 全部门禁通过（`npm` 检查、`ruff format --check`、`ruff check`、`pyright`、测试、并发与覆盖率）；验证环境与基线一项已由项目负责人随 [D01](flow.md#开发节点邻接表) 验收，真实终端验收也随 [D13](flow.md#开发节点邻接表)、[D47](flow.md#开发节点邻接表) 通过；Windows 基线未在该平台重跑，平台侧缺口见 [G14](#已知待完成工作)；阶段产品验收仍未执行，待 [D48](flow.md#开发节点邻接表) 完成后进入 [D90](flow.md#开发节点邻接表) | 建立可执行验证环境，完成适用自动检查、平台隔离和终端验收；按确认的场景完成阶段产品验收并记录真实结果 |
| G09 | 为非 Linux 平台提供命令隔离沙箱 | [工具沙箱](spec/tools.md#沙箱)、[配置](spec/config.md#沙箱) | `strict` 依赖 Linux `bubblewrap`，非 Linux 平台当前在未显式设置时自动降级为 `off` 并提示 `sandbox_downgraded`，命令以完整权限运行；Windows 上的真隔离（Windows Sandbox / AppContainer / Job Objects）尚未实现，Job Objects 只能限资源、不能限文件访问。项目负责人已于 2026-10-29 决定实现该能力，不采用“明确不提供并接受风险”的收口方式；实施节点见 [D48](flow.md#开发节点邻接表) | 非 Linux 平台具备命令隔离机制，或明确决定不提供并记录风险接受的依据 |
| G14 | 对齐 Windows 平台上的工具链与路径语义 | [工具](spec/tools.md)、[运行时](spec/runtime.md)、[质量验收](design/constraints.md#验证方式) | 已修：`read_file` 按行读取时不再保留 CRLF 的回车符；权限策略把 Windows 驱动器相对路径（`/etc/passwd` → `C:\etc\passwd`）与绝对路径同样判为工作区外；`tests/conftest.py` 创建 `HOME` 后 Git Bash 不再打印 MSYS2 首启横幅；命令工具的 cwd 断言改用 `pwd -W` 与分隔符归一化，LSP 与工作区 display 用例不再按 POSIX 拼写断言。仍缺：`run_command` 与 `bash` 固定调用 `bash -lc`，Windows 默认解析到未安装发行版的 WSL 占位程序，只有把 Git Bash 置于 PATH 前才可用，启动时也没有校验或提示；Windows 上进程组终止用例仍失败。 | Windows 上命令工具不依赖未声明的 shell，或启动时明确校验并提示；文件工具按行读取时把 CRLF 当作行尾；绝对路径守卫覆盖驱动器相对路径；相关用例在 Windows 上或通过、或按记录的依据跳过，平台失败从基线中清除 |

## 说明

以上未关闭缺口依据 2026-10-29 工作区源码和测试定义整理，尚未完成全产品验收。工作更新方法见[开发流程](development.md#开发前后的进度同步)。
