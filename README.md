# GPTDSL

面向 Linux 内核源码审计的补丁驱动 CodeQL 查询合成研究项目。

项目借鉴 KNighter 的补丁理解思路与 MoCQ 的查询合成、反馈验证思路。
目标输入为内核修复补丁及对应源码上下文，目标输出为 CodeQL QL 查询及评估结果。

当前已实现 Git 历史补丁筛选、补丁与上下文准备模块；缺陷模式提炼、QL 合成、验证、评估和 workflow 尚未实现。

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

## 从 Git 历史筛选补丁

先用代码检查单父提交、C/H 文件修改和改动规模，再复用历史源码上下文。
`Fixes:`、stable 标签和修复关键词仅作为参考信号，不会直接决定入选。
初期语义复核范围为错误返回处理和局部资源清理，关注修复意图清晰、目的单一、
上下文可读且约束可复用的补丁。入选表示适合研究语料，不代表已确认漏洞或查询可检测性。

离线初筛不调用模型，所有通过初筛的提交仍待复核：

```powershell
uv run gptdsl select --repo D:/sources/linux --revision HEAD --max-commits 100 --out artifacts/selection
```

历史模式中，`--revision HEAD` 表示从当前提交沿父提交历史向前扫描，不是只处理 HEAD；
也支持本地引用或提交范围，例如 `v6.15..v6.16`。
`--max-commits 100` 表示最多扫描 100 个提交，包含随后被排除的提交。
这两个参数可省略，默认仍是 HEAD 和 100。

也可以直接输入一个已有提交清单，此时不需要历史范围或扫描数量：

```powershell
uv run gptdsl select --repo D:/sources/linux --commit-file commits.txt --out artifacts/selection
```

文件为 UTF-8（支持 BOM），每行一个 hash 或提交引用，支持空行、整行及行尾 `#` 注释。
只处理列出的提交，按文件顺序执行，不展开其父提交历史；全部有效条目都会处理，不默认截断为 100 个。
同一提交的完整 SHA、短 hash 或其他引用只处理一次，报告记录原始行号和重复项。
无效条目记为错误并继续处理后续条目，首次失败的重复提交不会自动重试。
`--commit-file` 与 `--revision` 互斥，文件模式不能指定 `--max-commits`。
两个模式下，每个补丁默认最多 8 个文件、
300 行增删、6 个改动函数，上下文展示预算为 32000 字符。命令只读本地 Git 对象，不下载提交。

项目默认使用 DeepSeek 的 `deepseek-flash`，通过 Chat Completions 接口调用。
如需 AI 语义复核，设置 `DEEPSEEK_API_KEY` 并显式添加 `--ai`：

```powershell
$env:DEEPSEEK_API_KEY = "your-api-key"
uv run gptdsl select --repo D:/sources/linux --revision HEAD --max-commits 20 --ai --out artifacts/reviewed
```

默认服务地址为 `https://api.deepseek.com/v1`。模型名称和服务地址可用 `--model`、`--base-url`
或环境变量 `GPTDSL_REVIEW_MODEL`、`GPTDSL_REVIEW_BASE_URL` 覆盖，CLI 参数优先。
密钥只从 `DEEPSEEK_API_KEY` 读取，启用 AI 时缺失密钥会在请求前报错；离线模式不需要密钥。
服务需支持 `response_format=json_object`
和 `max_tokens`。启用后会将符合条件的提交信息、补丁及源码展示文本发送到该服务。
接口失败或证据无效会逐项记录并继续处理其余提交；关键上下文缺失或展示被截断时保留待复核。

每次导出三个文件：

| 文件 | 内容 |
| --- | --- |
| `commits.txt` | AI 复核为 `suitable` 且通过源码证据校验的完整 SHA；离线运行时为空 |
| `candidates.txt` | 通过 Git 元数据与改动规模初筛的 SHA，可能包含后续被排除、待复核或失败的项 |
| `selection.json` | 输入计划、已完成项、运行进度、检查和参考信号、状态及理由、上下文与诊断、模型结果及审计哈希 |

结果目录必须位于输入仓库之外。默认拒绝覆盖已有文件；显式 `--overwrite` 可替换结果。
每完成一条提交就更新报告和清单，无需等待整批结束。按 Ctrl+C 中断时保存已完成项并返回 130。
用相同命令、相同输出目录加 `--resume`，即可跳过已记录项继续执行：

