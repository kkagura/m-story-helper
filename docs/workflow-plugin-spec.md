# Python 流程插件接口（供开发者与智能体阅读）

文档版本：1.6；日期：2026-10-28；插件接口版本：`api_version = 1`。

**状态：已编写插件基础 SDK、显式注册表、协作式上下文和中士占位插件；新增可选 evaluate 单步判断接口、缓存感知、流程列表 API 和通用截图测试；自动运行器、输入工具和真实兑换未实现。** SDK 与测试尚待宿主机验证。异步执行/等待工具仍只有 Protocol 声明；只读对话感知已实现接入，真实 OCR 与输入能力仍需分别验收。当前识别代码仍以手动截图/视频帧为主。总体方案见 [技术方案](../技术方案.md)，实施状态见 [待办](../todo.md)。

## 1. 范围与职责

流程使用 Python 插件编写步骤、分支和有界循环，不再使用流程 JSON、节点图或通用解释器。JSON/YAML 可用于保存启动参数和设置，不承担流程语言的职责。删除的流程 JSON 规范、格式迁移与无环节点约束不再适用；现有视觉配置的严格校验保持原状。

| 部分 | 负责 | 边界 |
| --- | --- | --- |
| 流程插件 `WorkflowPlugin` | 编排步骤，调用共用工具，根据明确反馈决定继续、暂停或结束 | 不直接调用操作系统输入库，不管理窗口句柄或执行租约 |
| 共用工具 | 感知、等待、定位和动作请求；返回类型化证据与回执 | 动作工具生成结构化计划，提交共用引擎校验和执行 |
| 核心引擎 | 注册/启动检查、生命周期、预算、取消、输入绑定、执行、验证与记录 | 不信任脚本自行宣称的成功或许可；不会执行模型生成的 Python |
| 决策插件（技术方案 4.7） | builtin/vlm/hybrid 根据上下文返回 `ActionPlan` | 与流程插件不同，不拥有流程生命周期或直接输入能力 |

内置流程可以直接编排确定性的工具调用，不要求每个步骤调用决策插件。后续需要模型规划时，另提供经兼容检查的规划工具，仍按第 4.7 节计划契约执行，本文不提前引入该接口。

首个插件版本只显式注册随项目发布的可信 Python 插件，每次运行/手动判断创建独立实例。目录发现、上传安装、热更新、第三方依赖和不可信代码隔离属于后续事项；现在仅固定接口，不实现外部加载。工具调用约束是可信代码的开发规则，不是 Python 沙箱。

## 2. 插件接口

接口位于 [base.py](../app/workflows/base.py)。下面摘录插件签名；元数据、证据、回执和返回值采用严格且冻结的 Pydantic 模型，完整字段见后文及源码。工具签名位于 [tools/base.py](../app/workflows/tools/base.py)，输入工具实现留待后续；只读感知已按第7节接入。

```python
from typing import Generic, Protocol, TypeVar
from pydantic import BaseModel
from app.workflows.base import WorkflowContext, WorkflowMetadata, WorkflowResult

ParamsT = TypeVar("ParamsT", bound=BaseModel)

class WorkflowPlugin(Protocol, Generic[ParamsT]):
    metadata: WorkflowMetadata
    params_model: type[ParamsT]

    async def run(
        self, ctx: WorkflowContext, params: ParamsT
    ) -> WorkflowResult: ...
```

### 2.1 注册元数据的输入输出

`metadata` 和 `params_model` 由插件提供给注册表/页面，不是由用户启动请求覆盖。元数据不包含实例运行状态。

| 字段 | 类型与语义 |
| --- | --- |
| `id` | 稳定唯一插件 ID，例如 `orbis_charlie_exchange`；建议 `[a-z][a-z0-9_]*`，最多 64 字符，不是模块路径 |
| `api_version` | 正整数接口主版本，当前拟定 1；引擎不支持时拒绝注册 |
| `version` | 插件内容版本，例如 `1.0.0`；行为或参数变化应更新版本，启动后固定 |
| `task_id` | 注册任务 ID，例如 `npc_material_exchange`，关联分类、动作许可和独立成功验证器；多个流程插件可以服务同一任务 |
| `name/category/description/tags` | 页面名称、分类、说明和标签；分类不会授予执行能力 |
| `required_capabilities` | 需要的注册能力，如 `npc_detection`、`dialogue_ocr`、`dialogue_scroll`、`bounded_input`；按当前适配器判断可用性 |
| `allowed_actions` | 允许请求的底层动作，如 `mouse_click`、`mouse_scroll`；空集合表示只读，与任务/控制器/宿主许可取交集，不是脚本自授权 |
| `params_model` | 继承 WorkflowParams 的 Pydantic 参数模型类；严格校验、冻结、拒绝额外字段；输出参数描述供页面生成表单，由后端创建类型化参数实例 |

