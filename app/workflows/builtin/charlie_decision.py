"""The one exchange decision function: reusable by preview and future run code."""

from app.workflows.inspection import (
    InspectionAnnotation,
    InspectionContext,
    InspectionField,
    StepIntent,
    WorkflowInspection,
)

MIN_CONFIDENCE = 0.8


def normalized(value: str) -> str:
    import unicodedata

    return "".join(unicodedata.normalize("NFKC", value).split())


def decide_initial_scene(ctx: InspectionContext, params, metadata) -> WorkflowInspection:
    name = ctx.perception.npc_name(params.npc_name)
    ctx.checkpoint()
    annotations = tuple(InspectionAnnotation(
        id=f"npc_name_{index}", label=f"NPC 名字：{candidate.text}", kind="candidate",
        bbox=candidate.bbox,
    ) for index, candidate in enumerate(name.candidates))
    confirmed = name.status == "found" and name.name_bbox is not None
    observed = name.candidates[0].text if confirmed and len(name.candidates) == 1 else None
    body = ctx.perception.npc_body(params.npc_name) if confirmed else None
    ctx.checkpoint()
    body_confirmed = body is not None and body.status == "found" and body.bbox is not None
    if body and body.search_bbox:
        annotations += (InspectionAnnotation(
            id="npc_search", label="NPC 外观搜索范围", kind="region", bbox=body.search_bbox,
        ),)
    if body:
        annotations += tuple(InspectionAnnotation(
            id=f"npc_candidate_{i}", label="NPC 外观候选", kind="candidate", bbox=item.bbox,
        ) for i, item in enumerate(body.candidates))
    if body_confirmed:
        annotations += (InspectionAnnotation(
            id="npc_body", label="NPC 人物框（模板匹配）", kind="target", bbox=body.bbox,
        ),)
    center = (body.bbox[0] + body.bbox[2] // 2, body.bbox[1] + body.bbox[3] // 2
              ) if body_confirmed else None
    return WorkflowInspection(
        plugin_id=metadata.id, plugin_version=metadata.version,
        observation_id=ctx.snapshot.result.observation_id,
        status="found" if body_confirmed else body.status if body else name.status,
        stage_id="await_npc_interaction" if body_confirmed else
        "locate_npc_body" if confirmed else "search_npc",
        stage_label="等待与 NPC 交互" if body_confirmed else
        "已找到名字，等待确认人物" if confirmed else "寻找目标 NPC",
        fields=(
            InspectionField(key="npc", label="本帧 NPC", value=observed),
            InspectionField(key="target_npc", label="查找目标", value=params.npc_name),
            InspectionField(key="body_score", label="外观匹配分", value=body.score if body else None),
            InspectionField(key="body_box", label="人物框（x,y,宽,高）",
                            value=", ".join(map(str, body.bbox)) if body_confirmed else None),
            InspectionField(key="click_point", label="候选点击中心（未实测）",
                            value=", ".join(map(str, center)) if center else None),
        ),
        annotations=annotations,
        intent=StepIntent(
            kind="click", label="点击 NPC 人物框中心并打开对话",
            target_id="npc_body", reason="唯一名字关联上方唯一高分NPC外观模板",
        ) if body_confirmed else None,
        missing_conditions=("人物框为外观模板矩形，包含少量背景；可点击性与交互距离待实测",
                            "未独立验证对话关闭；没有输入窗口/租约校验"),
        diagnostics=(f"NPC 名字：{name.reason or 'found'}",
                     f"NPC 外观：{body.reason or body.template_version}" if body else "未执行外观匹配"),
    )



