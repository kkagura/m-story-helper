# 天空之城中士臼齿兑换：单轮流程

本场景按 [Python 流程插件接口](../../docs/workflow-plugin-spec.md) 实现。原 v1.json 已移除，本文保留业务步骤和截图依据；当前尚无插件运行器、对话工具或可运行兑换插件，未通过真实点击验收。

运行前由用户准备足够材料、背包空位，并使 NPC 处于可交互范围；流程不自动移动到 NPC、不检查库存/空位，也不核对确认页上的材料/数量。选择列表项仍按“僵尸丢失的臼齿 100 个”定位，属于选择目标，不是检查背包。

| 业务步骤 | 操作 | 等待的结果 | 图片依据 |
| --- | --- | --- | --- |
| open_npc | 找到并点击中士 NPC | NPC 介绍页出现 | [1.png](../../samples/tasks/1.png) → [2.png](../../samples/tasks/2.png) |
| next_intro | 点击“下项” | 交易说明及“是/不是”页 | [2.png](../../samples/tasks/2.png) → [3.png](../../samples/tasks/3.png) |
| agree_trade | 点击“是” | 材料列表出现 | [3.png](../../samples/tasks/3.png) → [4.png](../../samples/tasks/4.png) |
| choose_material | 选材料，必要时只在列表内向下滚动 | 兑换确认页出现 | [4.png](../../samples/tasks/4.png) → [5.png](../../samples/tasks/5.png) |
| confirm_exchange | 确认页点击一次“是” | 明确出现“已经交换成功了” | [5.png](../../samples/tasks/5.png) → [6.png](../../samples/tasks/6.png) |
| close_dialogue | 成功页点击“结束对话” | 确认对话框关闭，本轮 succeeded | [6.png](../../samples/tasks/6.png)；关闭后的图片尚未提供 |

NPC 名称与按钮/页面关键词由插件参数模型或脚本中的页面常量定义，可按实际 OCR 校准。图 4 的当前可见列表中没有最终材料，滚动中间帧未提供：插件参数 max_scrolls=12、工具 scroll_steps=3 的向下滚动只是有界开发初值，并非实测操作次数或路径。找不到、无进展、歧义或页面异常均暂停。共 6 个业务步骤，所有工具共享步骤/运行时限和动作预算；不自动重试兑换，不自动重开下一轮。

奖励截图显示 20 个万能疗伤药，作为图片理解的记录；插件按用户约定以明确兑换成功提示为依据，不另外比较奖励数量、背包空间或材料库存。只有看到成功后再关闭对话，才把该轮记为完成；不能只凭确认点击或对话框偶然关闭就宣告完成。

图片对应关系仅用于开发审查，不能用固定样本代替实时交互反馈。预期插件元数据：id=orbis_charlie_exchange、api_version=1、version=1.0.0、task_id=npc_material_exchange、category=quest；业务参数模型见接口文档。需要 npc_detection/dialogue_ocr/dialogue_scroll/bounded_input，允许 mouse_click/mouse_scroll，均是待实现能力。返回单轮完成摘要与成功提示/关闭的证据，由任务验证器核验；暂停后不按步骤名自动续跑。

本次仅完成说明文档和接口示例的静态检查；真实 OCR、滚动、按钮定位和交互闭环尚未验证。
