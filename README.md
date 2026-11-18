# GPTDSL

面向 Linux 内核源码审计的补丁驱动 CodeQL 查询合成研究项目。

项目借鉴 KNighter 的补丁理解思路与 MoCQ 的查询合成、反馈验证思路。
目标输入为内核修复补丁及对应源码上下文，目标输出为 CodeQL QL 查询及评估结果。

当前已实现补丁与上下文准备模块；缺陷模式提炼、QL 合成、验证、评估和 workflow 尚未实现。

## 环境

- Python 3.12+
- 使用 uv 管理项目、虚拟环境和依赖锁文件。
- 使用 Tree-sitter C 提取语法片段，使用 pytest 验证模块行为。
- 需要 Git 可执行程序；推荐 Git 2.48+，支持禁止部分克隆仓库的隐式对象下载。
- CodeQL 和内核构建环境属于后续外部依赖，本次未安装。

在项目目录中同步环境：

```powershell
uv sync
```

## 准备补丁上下文

输入一个已有完整父提交的本地仓库和修复提交。以下命令中的仓库与提交是占位值：

```powershell
uv run gptdsl context --repo D:/sources/linux --commit <commit-sha> --out artifacts/context
```

输出目录必须位于输入仓库之外。生成 `context.json` 与 `context.md`，已有同名文件默认拒绝覆盖，
显式传入 `--overwrite` 可替换。`--max-context-chars 16000` 可调整 Markdown 字符预算（最低 512）。

也可使用 Python 接口：

```python
from gptdsl.patch_context import ContextLimits, prepare_patch_context

context = prepare_patch_context(
    "D:/sources/linux",
    "<commit-sha>",
    limits=ContextLimits(markdown_chars=16000),
)
materials = context.to_dict()
```

接口只读 Git 对象，不切换版本、不更新索引、不读取当前工作区补齐历史材料，也不下载缺失提交。
暂不支持根提交、合并提交、独立补丁文件或批量任务。

`context.json` 保存已收集的原始源码、前后函数、来源位置和诊断；`context.md` 是有预算的展示版本。
超限文件、无法解析或无法唯一解析的符号会显式记录，不代表所有上下文均已收齐。
`complete` 只有在没有任何诊断（包括展示截断）时为真；CLI 对带诊断的部分结果仍返回 0，
输入、Git 或输出错误返回 2。调用方应检查诊断，不能将结果是否完整当作缺陷判断。

## 目录

```text
GPTDSL/
├── pyproject.toml
├── uv.lock
├── .python-version
├── README.md
├── docs/
│   └── architecture.md
├── configs/
│   └── README.md
├── src/
│   └── gptdsl/
│       ├── cli.py
│       ├── patch_context/
│       ├── pattern_analysis/
│       ├── query_synthesis/
│       ├── validation/
│       ├── evaluation/
│       └── workflow/
└── tests/
    └── README.md
```

五个业务模块分别负责补丁上下文、缺陷模式、查询合成、查询验证、泛化评估。
`workflow/` 负责流程调度，不作为第六个业务模块。
除 `patch_context` 外，其他模块当前仍只包含职责说明文件。

## 测试

```powershell
uv run pytest -q
```

测试创建临时 Git 仓库及小型 C 源码历史，不需要下载内核、调用模型或安装 CodeQL。

## 架构约定

主流程由 workflow 控制；未来根据需要在局部步骤引入有边界的 agent。
验证与评分由独立程序执行，模型输出属于待验证的候选。
最终独立测试集不向生成阶段提供修改反馈。

详见 [架构说明](docs/architecture.md)。
