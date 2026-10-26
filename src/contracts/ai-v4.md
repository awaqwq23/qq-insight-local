# 模型容量与读取建议（0.6.0-rel）

- 主模型配置增加 `limits`：`context_tokens`（2048–10000000）、`tpm_tokens`（0–10000000；0表示未知）、`output_tokens`（512–16384）。设置按配置保存；模型、地址、接口类型或密钥改变后清除旧测试。
- `model:limits` 仅返回对应接口和精确模型名的官方快照或保守默认值；`model:discover` 能力条目可携带接口提供的容量。未知模型默认32768，明确标注未验证，不按别名猜测。
- `model:test-capacity` 只接受保存的 `profileId`、`maxMessages`（1–10000）与 `maxTokens`（2000–2000000），最多8次调用，使用合成消息。所有调用须在发送前经 `ai.call.reserve`，成功、失败和取消均经 `ai.call.settle`；账本类型 `test_capacity`。未知用量仍保守预占。
- 测试查验返回首尾消息ID及条数；记录成功读取下限、失败条数区间、停止原因、接口报告的上下文数值（若有）及1万条合成消息估算用量。该校验不代表完整分析质量验收。429 限流不作为上下文失败区间，不从一次429推测TPM，只接受接口明确报告的数值。
- 推荐条数按完整输入/输出预留、TPM安全额度、每条256 Token估算及成功测试下限计算。QQ真实消息长度与合成样本不同，推荐不是精确容量保证；超过建议时允许用户在弹窗中返回或继续。
- 模型描述符增加 `limits`；核心发请求前按UTF-8字节保守上界计入Prompt、群配置、历史和记忆，并预留输出，必要时裁剪补充材料、继续拆分消息。TPM已配置时桌面按照每分钟80%额度等待，可取消；其他客户端的并行用量仍可能引起服务限流。
- 旧任务继续时校验原模型、接口及媒体路由；允许更新容量/输出与当前定价，同时保留既有成功分块和账本。
- 非收藏分析结果忽略无意义的图片收藏索引；收藏推荐仍严格校验第一证据消息和图片索引。任何功能都继续严格校验证据ID和账号/会话范围。

官方容量快照（2026-10-12）：[百炼 DeepSeek V4 Pro](https://help.aliyun.com/zh/model-studio/deepseek-v4-pro)、[DeepSeek 模型说明](https://api-docs.deepseek.com/quick_start/pricing/)。官方 DeepSeek 主域使用[关闭思考参数](https://api-docs.deepseek.com/guides/thinking_mode/)；百炼沿用其现有 `enable_thinking=false`。其他兼容接口不推送这些专属参数。