注册表输出插件描述（以上元数据和参数 schema）及 `available: bool`、`unavailable_reasons: list[str]`。重复 ID、参数模型无效或不支持接口版本是注册错误；缺少感知或输入能力可展示为不可用，不假装插件已经能运行。Mock 能力不等于真实模式能力。

### 2.2 启动请求与 `params` 入参

后续通过 `GET /api/workflows` 查询注册描述；`POST /api/tasks/{task_id}/validate` 和 `/start` 接收下表流程模式字段，run_kind=workflow。路由 task_id 须与插件 metadata.task_id 一致。与 run_kind=planner 的决策路径互斥，流程模式不同时传 planner 配置；当前已实现 GET /api/workflows；任务 validate/start 尚未实现，手动图片/视频分析按第7节使用。

| 启动字段 | 输入语义 |
| --- | --- |
| `run_kind` | 固定为 `workflow`，区分决策规划器路径 |
| `plugin_id` | 选择注册插件，不能填写任意文件路径或导入表达式 |
| `plugin_version` | 选择确切插件版本；不支持的版本拒绝启动，不静默换成最新 |
| `params` | 仅业务参数；插件模型默认值与用户覆盖值合并，由后端严格校验 |
| `session_id` | 当前有效捕获会话；静态样本只能用于相应感知/Mock 验证 |
| `mode` | `mock` 或 `real`，默认 Mock；真实模式另需已确认的输入绑定 |
| `max_run_ms/max_actions` | 整数活跃运行时间和底层动作次数预算，默认 120000 ms / 256 次；范围分别为 1000–3600000 / 1–1024，宿主可进一步收紧；越界拒绝，布尔值不当整数 |

validate 输出 `valid: bool` 与 `reasons: list[str]`；start 校验成功后输出 `run_id` 和初始状态；失败返回字段错误或缺失能力原因，不创建活动运行。参数不能夹带窗口句柄、模型凭据、Python 路径或执行模式；这些属于宿主管理配置。类型与范围以每个插件参数模型为准，无需为步骤定义一套序列化语言。

例如兑换业务参数模型（也作为后文伪代码的入参）：

```python
from pydantic import Field
from app.workflows.base import WorkflowParams

class CharlieExchangeParams(WorkflowParams):

    npc_name: str = Field(default="查里中士", min_length=1, max_length=100)
    material_name: str = Field(default="僵尸丢失的臼齿", min_length=1, max_length=100)
    material_count: int = Field(default=100, ge=1, le=9999)
    step_timeout_ms: int = Field(default=10000, ge=100, le=60000)
    max_scrolls: int = Field(default=12, ge=0, le=20)
```

启动前冻结有效参数，插件接收 `CharlieExchangeParams` 实例，而不是未经校验的原始字典。运行中更改参数或切换插件需要停止后重新启动。

### 2.3 `ctx` 入参

已编写 [RunContext/WorkflowControl](../app/workflows/context.py) 基础组件，待运行器接入。上下文由核心引擎构造，插件只读取，不能自行替换工具、会话、截止时间或预算。Protocol 表达访问接口，实际实现需提供只读属性，不靠类型注解实现权限控制。

