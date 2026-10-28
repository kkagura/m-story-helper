"""Workflow SDK and an explicit registry, independent of the service lifecycle."""

from app.workflows.registry import WorkflowRegistry


def create_builtin_registry() -> WorkflowRegistry:
    from app.workflows.builtin.charlie_exchange import CharlieExchangeWorkflow

    registry = WorkflowRegistry()
    registry.register(
        CharlieExchangeWorkflow,
        implementation_ready=False,
        inspection_ready=True,
        inspection_capabilities=("dialogue_reading", "npc_name_reading", "npc_body_matching"),
        unavailable_reason="中士兑换仅有插件骨架，对话工具和执行流程尚未实现。",
    )
    return registry
