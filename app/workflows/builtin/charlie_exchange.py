"""Inspectable exchange plugin; automatic execution remains unavailable."""

from pydantic import Field

from app.workflows.base import (
    WorkflowContext,
    WorkflowMetadata,
    WorkflowParams,
    WorkflowResult,
)
from app.workflows.builtin.charlie_decision import decide_exchange
from app.workflows.inspection import InspectionContext, WorkflowInspection


class CharlieExchangeParams(WorkflowParams):
    npc_name: str = Field(title="目标 NPC", default="查里中士", min_length=1, max_length=100)
    material_name: str = Field(title="材料名称", default="僵尸丢失的臼齿", min_length=1, max_length=100)
    material_count: int = Field(title="材料数量", default=100, ge=1, le=9999)
    step_timeout_ms: int = Field(
        title="执行步骤超时（毫秒）", description="供后续自动执行使用；预览采用宿主时限",
        default=10000, ge=100, le=60000,
    )
    max_scrolls: int = Field(title="最多滚动次数", default=12, ge=0, le=20)


class CharlieExchangeWorkflow:
    metadata = WorkflowMetadata(
        id="orbis_charlie_exchange",
        api_version=1,
        version="1.3.0",
        task_id="npc_material_exchange",
        name="天空之城中士臼齿兑换（单轮）",
        category="quest",
        description="提前准备材料和背包空间，成功兑换后结束对话；支持单帧判断，尚未启用自动执行。",
        tags=("npc", "exchange", "single_round"),
        required_capabilities=("npc_detection", "dialogue_ocr", "dialogue_scroll", "bounded_input"),
        allowed_actions=("mouse_click", "mouse_scroll"),
    )
    params_model = CharlieExchangeParams

    def evaluate(
        self, ctx: InspectionContext, params: CharlieExchangeParams,
    ) -> WorkflowInspection:
        return decide_exchange(ctx, params, self.metadata)

    async def run(
        self, ctx: WorkflowContext, params: CharlieExchangeParams,
    ) -> WorkflowResult:
        await ctx.checkpoint()
        return WorkflowResult(
            status="paused",
            code="workflow_not_implemented",
            message="中士兑换流程尚未实现 NPC/对话工具，未执行任何输入。",
            last_step=None,
            data={},
            evidence=(),
        )