| 成员 | 语义 |
| --- | --- |
| `run_id/session_id` | 本轮运行及所绑定捕获会话，工具结果必须属于该运行/会话 |
| `mode` | Mock 或真实执行，由宿主固定；脚本不能自行开启真实输入 |
| `deadline_monotonic` | 单调时钟的当前活跃执行截止时间；不使用墙上时钟，也不允许脚本延长 |
| `tools` | 本轮有能力/权限约束的工具门面；不暴露原始 Windows 输入适配器 |
| `await checkpoint()` | 检查停止、暂停、会话有效性和预算；循环每轮必须调用，工具自身也检查 |
| `await set_step(step_id, timeout_ms=...)` | 记录当前业务步骤，设定不可自动重置的步骤截止时间并检查取消；timeout_ms 为 100–60000 且受运行预算约束，当前仅保存步骤/时限，不推送事件，不执行动作、不创建可恢复的程序计数器 |

当前 RunContext 使用冻结 dataclass 和引擎持有的 WorkflowControl，checkpoint 协作检查停止、暂停、会话失效、运行/步骤截止时间，set_step 最多保存 256 个不同步骤。同名步骤再次进入只收紧原截止时间，防止重置。control 不交给插件。尚无后台监测、任务调度、步骤事件推送、动作计数、执行租约或窗口时效校验；这些由后续运行器/工具/执行层实现，不能用当前 checkpoint 代替。

执行预算、动作次数、窗口绑定版本等由引擎持有。插件不直接引用媒体缓存和跨帧可变检测；工具返回只读快照或受限引用，历史/在途证据均须有数量、时间和字节上限。

## 3. 共用工具的入参与返回值

`WorkflowTools` 已声明 `vision`、`mouse`、`keyboard`、`dialogue` 四组 Protocol 接口及只读数据引用。下表签名已有声明，但没有任何工具实现，输入约束/页面校验/取消和预算执行均为后续目标。所有异步工具接受正整数 `timeout_ms`，范围 100–60000；有效时限取工具、步骤和运行剩余时间的最小值。组合工具不得给每个子调用重新分配完整时限。

### 3.1 统一返回包装

`ToolResult[T]` 字段：

| 字段 | 类型与含义 |
| --- | --- |
| `status` | `ok / not_found / ambiguous / unknown / timeout / rejected / error` |
| `value` | 成功时为表中指定的类型 `T`，其他状态为 None |
| `code/message` | 稳定原因码和供用户阅读的说明，例如 `target_ambiguous` |
| `evidence` | `tuple[EvidenceRef, ...]`，指向引擎管理的同帧证据，不在返回值复制无限图片 |
| `receipt` | `ActionReceipt \| None`；动作类工具包括组合动作即使失败也应保留回执/关联记录 |

`not_found` 仅表示有效画面上未找到，`unknown` 表示证据不足/识别不可用，`ambiguous` 表示多个候选。等待工具对明确未出现可继续等待到超时，对未知/歧义默认提前返回；不能把未知当作“不存在”。参数/能力/权限不合法为 rejected，内部故障为 error；取消走异常传播，不伪装成 not_found。

`ActionReceipt` 包含 `action_ids: tuple[str, ...]`、`effect: not_sent/sent/outcome_unknown`、`verification: not_checked/confirmed/unknown`、`evidence`。只要部分输入可能已发送就不能返回 not_sent；引擎仍记录全部子动作/结果。sent 不代表画面结果已验证，停止时也可能 outcome_unknown。

EvidenceRef 包括 id/run_id/observation_id/session_id/frame_id/size_version/profile_version，新增的 run_id 用于核验本次运行归属；观测尚无运行时由后续工具包装生成引用。profile_version 为当前视觉配置的内容版本字符串，与现有快照结果一致。完整证据由引擎记录工具 ID、运行/步骤、时钟、来源、前后观测与原因；引用不能赋予访问任意文件的能力。

### 3.2 数据类型

| 类型 | 必含信息 |
| --- | --- |
| `ObservationSnapshot` | 复用现有同帧 frame/result；不拼接新画面与旧检测，工具需标明支持的检测字段 |
| `RegionRef` | id、EvidenceRef、bbox `(x,y,width,height)`，原始帧像素坐标、语义区域 kind |
| `TargetRef` | id、EvidenceRef、bbox、目标 kind、识别身份/文字、置信度；原始帧坐标，非桌面坐标 |
| `TextRead` | 文字块 text/confidence/bbox 及来源 EvidenceRef；置信度不表示已校准准确率 |
| `DialogueRef` | 对话身份 id、npc_name、dialogue_region、内容区/列表区 RegionRef、来源证据 |
| `DialogueEvidence` | dialogue: DialogueRef、matched_text: str、evidence: EvidenceRef |
| `ClosedEvidence` | 原对话身份、之前打开证据与新画面确实关闭的证据；不是一次 OCR 未读到 |
| `SelectionEvidence` | 选中的材料名/数量、确认页证据、滚动次数；不表示库存已核验 |

