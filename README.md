# RecurDyn Codex

RecurDyn Codex 为 RecurDyn 二次开发提供 Python 命令工具、Codex 工作区说明和技能。项目通过本机安装的官方 ProcessNet Python SDK 连接 RecurDyn，支持读取已有模型、复用参数化模板、运行动态仿真和导出结果，并为 Codex 按机械关系编写新建模脚本提供本地接口查询、帮助检索和可运行示例。

## 项目介绍

本项目面向希望通过 Python 和 Codex 开展 RecurDyn 建模与仿真自动化的工程师、研究人员和开发者。它把环境配置、接口查找、模型读取、脚本执行和结果校验组织成可复用流程，减少每次开发都重新搭建连接和检索官方资料的工作。

在 Codex 中打开仓库目录后，可以用自然语言说明模型路径、刚体与关节关系、驱动和载荷、参数变化或结果需求。Codex 根据技能指引调用现有工具，或查询本机 SDK 和官方案例后编写 Python。模型的单位、尺寸、坐标、质量和力学条件仍需要明确给出，缺少影响建模的信息时应先补齐。

主要有两条工作路径：

- **已有模型自动化**：从保存的 RDYN/RDX 文件建立递归索引，查询刚体、关节连接、Marker、Motion、Force 和参数依赖；需要全局坐标或公式求值时再通过 API 补查，随后生成参数变体、仿真并导出结果。
- **按关系编写新模型**：整理机械规格，查找已安装 SDK 的真实接口及官方 Python 案例，参考项目示例生成脚本，通过 `run-script` 执行，再保存模型、回读结构，并在请求仿真时检查实际求解结果。

模型读取采用 **RDX 优先、API 按需补查** 的方式：完整文件组和索引保存在本地，向 Codex 提供摘要或指定字段，减少把大段 XML 和重复对象遍历结果放入对话。具体速度和上下文节省程度取决于模型规模及查询任务。

## 当前状态与验证范围

当前为 **v0.2 实验性版本**，适合小范围试用和进一步二次开发。已验证的环境是 Windows 64 位、RecurDyn 2024 / ProcessNet 10.2.45533.2024、Python 3.10.13 和 pywin32。

本地验证覆盖了基础模型连接、递归索引、定向 API 补查、模板改参、自由落体解析解、驱动连杆轨迹以及嵌套子系统坐标。分享包还在同一台电脑的独立解压目录中完成了初始化、CHM 解包、官方示例读取和建模运行验证。

这些结果有以下边界：

- 尚未在第二台电脑实测；独立副本验证明确提供了安装和 Python 路径，不能据此保证各种本机环境都能自动发现和配置。
- 新机构代码生成仍依赖 Codex 对规格和文档的理解；目前没有陌生需求的独立成功率测试，也没有通用的自然语言或 JSON 模型编译器。
- 模板回读检查涵盖层级、引用、未修改公式和改参值，尚未逐项验证全部质量、惯量、坐标、接触及求解设置的物理等价性。
- **已知复制问题**：RDX 配套文件使用子目录相对路径时，当前 `copy_bundle` 会把文件复制到顶层而保留原引用，导致复制后的文件组缺失引用文件。此问题已通过离线路径布局复现，当前模板和复制流程应避免使用这类文件组。

项目使用接收方本机安装的 SDK、帮助文档和许可证，不附带 RecurDyn 本体、官方 SDK、CHM 或 Python/conda 环境。基础示例的验证不能覆盖复杂接触、柔性体、专业工具包或联合仿真。

## 项目结构

| 路径 | 用途 |
|---|---|
| `recurdyn_control/` | Python 会话、命令入口、RDX 索引、模板、文档检索和结果导出 |
| `skills/recurdyn-control/` | Codex 调用流程、命令参考和建模指南 |
| `examples/` | 自行编写的建模示例及任务/关系规格模板 |
| `initialize.ps1` | 检查本机环境，生成运行配置，可选解包 CHM |
| `rd.ps1` | 使用配置中的 Python 启动命令工具 |
| `recurdyn-config.example.json` | 路径配置参考；首次初始化会生成本机 `recurdyn-config.json` |

## 能做什么

