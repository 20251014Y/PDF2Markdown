# PDF2Markdown v0 项目说明

PDF2Markdown 用于把 PDF 转换为适合 Obsidian / Markdown 阅读和整理的文档。工具会尽量保留正文、LaTeX 公式、图片、图注、表格和每篇文档的转换报告。

项目根目录主要包含：

- `README.md`：项目说明。
- `input/`：放入待转换 PDF。
- `output/`：正式转换结果。
- `tool_v0/`：v0 版本程序、运行环境、规则和说明。

使用方式：

1. 把 PDF 放入 `input/`。
2. 本地模式运行 `tool_v0/run_local.cmd`；API 模式运行 `tool_v0/run_api.cmd`。安装版则双击根目录中的 `PDF2Markdown_Local.cmd` 或 `PDF2Markdown_API.cmd`。
3. 到 `output/原PDF文件名/` 中取用 `article.md`、`assets/figures/` 和该篇文档的 `README.md`。

批量转换行为：

- 已经存在 `article.md` 的 PDF 会自动跳过。
- 某一篇转换失败时，会记录原因并继续处理下一篇。
- 命令行最后会汇总成功、失败和跳过数量。
- 命令行界面使用上方动态进度区显示整批与当前文献进度，已完成步骤以普通日志保留，减少重复步骤输出。
- 如果转换过程中关闭命令行窗口，当前转换会中止，不会继续留在后台运行。

两种模式：

- 本地模式：使用本机 NVIDIA GPU 和本地 MinerU VLM 模型，准确性较高，可离线转换，预计项目总大小约 7–8 GB。
- API 模式：使用 MinerU API，安装轻量、转换较快，需要联网和 API Token，预计项目总大小约 100–300 MB。

## GitHub 分发说明

本仓库采用“源码 + 联网安装器”的方式发布。

- `PDF2Markdown-Installer_v0.exe` 是联网引导安装器，不是离线完整包。
- 仓库包含工具源码、安装器、运行入口和说明文档。
- 仓库不包含用户 PDF、转换结果、本地 Python 环境、本地 MinerU 模型或 API Token。
- `input/` 和 `output/` 只保留空文件夹占位；其中的实际文件不会上传。
- Local 模式首次安装会下载便携 Python、PyTorch CUDA、MinerU VLM 和模型，预计安装后约 7–8 GB。
- API 模式首次安装会下载便携 Python 和轻量依赖，预计安装后约 100–300 MB；用户需要输入自己的 MinerU API Token。

推荐给普通用户的使用方式：

1. 在 GitHub Release 中下载 `PDF2Markdown-Installer_v0.exe`。
2. 双击安装器，选择 Local 或 API 模式。
3. 把 PDF 放入安装目录的 `input/`。
4. 双击根目录运行文件，转换结果会出现在 `output/`。

隐私提示：

- Local 模式默认在本机处理 PDF。
- API 模式会把 PDF 上传到 MinerU 服务端解析。
- API Token 使用 Windows 当前用户加密保存，不会写入 README、日志或输出文档。

输出交付原则：

- 正文图片引用和 `assets/figures/` 文件必须一一对应。
- 图片文件和正文引用都必须使用规范名称，例如 `Fig09_1_xxx.jpg` 或 `Table01_xxx.jpg`，不交付哈希式图片名。
- Markdown 图片、Obsidian 图片和 HTML `<img src="...">` 都会统一纳入图片命名系统。
- 输出前会执行图片交付门禁：补齐规范 Fig/Table 名缺失文件，删除未被正文引用的哈希残留。

已内置最终修补规则：

- 行内公式 `$...$`，行间公式 `$$...$$`。
- 删除行间公式前后的多余空行。
- 只在 `$$...$$` 行间公式内部删除残留的 `\(`、`\)`、`\[`、`\]`，避免 Obsidian 编译错误；正文普通文本不处理。
- 修正 `\vertP` 为 `\vert P`。
- 清理 `<details><summary>heatmap</summary>...` 等附加分析内容。
- 简单 HTML 表格转为 Obsidian 兼容 Markdown 表格。
- 如果 MinerU 把图片误包进只有图片的 HTML 表格，会拆掉表格外壳，恢复为普通图片引用。
- 识别并复制 HTML `<img src="...">` 图片引用，避免正文引用图片但文件未保存。
- MinerU 产生的 `<div class="mineru-algorithm">...</div>` 算法/代码块会转成普通 Markdown 代码块，并恢复 `&gt;` 等 HTML 转义字符。
- 多行公式自动修复 `array`/`aligned` 对齐点。
- 大图被拆成多个子图时，尽量合并为一个完整 Fig 图片。
- 如果图片插在同一 Figure 图注中间，会在严格判断为图注续句时归入前一个 Figure，命名为续图，避免误命名成新图。
- 图片统一使用 Obsidian 引用格式。
- 每篇 README 会再次检查正文图片引用与 `assets/figures/` 文件是否一一对应，并提示缺失、未引用或哈希式命名残留。

个性化规则：

- 将 `\textcircled{C}`、`\textcircle{C}`、`\circledcirc`、`\circledast` 等版权符号误识别形式统一替换为 `©`。

规则入口：

- 通用修复：`tool_v0/converter_core/refine_markdown.py`
- 个性化偏好：`tool_v0/converter_core/user_customizations.py`
- MinerU 输出归一化：`tool_v0/converter_core/mineru.py`
- 图片、README、输出整理：`tool_v0/converter_core/delivery.py`

如果要让 AI 添加规则，请提供错误输出片段、希望修正后的片段，并说明这是“通用修复”还是“个人偏好”。如果需要分发给别人，还要同步重建安装包。
