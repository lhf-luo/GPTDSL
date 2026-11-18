# 补丁与上下文准备

职责：解析补丁与提交信息，定位修复前后版本，整理相关源码上下文。

- 输入：内核补丁、源码位置和版本信息。
- 输出：可追溯的补丁及源码上下文材料。
- 边界：不生成检测模式、不生成查询、不决定查询是否有效。
- 实现方式：固定的只读收集流程，不调用 LLM。

## Interface

`prepare_patch_context(repo, commit, *, limits=None) -> PatchContext` 接受本地 Git 工作仓库和提交引用。
引用被固定为完整 SHA，提交必须恰有一个可在本地读取的父提交。失败抛出带 `code` 的 `PatchContextError`。

`PatchContext` 为不可变数据结构，`to_dict()` 导出 schema version 1。包括：

- `repository`、`commit`、`parent_commit`、`message`、完整 `diff`。
- `files`：变更状态、前后路径、前后 C 源码及实际增删行，所有行号均从 1 开始。
- `functions`：前后对应函数；无法唯一配对时分别保留，不猜测函数重命名。
- `fallback`：非函数区域或未解析函数周围的改动片段。
- `supplements`：局部函数定义或声明、宏和 `DEFINE_FREE` 清理定义。
- `diagnostics`、生效的 `limits`、预算裁剪后的 `markdown` 和 `complete`。

每个源码片段包含完整提交、路径、起止行、类型、符号、加入原因和源码文本。
非 C 文件只保留变更元数据及原始 diff。超限、二进制或不可用源码不伪装为空文件；
`files` 中相应文本为 `None`，诊断记录原因。新增或删除文件的不存在一侧也为 `None`，由状态区分。
非法 UTF-8 会替换并记录诊断，原始字节不保存在 JSON 中。

## 有限补充

从前后历史版本的受影响文件出发，按 include 路径确定性展开局部头文件。
引号 include 先找文件所在目录，再找仓库 `include/` 和仓库根目录；尖括号 include 只使用后两者。
不借用系统头文件、当前工作区文件或全仓库同名搜索结果。

根据相关函数与回退片段中的符号收集局部证据。`__free(name)` 优先关联 `DEFINE_FREE(name, ...)`，
宏和短包装函数最多补充一层被调用定义。不执行预处理，不推断宏展开后的控制流或自动清理语义。
多处同名定义会报告歧义；唯一可见定义也不代表在特定内核构建配置下必然生效。

`ContextLimits` 默认：include 深度 3、每版本局部搜索文件 128、候选符号 32、根符号 6、
补充片段总计 12、短包装函数 24 行、单源码文件 2 MiB、Markdown 32,000 字符。
除局部文件数和深度外，补充预算由前后版本共享。根符号按实际解析到的不同请求计数。

Markdown 优先展示修复前材料，并围绕实际修改行裁剪长函数；所有省略均有诊断。
JSON 中已收集的源码不受 Markdown 预算裁剪。头文件材料按进程内缓存去重，没有持久缓存。

## Implementation

- `repository`：只读 Git 对象访问及受大小限制的源码读取。
- `syntax`、`changes`：Tree-sitter C 解析、diff 实际改动行定位和前后函数配对。
- `supplement`：局部历史 include 闭包和有预算的符号补充。
- `prepare`、`render`：收集组织与独立的可读材料渲染。

调用方无需按顺序调用这些内部模块，只使用上面的 Interface。

CLI 另外支持 `--commit-file` 批量输入。批量层只负责逐项调用这个单提交 Interface、去重与汇总，
不改变本模块的收集逻辑。结果按完整 SHA 分目录导出，列表格式及错误处理详见项目 README。