def decide_exchange(ctx: InspectionContext, params, metadata) -> WorkflowInspection:
    ctx.checkpoint()
    reading = ctx.perception.dialogue()
    ctx.checkpoint()
    if reading.status == "not_found" and reading.reason == "no_dialogue_panel":
        return decide_initial_scene(ctx, params, metadata)
    annotations = []
    if reading.panel_bbox:
        annotations.append(InspectionAnnotation(
            id="dialogue_panel", label="对话面板", kind="region", bbox=reading.panel_bbox,
        ))
    for index, box in enumerate(reading.candidates):
        annotations.append(InspectionAnnotation(
            id=f"panel_{index}", label="候选面板", kind="candidate", bbox=box,
        ))
    for index, option in enumerate(reading.options[:60]):
        annotations.append(InspectionAnnotation(
            id=f"option_{index}", label=option.text, kind="candidate", bbox=option.bbox,
        ))
    fields = (
        InspectionField(key="npc", label="本帧 NPC", value=reading.npc_name),
        InspectionField(key="material", label="目标材料", value=params.material_name),
        InspectionField(key="count", label="目标数量", value=params.material_count),
        InspectionField(key="dialogue_text", label="对话内容", value=reading.text[:2048] or None),
    )
    diagnostics = tuple(
        [f"感知：{reading.reason}"] if reading.reason else []
    ) + tuple(f"OCR {row.confidence:.3f}：{row.text[:180]}" for row in reading.texts[:60])
    common = dict(
        plugin_id=metadata.id, plugin_version=metadata.version,
        observation_id=ctx.snapshot.result.observation_id,
        annotations=tuple(annotations), fields=fields, diagnostics=diagnostics,
    )
    if reading.status != "found":
        return WorkflowInspection(status=reading.status, **common)
    if len(reading.options) > 60:
        return WorkflowInspection(status="unknown", missing_conditions=("选项数量超限",), **common)
    certain = normalized("".join(
        row.text if row.confidence >= MIN_CONFIDENCE else "\0" for row in reading.body_texts
    ))
    markers = {
        "intro": ("不愿意跟我交易呢",),
        "trade": ("你只要给我我需要的东西", "交易其实很简单"),
        "materials": ("你先决定拿什么东西换吧",),
        "confirmation": ("你确定要交换吗",),
        "success": ("已经交换成功了",),
    }
    pages = [key for key, phrases in markers.items() if any(p in certain for p in phrases)]
    if len(pages) != 1:
        return WorkflowInspection(
            status="ambiguous" if len(pages) > 1 else "unknown",
            missing_conditions=("页面内容冲突" if pages else "未确认流程页面",), **common,
        )
    page = pages[0]
    labels = {"intro": "NPC 介绍", "trade": "交易说明", "materials": "材料列表",
              "confirmation": "兑换确认", "success": "兑换成功提示"}
    common.update(stage_id=page, stage_label=labels[page])
    if reading.npc_name and normalized(reading.npc_name) != normalized(params.npc_name):
        return WorkflowInspection(
            status="unknown", missing_conditions=("本帧 NPC 与流程参数不匹配",), **common,
        )
    missing = [] if reading.npc_name else ["本帧未确认 NPC 身份，且没有可信前序证据"]
    if page == "success":
        missing.append("尚未验证结束对话和对话框关闭，本轮未判定完成")
    button = {"intro": "下项", "trade": "是", "confirmation": "是", "success": "结束对话"}.get(page)
    wanted = normalized(f"{params.material_name}{params.material_count}个")
    matches = [(i, option) for i, option in enumerate(reading.options) if (
        normalized(option.text).strip("<>›▶◀→←") == button if button else
        option.kind == "material" and normalized(option.text).lstrip(">›▶·•◆◇-") == wanted
    )]
    if len(matches) > 1 or (matches and matches[0][1].confidence < MIN_CONFIDENCE):
        return WorkflowInspection(
            status="ambiguous" if len(matches) > 1 else "unknown",
            missing_conditions=tuple(missing + ["目标重复" if len(matches) > 1 else "目标置信度不足"]),
            **common,
        )
    if matches:
        target = f"option_{matches[0][0]}"
        intent = StepIntent(
            kind="click", label=f"选择“{matches[0][1].text}”", target_id=target,
            reason=f"当前正文匹配“{labels[page]}”，且目标文字唯一",
        )
    elif page == "materials" and params.max_scrolls > 0:
        intent = StepIntent(
            kind="scroll", label=f"向下查找目标材料（最多 {params.max_scrolls} 次）",
            target_id="dialogue_panel", reason="目标材料当前不可见；尚未执行滚动",
        )
        missing.append("尚未找到目标材料选项")
    else:
        intent = StepIntent(kind="wait", label="等待目标选项", reason="当前没有可靠的目标位置")
        missing.append("目标选项尚未确认")
    return WorkflowInspection(
        status="found", intent=intent, missing_conditions=tuple(missing), **common,
    )
