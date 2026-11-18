# 补丁筛选

从有界 Git 历史或显式提交清单中整理修复研究语料。判断的是材料质量及初期语义范围，
不将模型结论当作已验证的漏洞标签。

## Interface

```python
from gptdsl.patch_selection import SelectionLimits, select_patches

result = select_patches(
    "D:/sources/linux",
    "HEAD",
    limits=SelectionLimits(max_commits=100),
)
report = result.to_dict()
candidates = result.candidate_commits
accepted = result.selected_commits  # 离线模式为空
```

输入仓库必须为本地非 bare Git 仓库。`revision` 为单个历史起点或 Git 提交范围，
按拓扑顺序从新到旧最多遍历 `max_commits` 项，限制发生在筛选前。
省略 `revision` 时默认扫描 HEAD 历史。

指定 `commit_file` 可只筛选清单中的提交：

```python
result = select_patches("D:/sources/linux", commit_file="commits.txt")
```

`revision` 与 `commit_file` 互斥。文件模式按行处理全部条目，`SelectionLimits.max_commits`
仅作用于历史模式，不限制提交清单。CLI 在文件模式下拒绝 `--max-commits`。
文件格式与上下文批量输入相同：UTF-8/BOM、每行一个 hash 或引用、支持空行和 `#` 注释。
引用解析成完整 SHA 后去重，重复项标记 `duplicate` 并记录首次行号，包含首次处理失败的项。
无效行、引用及单项复核错误不会中断后续处理；根/合并提交仍按正常筛选规则排除。
报告的 `input_mode` 区分 `history` 和 `commit_file`；文件模式额外保存清单路径、每项行号与原始输入、重复数。

函数不导出文件、不切换 HEAD、不修改索引和工作区、不下载缺失对象。
无效仓库或历史范围抛出 `PatchContextError`，无效预算抛出 `ValueError`；
清单为空、无法读取或编码错误直接报错；逐项的 Git、上下文和复核错误记为 `error` 并继续处理。

注入 `reviewer` 可启用语义复核，其 Interface 为：

```python
from gptdsl.patch_selection.provider import ChatCompletionsReviewer, ReviewConfig

reviewer = ChatCompletionsReviewer(ReviewConfig.from_env())
# 显式执行时会将候选上下文发送到配置的模型服务。
result = select_patches("D:/sources/linux", "HEAD", reviewer=reviewer)
```

也可提供满足 `Reviewer` 协议的实现：`review(context) -> SemanticReview`。
结果使用 `suitable`、`needs_review`、`out_of_scope` 三种决策，以及具体理由和 `Evidence`。
初期支持 `error_handling`、`resource_cleanup` 两类入选；`other`、`unknown` 可用于解释排除或待复核。
`suitable` 必须附源码证据。每条证据的完整版本、文件、1-based 行范围和引用内容都需要匹配
历史片段及模型实际看到的文本。校验约束引用真实性，语义结论仍需后续人工或独立评估。

## Implementation

```text
CLI → select_patches → Git 初筛 → patch_context → Reviewer（可选）→ 证据校验
CLI → 公共导出工具 → commits.txt / candidates.txt / selection.json
```

- `history.py`：有界历史、单父提交和可用父对象检查、C/H 修改和改动规模检查。
- `select.py`：组织固定阶段、上下文预算、逐项错误隔离。
- `models.py`：预算、复核器协议、证据和结果。
- `review.py`：结构和历史源码证据校验。
- `provider.py`：可选 DeepSeek Chat Completions adapter，禁止跟随重定向。
- `command.py`：CLI 参数和导出，与已有上下文批量输入衔接。

默认预算：历史模式扫描 100 个提交，每个补丁 8 个修改文件、300 行增删、6 个改动函数；
上下文预算继承 `ContextLimits`，默认展示 32000 字符。
根/合并提交、非 C/H 修改或规模超限记为 `out_of_scope`。
关键源码缺失、二进制源码、解析错误、函数配对歧义和展示截断保留待复核，不调用模型。
其他上下文诊断随材料提供给复核器，不能据此推断全局上下文已完整。
提交关键词、`Fixes:` 和 stable 标签只记录为弱信号；没有这些信号的提交仍可进入复核。

`candidates.txt` 对应通过 Git 元数据和规模初筛的集合，
包括后续函数超限、语义排除、待复核或复核失败的项。
`commits.txt` 只包含最终 `suitable` 项，离线时为空。
`selection.json` 保存所有扫描项、来源与上下文展示、诊断、判断理由和证据。
外部 adapter 另外记录模型和地址、请求/响应 SHA256、原始复核文本，不保存 API 密钥。

模型默认 `deepseek-flash`，服务默认 `https://api.deepseek.com/v1`。
启用 AI 前需要设置 `DEEPSEEK_API_KEY`，缺失或为空时立即报错；离线模式不需要配置密钥。
密钥仅从该环境变量读取，不回退到其他服务的凭据。
可选的 `GPTDSL_REVIEW_MODEL`、`GPTDSL_REVIEW_BASE_URL` 可覆盖默认值，
CLI 的 `--model` 和 `--base-url` 优先于环境变量。
服务必须兼容 Chat Completions、`response_format=json_object` 和 `max_tokens`。
单次请求超时默认 60 秒、响应最多 1 MiB，不自动重试；失败不会自动转为入选。

目前不进行不同 SHA 之间的语义去重、补丁系列合并、补丁效果执行验证或 CodeQL 生成。
同一修复在不同分支的回移提交可能重复出现，需要在后续语料评估时处理。
