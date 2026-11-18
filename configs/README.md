# 配置目录

模型配置通过环境变量读取。目前补丁筛选的默认配置为：

- 模型：`deepseek-flash`。
- API 地址：`https://api.deepseek.com/v1`。
- 密钥：`DEEPSEEK_API_KEY`，启用 `--ai` 时必须设置。
- 可选覆盖：`GPTDSL_REVIEW_MODEL`、`GPTDSL_REVIEW_BASE_URL`；CLI 的 `--model`、`--base-url` 优先。

离线运行无需模型配置。后续运行预算、工具路径和评估配置仍预留。
真实密钥与机器专属路径不应提交到版本控制。
