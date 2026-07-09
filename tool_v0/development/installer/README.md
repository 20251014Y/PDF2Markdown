# PDF2Markdown v0 安装器说明

运行 `build-installer.ps1` 后，会覆盖生成项目根目录中的 `PDF2Markdown-Installer_v0.exe`。

安装器提供两个独立分支：

- 本地模式：安装到下载目录的 `PDF2Markdown_Local`，下载便携 Python、CUDA PyTorch、MinerU VLM 和模型；需要 NVIDIA GPU，安装后可离线转换。
- MinerU API 模式：安装到下载目录的 `PDF2Markdown_API`，只下载便携 Python 和轻量转换组件；安装时输入 MinerU 精准解析 API Token，并使用 Windows 当前用户 DPAPI 加密保存。

两个分支使用不同的安装目录、锁、配置、缓存、`input` 和 `output`，可以同时存在，不会互相替换。重新安装时只清理当前分支的程序文件，并保留 `input`、`output` 及其内容。

用户版本结构：

```text
PDF2Markdown_Local 或 PDF2Markdown_API/
├── input/
├── output/
├── tool_v0/
└── PDF2Markdown_Local.cmd 或 PDF2Markdown_API.cmd
```

安装包会携带 `tool_v0/README.md` 作为用户项目说明。该 README 必须说明：

- 项目用途和目录结构；
- 本地模式与 API 模式的优劣；
- 每篇文章输出结构；
- 已内置的最终修补规则；
- 已内置的用户个性化规则；
- 用户以后如何让 AI 添加新的修补/个性化规则。

当前规则入口：

- 通用 Markdown / LaTeX 修复：`tool_v0/converter_core/refine_markdown.py`
- MinerU 输出归一化入口：`tool_v0/converter_core/mineru.py`
- 图片、README、输出整理：`tool_v0/converter_core/delivery.py`
- 用户个性化规则：`tool_v0/converter_core/user_customizations.py`

安装器自身只携带项目代码，运行时联网获取 Python 和依赖。本地分支最终约占 7–8 GB；API 分支体积显著更小，但每次转换必须联网。