目标/区域引用在执行前校验运行、会话、配置、尺寸版本和时效，并重新检查目标/页面仍成立；普通新帧不必自动废弃仍有效的目标。坐标由执行层映射到独立绑定窗口，脚本不能把识别坐标当作桌面坐标。

### 3.3 感知和底层动作工具

下列方法均为 `async`，签名省略统一的关键字参数 `timeout_ms: int`，返回均为 `ToolResult[T]`。

| 方法与输入 | T | 行为 |
| --- | --- | --- |
| `vision.observe()` | ObservationSnapshot | 获取最新有效同帧观测，不无限排队、不阻塞接收 |
| `vision.read_text(region: RegionRef)` | TextRead | 在引用区域读取文字，使用与区域一致的画面；新画面需重新定位区域 |
| `vision.find_image(template_id: str, region: RegionRef)` | TargetRef | 使用注册模板在指定画面区域找唯一目标；不接受任意文件路径 |
| `vision.find_npc(name: str)` | TargetRef | 找到唯一可交互 NPC；找不到/多个候选不能随意点击 |
| `mouse.click(target: TargetRef, button: Literal["left", "right"] = "left")` | ActionReceipt | 一次有界点击，不自动重试，点击后仍需业务验证 |
| `mouse.scroll(region: RegionRef, direction: Literal["up", "down"], steps: int)` | ActionReceipt | 在有效列表区域内滚动 1–3 标准滚轮刻度，不对全窗口盲滚 |
| `keyboard.press(key: str, hold_ms: int)` | ActionReceipt | 注册按键白名单，按住并释放，时长受宿主单动作上限约束；不提供无限 key_down |

动作工具的 value 与包装中的 receipt 指向同一回执。所有工具在操作前与等待期间响应停止、失焦、来源变化和租约失效；按键释放由执行层维护，仍按技术方案报告系统故障下的覆盖边界。

### 3.4 对话组合工具

用于避免每个脚本重复实现 OCR、滚动和页面判断。相同的超时、证据、回执和取消规则适用于它们；下列方法同样接收 `timeout_ms`。

| 方法与输入 | T | 行为 |
| --- | --- | --- |
| `dialogue.wait_text(npc_name: str, text: str, after: EvidenceRef \| None = None)` | DialogueEvidence | 先确认 NPC 身份，仅在该对话内容区 NFKC/去空白后匹配文字片段；有 after 时必须来自更晚的有效画面 |
| `dialogue.click_option(page: DialogueEvidence, text: str)` | ActionReceipt | 在已验证页面定位唯一选项、确认页面仍有效后点击一次；不隐含成功 |
| `dialogue.select_material(page: DialogueEvidence, name: str, count: int, max_scrolls: int, direction: Literal["down", "up"] = "down", scroll_steps: int = 3, confirmation_text: str = "你确定要交换吗")` | SelectionEvidence | 名称与数量匹配唯一列表项后点击一次，验证新画面出现确认页；列表数量允许“个”，不读取背包 |
| `dialogue.wait_closed(dialogue: DialogueRef, after: EvidenceRef)` | ClosedEvidence | 在晚于 after 的有效画面确认原对话框确实关闭；捕获失败/OCR 未读到不算关闭 |

select_material 的 count ≥1、max_scrolls 为 0–20、scroll_steps 为 1–3，0 次只检查当前可见列表。每次滚动后重新观察；无进展、到底、超限、页面变化或歧义就返回明确非成功状态。整个搜索共用一次截止时间，滚动和点击均计入动作预算。确认选项只能点击一次，不能把超时当作重发依据。

after 由插件传入之前的页面证据，工具核验其所属上下文；引擎还须用动作完成时序确认动作后的结果，不能用早于点击的识别结果证明操作成功。

## 4. `run()` 返回值、异常和生命周期