| 能力 | 现有入口 | 当前验证范围 |
|---|---|---|
| 检查环境、连接/启动软件、列出打开模型 | `doctor / start / status` | Windows 主机 COM |
| 读取保存模型的递归结构、关节连接、Marker、Motion、Force、参数依赖 | `scan / query` | 2024 RDX 文件组；基础嵌套模型验证，未知属性保留 |
| 补查全局坐标系和公式求值 | `query --api-missing` | 已适配字段；来源/缺失明确标记 |
| 复制旧模型、改指定参数生成新模型 | `template / instantiate` | 层级、连接、引用和未修改公式回读检查 |
| 改 numeric PV、设置时长/步数并动态仿真 | `job` | 原模型保留；用实际时间通道确认完成 |
| 查询结果通道、导出 CSV | `channels / export` | 校验通道名、长度和有限数值 |
| 创建和校验基础模型 | `demo` | 自由落体建模/求解/解析解验证 |
| 查官方 Python 接口、属性类型、枚举和示例 | `docs-paths / api-search / docs-search / docs-read` | 从对方本机安装读取；CHM 可自动解包 |
| 根据刚体/关节/驱动/力的关系编写新模型 | 建模技能 + `examples/modeling/` + `run-script` | 驱动连杆/弹簧和嵌套坐标示例；新机构逐项查文档并验证 |

参数扫描可以由 Codex 生成多份 job，串行调用并汇总；当前没有通用优化器、GUI 任务面板、MCP 服务或求解器逐步联合仿真入口。复杂接触、柔性体、CAD、用户 DLL/工具包和任意新机构建模需要具体模型/接口开发，不能把基础案例验证视为这些能力已经全面验证。

## 首次使用

需要 Windows、本机安装的 RecurDyn（当前验证版本为 2024）及可用许可证；推荐已有 64 位 Python 3.10 环境并包含 pywin32。本包不附带 RecurDyn、许可证或 Python 环境。

1. 克隆仓库或下载 ZIP 并解压到可写目录，用 Codex 打开包含 `AGENTS.md` 和 `rd.ps1` 的仓库根目录。
2. 发送下面的“首次配置”提示。Codex 会读取 AGENTS.md 和技能，检查本机环境并生成本机配置。
3. 配置成功后直接给出模型路径和任务需求，无需记住 CLI 命令。

首次配置提示：

> 请读取 AGENTS.md 和 skills/recurdyn-control/SKILL.md，检查这台电脑的 RecurDyn 安装和 Python/conda 环境，用 initialize.ps1 配置本机路径和帮助路径，加 -ExtractProcessNet 准备官方 Python 示例，再运行 doctor 和 docs-paths。模型和软件安装目录保持只读；先验证连接，暂不运行仿真。

初始化脚本自动检测常见安装位置、注册表安装信息、当前 conda 环境和用户的 conda 环境列表。多个合适环境时列出候选，由对方选择；找不到时提供明确路径。脚本生成包内配置；加 `-ExtractProcessNet` 时把只读 CHM 复制、解包到包内 `.reference/`。不安装依赖或修改软件/注册表。

也可以手动执行一次：

```powershell
.\initialize.ps1 -PythonExecutable 'C:\envs\recurdyn\python.exe' -RecurDynInstallDir 'C:\Program Files\FunctionBay, Inc\RecurDyn 2024' -ExtractProcessNet
.\rd.ps1 doctor
.\rd.ps1 docs-paths
```

上面路径仅为示例。若缺少 pywin32，可在选定环境中安装 `requirements.txt`；由对方决定使用哪个环境。Codex 隔离执行可能看不到 COM 注册，真实调用需要该会话获准的 Windows 主机执行权限；不要因此自动改注册表或重装软件。其他 Python/RecurDyn 版本须本机验证兼容性。

## 日常直接复制的提示词

读取旧模型：

> 分析 C:\Models\mechanism.rdyn。先用 RDX 建立索引，给我子系统、刚体、关节连接、驱动、力和参数依赖的摘要。需要全局坐标或公式数值时再用 API 补查，完整 XML 不放进对话。

从旧模型生成变体：

> 从这个模型创建可复用模板，把 Speed 改成 20，生成独立模型。保留已有连接和依赖公式，输出到新的 runs 目录，并重新读取验证。若参数重名先用索引确认完整名称。

仿真和后处理：

> 用这个模型的副本仿真 1 秒、输出 100 步。先确认模型单位和参数，完成后读取真实结果通道，导出我指定刚体的位移和速度 CSV，确认求解达到结束时间。

多工况：