```powershell
# 首次运行
uv run gptdsl select --repo D:/sources/linux --commit-file commits.txt --ai --out artifacts/selection
# 中断后续跑
uv run gptdsl select --repo D:/sources/linux --commit-file commits.txt --ai --out artifacts/selection --resume
```

恢复时核对仓库、输入计划、筛选预算、AI 开关和模型配置。
历史起点或文件中的引用解析结果变化（例如 HEAD 移动）、清单有效条目或参数变化时拒绝混用结果。
密钥不保存，可更换密钥后续跑。已经记录的错误、排除和待复核项也会跳过，未完成的当前项会重新处理。
`--overwrite` 表示从头开始，不能与 `--resume` 同用。
旧版本缺少断点信息的报告不能直接续跑，应使用新输出目录或显式从头运行。

`selection.json` 中的 `run.state` 为 `running`、`interrupted` 或 `completed`，
`run.processed` 和 `run.total` 表示已记录项数与总输入项数；运行中清单只包含已处理结果。
报告逐文件原子替换，异常退出时以该报告为准，续跑时重新生成可能落后的两个清单文件。
默认实时输出当前提交、已保存项数/总项数、百分比、单项状态和本次运行耗时，无需额外参数。
进度包含重复和无效项，表示处理进度，不表示入选比例；续跑会先显示已有进度。例如：

```text
Starting: 0/100 (0.0%) completed
[1/100] a1b2c3d4e5f6 | processing
Progress: 1/100 (1.0%) | a1b2c3d4e5f6 -> needs_review | saved | elapsed 3.2s
```

正常筛除和待复核返回 0，输入错误或任意条目发生运行错误返回 2。
入选清单可直接传给上下文批量命令：

```powershell
uv run gptdsl context --repo D:/sources/linux --commit-file artifacts/reviewed/commits.txt --out artifacts/context-batch
```

Python 接口与复核器协议见 [筛选模块说明](src/gptdsl/patch_selection/README.md)。

## 准备补丁上下文

输入一个已有完整父提交的本地仓库和修复提交。以下命令中的仓库与提交是占位值：

```powershell
uv run gptdsl context --repo D:/sources/linux --commit <commit-sha> --out artifacts/context
```

输出目录必须位于输入仓库之外。生成 `context.json` 与 `context.md`，已有同名文件默认拒绝覆盖，
显式传入 `--overwrite` 可替换。`--max-context-chars 16000` 可调整 Markdown 字符预算（最低 512）。

### 一个文件包含多个提交

使用 `--commit-file` 传入 UTF-8 文本文件（支持 BOM），每行一个 hash 或提交引用。
空行和 `#` 后的注释会被忽略；不接受 CSV 或每行多个 hash。

```text
# commits.txt：将下面占位值替换为实际提交 hash
COMMIT_SHA_1
COMMIT_SHA_2
```

```powershell
uv run gptdsl context --repo D:/sources/linux --commit-file commits.txt --out artifacts/batch
```

`--commit` 与 `--commit-file` 二选一。批量模式顺序处理，每个提交输出到完整 SHA 命名的子目录：

```text
artifacts/batch/
├── summary.json
├── <完整 SHA 1>/
│   ├── context.json
│   └── context.md
└── <完整 SHA 2>/
    ├── context.json
    └── context.md
```

长短 hash 或不同引用解析到同一提交时只处理一次，汇总记录重复项及首次出现的行号。
单项失败后继续处理其余提交，`summary.json` 记录每行状态、完整 SHA、输出目录或错误原因。
结果含诊断仍视为成功导出；任何条目失败时整个命令返回 2，否则返回 0。
已有汇总文件默认在开始处理前拒绝覆盖；`--overwrite` 可替换汇总和本次提交的已有结果。
重复项不会覆盖首次处理的结果，也不将首次失败自动重试。

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
暂不支持根提交、合并提交或独立补丁文件。Python 接口处理单个提交，CLI 支持文件批量输入。

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
│       ├── patch_selection/
│       ├── patch_context/
│       ├── pattern_analysis/
│       ├── query_synthesis/
│       ├── validation/
│       ├── evaluation/
│       └── workflow/
└── tests/
    └── README.md
```

六个业务模块分别负责补丁筛选、补丁上下文、缺陷模式、查询合成、查询验证、泛化评估。
`workflow/` 负责流程调度，不作为业务模块计数。
除 `patch_selection`、`patch_context` 外，其他模块当前仍只包含职责说明文件。

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