run 是一次运行协程，执行步骤并返回 WorkflowResult，不返回任意可执行代码。返回值中所有字段必填，无内容时使用 None/空映射/空元组。SDK 校验摘要为有限可序列化数据且 UTF-8 JSON 不超过 16 KiB，证据引用至多 32 条；succeeded 必须附证据，但 SDK 不判断业务事实，不等于独立成功验证通过。冻结模型仅限制字段赋值，嵌套 data/参数容器仍须由后续运行器复制、冻结或重新校验，不把它当作安全沙箱。

| 输出字段 | 约束 |
| --- | --- |
| `status` | succeeded：声明完成，须由任务注册的独立验证器核验证据；failed：已确认无法完成；paused：需用户处理/结果不明；cancelled 由引擎在用户停止时生成，插件不把取消改成成功 |
| `code/message` | 稳定原因码与简短说明，例如 exchange_completed / target_ambiguous / outcome_unknown；不把日志堆栈或凭据当用户消息 |
| `last_step` | 最近业务步骤 ID，无步骤时 None；仅用于展示/诊断，不是恢复执行地址 |
| `data` | 业务摘要，如材料名称、数量、完成轮次；只含有界、可序列化数据，不含图像、客户端、凭据或窗口句柄 |
| `evidence` | 支持结果的证据引用，成功声明必须有与本次运行匹配的必要证据 |

返回 `succeeded` 不直接提交运行成功；验证器用原始前后证据检查当前任务的完成标准，拒绝同一帧拼接、过期引用和只凭“点击已发送”的结果。Mock 只能得到标记为 Mock 的验证结论，不能写成真实兑换成功。run_id、插件 ID/版本、有效参数、起止时间、模式和动作/验证记录由引擎补充，不由插件伪造。

预期工具失败应检查 ToolResult 并返回 paused/failed；不能只判断 value 是否为空或默默跳过。未处理异常由引擎记录并暂停，取消未完成请求/动作，不自动重启插件。工具/运行超时由引擎暂停并保留 outcome_unknown（如适用），不能重放确认兑换。

`asyncio.CancelledError` 必须传播；插件可在 finally 中清理自身资源，但输入释放由执行层兜底。引擎收到停止/暂停请求立即撤销执行许可并取消协程，不等待脚本清理后才停止输入。不能承诺协作式取消能中断任意阻塞 Python；可信插件必须使用异步工具，禁止阻塞事件循环或自行创建无限后台任务。

暂停取消当前协程，本接口不承诺恢复 Python 调用栈或从 last_step 自动继续。首个插件版本仅支持用户明确重新启动并从新观测确认起始条件；兑换结果不明不能自动重开一轮。持久化断点恢复若将来需要，应另行定义状态模型和恢复接口。

## 5. 兑换流程使用示意

本段是未来工具调用示意；工具只有 Protocol 声明，不是可注册的完整兑换实现。完整步骤/截图依据见 [兑换说明](../workflows/orbis_charlie_exchange/README.md)。下面仅展示“同意交易后等待材料列表”的入参与结果处理，其他步骤使用同样规则：

```python
async def agree_trade(ctx, params, trade_page):
    await ctx.set_step("agree_trade", timeout_ms=params.step_timeout_ms)
    clicked = await ctx.tools.dialogue.click_option(
        page=trade_page, text="是", timeout_ms=params.step_timeout_ms,
    )
    if clicked.status != "ok":
        return clicked  # 上层 run 检查回执并返回 paused，不重发
    listed = await ctx.tools.dialogue.wait_text(
        npc_name=params.npc_name,
        text="你先决定拿什么东西换吧",
        after=trade_page.evidence,
        timeout_ms=params.step_timeout_ms,
    )
    return listed
```

示意中的 `trade_page.evidence` 是 DialogueEvidence 的单个 EvidenceRef。点击与后续等待还受同一业务步骤剩余时限限制；参数给的是上限，不重置总时限。set_step 使用已校验的 timeout_ms 分配步骤截止时间；重复设置同一步骤不能延长期限，切换步骤仍受运行总预算和动作预算限制。工具只能收紧该时限，不能放大。

运行前用户备好材料/空位，NPC 可交互；本流程不增加库存/背包或确认页材料复核。看到明确成功提示、点击结束对话并验证关闭后才返回单轮成功，不自动循环。页面/选项识别仍是必要证据。

