# PDF2Markdown v0 项目说明

PDF2Markdown 用于把 PDF 转换为适合 Obsidian / Markdown 阅读和整理的文档。工具会尽量保留正文、LaTeX 公式、图片、图注、表格和每篇文档的转换报告。

本工具目前支持两种工作方式：

- 本地模式：使用本机 NVIDIA GPU 和本地 MinerU VLM 模型，准确性较高，安装体积大，安装后可离线转换。
- API 模式：使用 MinerU API，安装轻量、转换较快，需要联网和 API Token，个别公式或版面准确性可能有瑕疵。

## 项目目录

项目根目录主要包含：

- `README.md`：项目说明，也就是你正在读的文件。
- `input/`：放入待转换 PDF。
- `output/`：正式转换结果。
- `tool_v0/`：v0 版本程序、运行环境、规则和说明。
- `PDF2Markdown_Local.cmd` 或 `PDF2Markdown_API.cmd`：安装版的双击运行入口。

`tool_v0/converter_core/` 是 Python 转换引擎源码，不是第二个项目。安装版本不包含开发测试文件；开发项目中额外存在的 `development/`、`.python-dev/` 等目录只供维护使用。

## 使用方法

1. 把一个或多个 PDF 放入 `input/`。
2. 双击项目根目录中的 `PDF2Markdown_Local.cmd` 或 `PDF2Markdown_API.cmd`。
3. 等待窗口显示“全部完成”。
4. 到 `output/原PDF文件名/` 中取用 `article.md` 和图片资源。

默认情况下，如果某个 PDF 已有 `output/同名文件夹/article.md`，工具会自动跳过，避免重复生成。

## GitHub 与安装包说明

- GitHub 仓库只包含源码、说明、运行入口和联网安装器。
- `PDF2Markdown-Installer_v0.exe` 是联网引导安装器，不是离线完整包。
- 仓库不包含用户 PDF、转换结果、本地 Python 环境、本地模型或 API Token。
- Local 模式安装时会下载 Python、PyTorch CUDA、MinerU VLM 和模型，安装后约 7–8 GB。
- API 模式安装时会下载轻量依赖，并要求用户输入自己的 MinerU API Token，安装后约 100–300 MB。

批量转换时，某一篇 PDF 如果因为网络、Token、模型、显存、文件损坏或其他原因失败，工具会记录失败原因并继续处理下一篇。命令行最后会汇总成功、失败和跳过数量。

命令行界面使用上方动态进度区显示整批与当前文献进度，已完成步骤以普通日志保留，减少重复步骤输出。

如果转换过程中关闭命令行窗口，当前转换会中止，不会继续留在后台运行。

## 每篇文档的输出结构

每个 PDF 会生成一个同名输出文件夹：

```text
output/原PDF文件名/
├── article.md
├── assets/
│   └── figures/
└── README.md
```

- `article.md`：转换后的单栏 Markdown 正文。
- `assets/figures/`：正文引用图片，按 Fig / Table 规则整理命名。
- `README.md`：该篇文档的转换报告，包含整批开始时间、单篇耗时、方案、GPU/API 信息、页数、公式数、图片数和准确性提醒等。

## 输出交付原则

- 正文图片引用和 `assets/figures/` 文件必须一一对应。
- 图片文件和正文引用都必须使用规范名称，例如 `Fig09_1_xxx.jpg` 或 `Table01_xxx.jpg`，不交付哈希式图片名。
- Markdown 图片、Obsidian 图片和 HTML `<img src="...">` 都会统一纳入图片命名系统。
- 输出前会执行图片交付门禁：补齐规范 Fig/Table 名缺失文件，删除未被正文引用的哈希残留。

## 已内置的最终修补规则

这些规则会在识别完成后执行，用来让输出更适合 Obsidian/MathJax：

