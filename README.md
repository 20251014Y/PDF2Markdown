# PDF2Markdown v0

PDF2Markdown 是一个 Windows 工具，用于把 PDF 转换为适合阅读和整理的 Markdown 文档。它会尽量保留正文、公式、图片、表格，并为每篇文档生成转换报告。

## 下载与安装

请下载并双击运行：

```text
PDF2Markdown-Installer_v0.exe
```

这是联网引导安装器。安装时可以选择：

### Local 模式

- 安装到：`Downloads/PDF2Markdown_Local/`
- 本地运行，不依赖 MinerU API。
- 首次安装会下载 Python、CUDA/PyTorch、MinerU 和本地模型。
- 预计安装后大小约 7–8 GB。
- 适合有 NVIDIA 显卡、希望本地转换的用户。

### API 模式

- 安装到：`Downloads/PDF2Markdown_API/`
- 使用 MinerU API，需要联网和自己的 MinerU API Token。
- 首次安装只下载轻量运行环境。
- 预计安装后大小约 100–300 MB。
- 适合希望安装轻、转换快的用户。

## 安装完成后怎么用

进入安装后的项目文件夹，例如：

```text
Downloads/PDF2Markdown_Local/
```

使用步骤：

1. 把 PDF 放入 `input/`。
2. 双击 `PDF2Markdown_Local.cmd` 或 `PDF2Markdown_API.cmd`。
3. 转换结果会出现在 `output/原PDF文件名/`。
4. 主要查看 `article.md` 和该文档的 `README.md`。

## 输出结果

每篇 PDF 会生成一个独立文件夹，通常包含：

```text
article.md
README.md
assets/figures/
```

- `article.md`：转换后的 Markdown 正文。
- `assets/figures/`：正文引用的图片。
- `README.md`：该文档的转换记录、耗时、模式和准确性提醒。

## 重要提醒

- 这个安装包不是离线完整包，首次安装需要联网下载依赖。
- 仓库不包含用户 PDF、转换结果、本地模型、Python 环境或 API Token。
- Local 模式会在安装时下载较大的本地模型。
- API 模式会把 PDF 上传到 MinerU 服务端解析。
- API Token 由用户自己提供，并在本机加密保存。

## 如果遇到问题

如果看到：

```text
The system cannot find the path specified.
```

通常说明运行入口不对。请确认你运行的是安装后的主入口：

```text
PDF2Markdown_Local.cmd
PDF2Markdown_API.cmd
```

如果还没有安装，请先运行：

```text
PDF2Markdown-Installer_v0.exe
```

## 版本

当前发布版本：v0

## 联系作者

作者邮箱：kezheng_yan@126.com

学术萌新，欢迎交流！