## 6. 注册、扩展与验收

已建立 [base.py](../app/workflows/base.py)（模型与 Protocol）、[registry.py](../app/workflows/registry.py)（显式注册/工厂及预检）、[context.py](../app/workflows/context.py)（协作式上下文）、tools/base.py（工具签名）、[中士占位插件](../app/workflows/builtin/charlie_exchange.py) 和 [注册入口](../app/workflows/__init__.py)。runtime.py 与输入/运行工具待建立；只读判断和流程列表/手动分析 API 已接入，见第7节。

create_builtin_registry() 返回独立注册表，目前仅显式注册中士插件且 implementation_ready=False；即使传入全部能力/动作仍不可用。register 在注册时创建一次探测实例，校验 API 版本、参数模型和 async run；工厂应无副作用。prepare 重新创建独立运行实例并校验元数据/参数模型与注册时一致，不调用 run，不自动启动任务。可信工厂不得返回单例或共享可变运行状态；注册器不能证明任意 Python 工厂不存在共享状态。

运行记录固定插件 ID、api_version、内容版本、有效参数、模式和代码/发布标识。接口不兼容时拒绝启动，参数变化需明确兼容范围；不隐式恢复到不同版本代码。不再要求实现旧流程 JSON 读写或迁移器：仓库内删除的 JSON 只是未执行的设计文件，没有实际运行记录需要恢复。

字段或工具不足时可按需求扩展 Python 契约；同步本规范、技术方案、待办和示例。破坏性接口变化更新 api_version 与调用方；保持兼容的新增工具也须有明确类型、错误、取消、证据及预算语义。不恢复已删除的视觉配置兼容逻辑。

后续实现验收至少包含：重复/未知插件、接口版本/参数/能力拒绝、实例隔离、工具返回未知/歧义、目标过期、失焦、停止、超时、预算耗尽、结果不明不重发、独立成功验证，以及 Mock 与真实运行记录区分。静态示例、工具桩、录制回放、真实 OCR、Windows 输入和交互闭环分别记录。

已交付 SDK/只读判断接入及单元测试源码，仅通过虚拟机静态检查；[tests/test_workflows.py](../tests/test_workflows.py) 由宿主机执行。插件运行器/输入工具实现、兑换交互及宿主机验证保持未完成。原 JSON 文档被本文件替代，不设通用节点图、流程解释器或外部脚本加载的首版任务。


### 6.1 当前内部调用示例

以下为执行预检的 Python 方法；执行仍不可用。只读判断另有 prepare_inspection 和 GET /api/workflows，见第7节：

```python
from app.workflows import create_builtin_registry
from app.workflows.registry import WorkflowEnvironment

registry = create_builtin_registry()
environment = WorkflowEnvironment(mode="mock")
descriptions = registry.describe(environment)
report = registry.validate(
    "orbis_charlie_exchange", "1.3.0", {"material_count": 100},
    environment, task_id="npc_material_exchange",
)
# report.valid 为 False：占位实现/能力缺失，不会执行输入。
```

| 方法 | 返回与边界 |
| --- | --- |
| register(factory, implementation_ready=..., unavailable_reason=...) | 返回 None；重复 ID、接口版本、参数模型或 run 签名错误抛 ValueError；尚未实现时必须写明不可用原因 |
| describe(environment) | tuple[WorkflowDescription, ...]，含 metadata/params_schema/mode/available/unavailable_reasons；按明确的 Mock 或真实环境分别评估 |
| validate(plugin_id, plugin_version, params, environment, task_id=...) | ValidationReport(valid, reasons)；同时检查注册项、版本、任务归属、严格参数、实现状态和能力/动作 |
| prepare(同 validate 入参) | PreparedWorkflow(plugin, params)，params 为冻结且已校验的模型；预检不通过抛 WorkflowUnavailable，工厂契约变化抛 ValueError，不执行 run |

WorkflowEnvironment 包含 mode、capabilities、allowed_actions，后两者是 frozenset，由宿主按当前执行模式提供。这里的 available/valid 仅是注册预检：尚未校验实际会话、目标窗口/租约、控制器或任务独立验证器，也未与 EngineService 连接，不能当作真实启动许可。