- 行内公式使用 `$...$`，行间公式使用 `$$...$$`。
- 删除行间公式前后的多余空行，使 Markdown 更紧凑。
- 只在 `$$...$$` 行间公式内部删除残留的 `\(`、`\)`、`\[`、`\]`，避免 Obsidian 编译错误；正文普通文本不处理。
- 修正 `\vertP` 这类命令粘连问题，自动变成 `\vert P`，避免 Obsidian 把它当成不存在的命令。
- 清理 MinerU 可能生成的 `<details><summary>heatmap</summary>...` 等模型附加分析内容。
- 把简单 HTML 表格整理为 Obsidian 更容易编译的 Markdown 管道表格。
- 如果 MinerU 把图片误包进只有图片的 HTML 表格，会拆掉表格外壳，恢复为普通图片引用。
- 识别并复制 HTML `<img src="...">` 图片引用，避免正文引用图片但文件未保存。
- MinerU 产生的 `<div class="mineru-algorithm">...</div>` 算法/代码块会转成普通 Markdown 代码块，并恢复 `&gt;` 等 HTML 转义字符。
- 多行公式若被识别成单列 `array` 且后续行以 `=`、`+`、`-`、`\pm`、`\leq`、`\approx` 等开头，会自动改成 `aligned` 并补充 `&` 对齐点。
- 图片统一转成 Obsidian 引用格式，例如 `![[assets/figures/Fig01_xxx.png]]`。
- 大图如果被拆成多个连续子图，会尽量合并为一个完整 Fig 图片；优先使用 PDF 内嵌原图，失败时再拼接裁切图。
- 如果图片插在同一 Figure 图注中间，会在严格判断为图注续句时归入前一个 Figure，命名为续图，避免误命名成新图。
- 每篇 README 会再次检查正文图片引用与 `assets/figures/` 文件是否一一对应，并提示缺失、未引用或哈希式命名残留。
- 检查乱码、CID 占位符、私用区字符、公式定界符和基础 LaTeX 结构问题。

这些规则主要位于：

- `tool_v0/converter_core/refine_markdown.py`
- `tool_v0/converter_core/mineru.py`
- `tool_v0/converter_core/delivery.py`

## 已内置的个性化规则

以下规则来自本项目当前用户的偏好，和通用修补规则分开放置，方便以后增删：

- 将 `\textcircled{C}`、`\textcircle{C}`、`\circledcirc`、`\circledast` 等容易被误识别的版权符号写法，统一替换为可直接输入和显示的 `©`。
- 保留 Obsidian 友好的公式和图片引用风格。

个性化规则集中放在：

```text
tool_v0/converter_core/user_customizations.py
```

## 如何让 AI 继续添加规则

如果你发现某类固定错误，例如：

- 某个 LaTeX 命令在 Obsidian 中总是编译失败；
- 某类符号总是被 MinerU 识别错；
- 某类图片、表格或公式排版总是不符合你的习惯；
- 你希望加入自己的 Markdown 风格偏好；

可以直接把错误片段和你想要的结果发给 AI，并说明：

> 请在 PDF2Markdown 的最终修正环节添加规则；如果是我的个人偏好，请放入 `tool_v0/converter_core/user_customizations.py`；如果是通用 LaTeX/Markdown 修复，请放入 `tool_v0/converter_core/refine_markdown.py`，并同步重建安装包。

建议给 AI 的最小信息：

1. 错误输出片段；
2. 希望修正后的片段；
3. 这条规则是“通用修复”还是“个人偏好”；
4. 是否需要同步安装包。

## 两种模式的补充说明

- 本地模式运行时会调用本地 GPU 和本地模型，适合文档较多、希望可离线复用的用户；预计项目总大小约 7–8 GB。
- API 模式会把 PDF 上传到 MinerU 服务端解析，适合快速、轻量安装的用户；预计项目总大小约 100–300 MB。
- 本地模式和 API 模式可以分别安装在 `PDF2Markdown_Local` 与 `PDF2Markdown_API`，互不覆盖。

## API Token 更换

API 模式的 Token 使用 Windows 当前用户加密保存，不写入输出文档、README 或日志。

如果需要更换 Token，可以让 AI 协助重新配置，或在项目 `tool_v0` 目录下使用当前安装的便携 Python 调用：

```powershell
.\.python\python.exe -m converter_core.credentials replace
```

开发版本可能使用 `.python-dev\Scripts\python.exe`，安装版本使用 `.python\python.exe`。
