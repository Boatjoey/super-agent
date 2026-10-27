# 仓库 Agent 工作入口

本文件面向在本仓库中执行开发工作的 Agent。用户使用说明见 [README.md](README.md)，开发操作步骤见 [Development](docs/development.md)。

## 必读顺序

1. 阅读 [文档职责与决策权](AGENTS.md#文档职责与决策权)，按唯一出处查找规则。
2. 开始开发前阅读 [Gap](docs/gap.md) 和 [Flow](docs/flow.md)，关联本次工作与开发节点。
3. 按 [Development](docs/development.md) 选择开发流程，阅读涉及领域的设计与 Spec 后再修改。
4. 完成后按开发流程同步 Gap 和 Flow，记录真实验证结果；未执行的检查不得报告通过。

## 执行要求

- 文档正文使用简体中文；代码标识符、命令、路径、配置键和精确协议文本保留原文。
- 遵守[文档内容归属与去重规则](AGENTS.md#内容归属与去重规则)。行为变化先修改负责的 Spec；修复实现使其符合有效 Spec 时无需改写该 Spec。
- 实现必须满足相关设计与 Spec，不能仅凭现有代码推断预期行为。
- 不得提交密钥等秘密信息。

## 规则入口

| 工作主题 | 必读文档 |
|---|---|
| 产品范围与入口 | [产品定义](docs/design/product.md)、[系统范围](docs/design/software-architecture.md#系统范围) |
| 架构、包依赖和文件分工 | [软件架构](docs/design/software-architecture.md)、[模块职责](docs/spec/packages.md) |
| 状态、转移、守卫与动作计划 | [状态机](docs/spec/machine.md) |
| 调度、事务提交、取消和过期结果 | [运行时](docs/spec/runtime.md) |
| 会话、指令、持久化与恢复 | [会话](docs/spec/session.md) |
| 界面、操作体验与应用边界 | [UI](docs/design/ui.md)、[UX](docs/design/ux.md)、[终端](docs/spec/terminal.md)、[应用接口](docs/spec/application-interface.md) |
| 工具、MCP、网络与隔离 | [工具](docs/spec/tools.md) |
| 权限模式、配置与环境变量 | [配置](docs/spec/config.md) |
| 编码、并发、测试、验证与构建 | [Development](docs/development.md) |

## 文档职责与决策权

本节是文档职责、内容归属和决策权的唯一出处。每份文档只维护表中属于自己的事实；涉及其他主题时链接到负责文档，不复制定义、规则、清单或状态。

| 文档 | 唯一职责 | 不承载的内容 |
|---|---|---|
| [README.md](README.md) | 面向使用者的安装、配置、启动和使用示例，以及使用参考入口 | 仓库开发规则、文档治理、内部任务和进度 |
| 本文件 | 面向仓库 Agent 的必读顺序、执行要求、文档职责、决策权和规则导航 | 用户使用教程、详细开发步骤，以及领域规范的第二份正文 |
| [vision.md](docs/design/vision.md) | 项目为何存在、服务谁、希望提供什么价值 | 功能清单、实现方案和阶段完成情况 |
| [product.md](docs/design/product.md) | 用户场景、产品能力范围、产品取舍与边界 | 概念定义、具体协议、任务清单和开发流程 |
| [concepts.md](docs/design/concepts.md) | 业务术语及其关系，包括 Session、Turn、Step 和输入归属 | 调度算法、按键、数据字段和实现进度 |
| [ui.md](docs/design/ui.md) | 布局、视觉层次、配色语义及界面示意 | 交互流程、精确按键和通知协议 |
| [ux.md](docs/design/ux.md) | 用户操作流程、反馈时机及恢复体验 | 布局配色、按键表和接口字段 |
| [software-architecture.md](docs/design/software-architecture.md) | 逻辑职责、系统边界、依赖方向及架构约束 | 文件分工、具体类型、导入规则和算法细节 |
| [constraints.md](docs/design/constraints.md) | 授权、一致性、恢复等跨领域质量目标 | 具体限额、产品范围和验证命令 |
| [packages.md](docs/spec/packages.md) | 架构到包、文件、端口及类型的映射与导入约束 | 业务行为、运行算法和开发操作步骤 |
| [machine.md](docs/spec/machine.md) | 状态、事件、转移、运行数据、守卫、不变量和动作计划语义 | Engine 调度算法、持久化顺序和开发教程 |
| [runtime.md](docs/spec/runtime.md) | Step 执行边界、调度、原子提交、运行有效性及遥测记录语义 | 转移表、会话历史操作、配置键和文件职责表 |
| [session.md](docs/spec/session.md) | 上下文组装、会话历史、持久化格式与兼容、恢复、压缩、重置、撤销、附件和委派 | 终端命令语法、调度算法和文件访问算法 |
| [application-interface.md](docs/spec/application-interface.md) | 前端应用端口的命令、视图、通知、关联标识及结果协议 | 界面布局、按键、领域规则及实现进度盘点 |
| [terminal.md](docs/spec/terminal.md) | 终端输入输出、精确按键、命令语法、补全和渲染行为 | 业务用例算法、视觉方案和应用接口字段 |
| [tools.md](docs/spec/tools.md) | 工具注册与执行、路径访问、MCP/LSP 行为、网络防护和隔离 | 配置键定义、会话生命周期和文件分工 |
| [config.md](docs/spec/config.md) | 配置键、默认值、来源、优先级、参数、环境变量和校验 | 工具执行机制、上下文加载算法及界面方案 |
| [workspace.md](docs/spec/workspace.md) | 工作区主题的跨文档导航 | 独立规则、实现地图或能力完成声明 |
| [gap.md](docs/gap.md) | 需要完成的工作、目标引用、当前缺口和工作完成条件 | 产品规则的重新定义、节点状态、依赖及验证执行记录 |
| [flow.md](docs/flow.md) | 开发节点拆分、Gap 关联、状态、依赖、阻塞和实际验收证据 | 重写 Gap 的完成条件、定义产品行为或开发方法 |
| [development.md](docs/development.md) | 开发步骤、编码与测试约定、验证命令、构建方法和记录操作 | 产品行为、磁盘协议、具体待办和实时执行结果 |

顶层设计由项目负责人把控；新增或改变顶层取舍须先确认。已明确确认的决策可直接落文档，日常修复和范围内实现不额外审批。Spec 细化设计，不能自行改变上层约定。顶层设计不写代码目录、具体类型、函数、导入规则或测试落点。

### 内容归属与去重规则

- 同一事实只维护一处正文。导航链接、目标引用及明确标为示意的例子不构成第二份规范；其他文档不得另写同义规则或验收清单。
- 设计说明目标与原则，Spec 定义该领域可执行、可验证的行为。实现不符合有效 Spec 时修复实现；有意改变契约时按[开发流程](docs/development.md)先更新负责文档。
- Gap 的完成条件引用设计或 Spec，说明该项工作怎样交付；具体行为断言保留在所属 Spec。Flow 通过 Gap ID 和交付物引用推进工作，不抄写完成条件。
- 验证方法与命令归 Development，实际执行结果及证据归 Flow；Gap 只保留证明缺口的源码、测试定义或 Flow 证据引用。
- 新增事实先定位负责文档，再修改；迁移事实时删除旧正文并更新所有引用。新增文档须先在本表定义唯一职责。
- 不新增第二套任务清单、节点状态表或按日期堆积的长期计划。临时实施笔记不能覆盖设计、Spec、Gap 或 Flow。