中士占位 run 仅 await checkpoint 后返回 paused/workflow_not_implemented、空证据和空业务结果；不调用工具、不伪造 Mock 成功。SDK 不改变 EngineService 的 planning/input 能力标记。


### 6.2 共用对话感知

[read_dialogue/extract_dialogue](../app/vision/dialogue.py) 只读取样本风格面板、可见 NPC、正文/按钮/材料，不含任务阶段或建议。中士页面规则已移至插件，前端不解释中士字段。感知结果依赖样式与相对布局，真实模型验收待完成。图片3实测no_dialogue_panel后，共用定位器新增优先检测完整矩形边框（嵌套笔画去重/正文亮色校验），无边框候选才走原亮色连通区域；接口和中士判断不变。真实截图几何回归与OCR复测待宿主机执行，静态检查不能记为修复通过。

## 7. 可选的只读单步判断（已编写，宿主机待验证）

执行接口 api_version=1 保留；新增可选 WorkflowEvaluator 协议，不强迫已有执行插件实现，未声明识别可用的插件不会被测试页启用。中士内容版本升为1.3.0。此扩展无需 JSON 流程迁移；不支持的插件版本拒绝选择，不静默替换。

```python
from app.workflows.inspection import InspectionContext, WorkflowInspection

def evaluate(self, ctx: InspectionContext, params: Params) -> WorkflowInspection:
    # 调用共用感知和同一个业务判断函数；不执行输入。
    ...
```

该入口为同步函数，在后台识别工作内运行；ctx 是冻结 dataclass，只有 snapshot、perception、deadline_monotonic、checkpoint()。snapshot 绑定画面和基础信息，未知字段保留未知；perception 提供 dialogue()/npc_name(name) 的只读接口，按本次快照缓存。没有 WorkflowContext.tools、键鼠、输入绑定或执行租约；不能把运行上下文传来再用开关禁止点击。可信 Python 仍非沙箱，不能声称可以防止任意脚本越权或阻塞。

当前 ctx 不接收人工填写的前序状态，也不自动保留跨截图身份。缺少历史证据就返回缺失条件；未来运行协调器若传历史，需另定义来源/时效/会话关联，不把一张成功页推断为已完成整轮。

### 7.1 注册、发现和请求

register 新增 inspection_ready=False、inspection_capabilities=()；声明就绪时必须存在同步 evaluate。执行 implementation_ready/required_capabilities/allowed_actions 保留独立；只读预检不要求输入能力。describe 新增 inspection_available 与 inspection_unavailable_reasons，available 仍表示执行兼容预检。

prepare_inspection(plugin_id, plugin_version, params, environment) 校验插件、版本、识别能力与严格参数，返回 PreparedInspection(plugin: WorkflowEvaluator, params) 新实例，不调用 run。参数最多64个键/16 KiB 有限 JSON 对象。当前宿主声明 dialogue_reading/npc_name_reading（表示实现存在，模型运行仍可能失败）；GET /api/workflows 输出注册描述/参数 schema 与两种可用性，中士可识别但不可执行。

图片/视频分析入口接收以下对象，workflow 可省略或为 null；VisionProfile 仍支持作为基础模式请求体，供现有调用者使用，不恢复任何旧视觉配置字段：

```json
{
  "profile": {"reference_size": [1382, 807]},
  "workflow": {
    "plugin_id": "orbis_charlie_exchange",
    "plugin_version": "1.3.0",
    "params": {"material_name": "僵尸丢失的臼齿", "material_count": 100}
  }
}
```

基础识别始终运行；未选流程不做对话 OCR。选择后在同一工作内调用 evaluate；工具重复读取只缓存本帧，不跨请求共享。截止时间60秒只在检查点执行，无法强行中断模型。错误选择/参数在感知前以422拒绝，工厂契约变化409；插件内部异常、超时、坏返回或错帧标注产生无意图的unknown结果，基础识别保留。

### 7.2 标准返回值

类型与验证见 [inspection.py](../app/workflows/inspection.py)。ObservationResult.workflow_inspection 可空；dialogue 是按需读取后的诊断数据，可空，不再含流程 page/suggested_action/target_bbox。