> 把这个模型的 Stiffness 分别设为 100、150、200，每个工况放在独立目录，串行运行并比较同一个结果通道的峰值。先核对 Stiffness 的完整名称和单位。

按关系从头建模：

> Ground 和 Link 用 Z 轴转动副连接，转轴在原点。Link 是 0.2×0.04×0.04 m 的均匀长方体，中心初始在 (0.1,0,0)，质量 0.25 kg；使用 MKS，重力为零。转角按 0.2*TIME rad 驱动。Ground 的 (0,1,0) 和 Link 初始的 (0.2,0,0) 之间接弹簧，刚度 200 N/m、阻尼 1 N·s/m，自由长度取初始距离。请读建模指南和相关示例，查询本机 SDK/帮助后生成 Python，保存独立模型，仿真 0.2 秒并核验连接和运动轨迹。

Codex 应先整理关系和单位/坐标等规格，按需询问影响建模的缺失信息，查询官方接口和 Python 案例，生成脚本，再通过 `run-script` 执行、校验和回读。完整流程见 [建模指南](skills/recurdyn-control/references/model-building.md)。本包的关系 JSON 用于表达/核对需求，不是任意 JSON 自动编译模型的通用引擎。

也可先运行包内示例：

```powershell
.\rd.ps1 run-script examples/modeling/hinge_motion_spring.py --output runs/hinge_001
.\rd.ps1 run-script examples/modeling/nested_system.py --output runs/nested_001
```

前一个验证指定运动轨迹、质量、弹簧参数及连接；后一个只建模，验证层级和局部/全局坐标。指定运动的轨迹正确不能独立证明弹簧反力正确。

这里的名称、数值、单位和模型路径应替换为实际需求；这些提示调用现有工具或让 Codex 编写额外 Python，不能保证任意专业模型会一次完成。

若还要分享自己的模型，可额外发送 `template` 生成的整个模板目录。对方可以指明该模板和参数，让 Codex 使用 `instantiate` 生成独立模型。不要只发索引 JSON 或单独 `.rdx`；模板文件组和实际依赖的外部资源应完整。

## 可选：安装为个人技能

直接打开本包目录已经可用。若希望在其他项目里通过 `$recurdyn-control` 调用，可把 `skills/recurdyn-control` 整个目录复制到自己的 Codex 技能目录：通常为 `%USERPROFILE%\.codex\skills\recurdyn-control`，设置了 `CODEX_HOME` 时用其 `skills` 子目录。

让新会话加载该技能后，可以发送：

> 使用 $recurdyn-control，工具包目录是 D:\Tools\recurdyn-codex，分析 C:\Models\mechanism.rdyn，说明关节连接和参数依赖。

技能提供调用流程，Python 工具仍来自解压目录。多项目使用时明确给出工具包目录，输出保存在工具包的 runs 内，或为该项目解压一份独立副本。

## 分享的内容和验证

本包包含本工具源码、启动/初始化脚本、技能、通用 JSON 模板和自行编写的可运行建模示例。没有作者的本机配置、模型、仿真结果、COM 缓存、官方 SDK 或帮助副本。

SDK 从对方安装的 `Bin\Python\Lib\recurdyn` 读取，包含 ProcessNet 和其他模块；`Bin\Python\ProcessNetTemplate.py` 是官方入口模板。conda 环境提供 Python/pywin32，接口不需要再从 pip 安装。安装根目录确定后，会自动推导使用帮助 HTML、ProcessNet CHM 和 Help 案例路径；特殊位置可用 `-RecurDynHelpIndex`、`-ProcessNetChm`、`-ExamplesRoot`、`-ProcessNetHtmlDir` 覆盖。CHM 中的官方 Python 示例通过 `-ExtractProcessNet` 或 `docs-extract` 准备，随后可以搜索和读取。缺少某个帮助文件时会明确指出路径，SDK 查询仍可使用。

本地已经验证基础嵌套模型、API 补查、模板改参、自由落体和驱动连杆仿真；v0.2 分享包的独立副本还测试了初始化、帮助解包、官方示例读取、模块 API 查询和两个建模示例。独立副本仍在同一台电脑，未在第二台电脑实测，首次使用须完成 doctor 和自己的模型验证。

使用者可以通过仓库源码继续扩展接口和工作流，或将完整模型模板与任务参数一起交给 Codex。首次使用及新增专业功能都应按自己的安装环境和模型完成验证。