| 字段 | 类型与含义 |
| --- | --- |
| plugin_id/plugin_version/observation_id | 引擎校验与所选插件/本次快照一致 |
| status | found/not_found/unknown/ambiguous，非 found 禁止意图 |
| stage_id/stage_label | 稳定阶段ID与显示名称；未知时 unknown/未知阶段 |
| fields | 最多64项 key/label/value；value 为字符串（≤2048字）、有限数值、布尔或null。当前不支持嵌套业务字段，复杂内容由插件摘要 |
| annotations | 最多64项 id/label/kind/bbox，kind为region/candidate/target，原图xywh；ID唯一，框需为正且在本帧内 |
| intent | 可空；kind为click/scroll/wait/observe，label/reason、可空target_id；execution_authorized恒false，引用必须存在，不是ActionPlan |
| missing_conditions | 最多32条缺失条件，每条1–256字；例如 NPC 身份不明或尚未验证关闭 |
| diagnostics | 最多64条诊断，每条1–256字；包含感知原因/原文/分数，不输出内部异常或凭据 |
| processing_ms | 引擎计算本次判断及感知耗时，不代表端到端延迟或准确率 |

通用前端自动渲染字段/阶段/诊断及标注；参数 schema 为常规标量/枚举时生成表单，其他形状使用 JSON 对象编辑，默认值来自参数模型。新增流程在该契约内只需新增插件及显式注册，无需改测试页；新感知工具或展示类型仍须扩展相应契约与实现。

### 7.3 中士规则与执行边界

[decide_exchange](../app/workflows/builtin/charlie_decision.py) 是唯一阶段/意图函数，evaluate 调用它。未来自动运行应复用相同函数并通过执行层验证意图，不能另写一套测试专用判断。本次 run 仍是不可用占位，没有宣称已实现自动运行复用或真实闭环。

参数决定目标 NPC/材料/数量与搜索预算；通用感知无中士关键词。没有本帧 NPC 标签时明确未知，缺少可信身份上下文；明确不匹配、页面冲突/低分/重复目标不产生操作意图。成功页仅提示结束对话/等待，标记尚未验证关闭。意图即使存在仍不授权执行，未来运行必须核验身份/窗口/租约/时效并将意图转为受控计划，不直接执行标签字符串。

验收区分通用感知、单步判断、注册/API、前端类型、真实 OCR 和交互。当前新增第二插件字段、错误隔离、缓存、身份/歧义/低分、参数/版本拒绝及同帧测试源码；宿主机运行、真实样本和页面验收待完成。


### 7.4 初始场景的 NPC 标签查询

新增 ReadOnlyPerception.npc_name(name: str) -> SceneNameReading，使用同帧配置scene范围/UI排除区、完整名字匹配和独立读取的候选文字。查询目标是参数，结果仅在唯一高分匹配时确认，不能把参数本身写成已识别NPC；规范化查询缓存最多8个名字，不跨快照复用。未配置范围时unknown/scene_not_configured。

中士1.3.0只在no_dialogue_panel分支调用该能力；对话未知/歧义不回退。名字查询成功后按第7.5节继续验证外观，不直接以名字框生成点击意图；名字失败阶段search_npc，无意图。execution_authorized仍恒false，真实OCR和图1验收待完成。插件注册新增npc_name_reading要求，执行能力保持禁用。


### 7.5 NPC 外观人物框

只读接口新增npc_body(name: str) -> BodyReading，本版仅支持注册中士外观，缓存当前快照结果，复用npc_name查询。宿主/注册识别能力增加npc_body_matching；玩家模板配置不控制NPC模板。模板来自samples/tasks/1.png帽子到鞋(411,408,50,69)，名字上方200×150搜索、阈值0.85，输出实际匹配框/候选/搜索区/版本而非名字固定偏移。

中士1.3.0仅在名字和外观都确认时提议点击npc_body标注，并显示候选矩形中心。名字确认而外观未确认时stage_id=locate_npc_body，无点击意图；此前仅名字就提议交互的行为取消。名字框仍作为诊断，不能退回它作为点击目标。模板框可能包含背景，非精确hitbox；执行、距离/窗口/关闭校验及真实可点击性尚未实现/验证。
