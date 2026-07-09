# PDF2Markdown v0

PDF2Markdown 是一个把 PDF 转换为 Markdown 的 Windows 工具，支持正文、公式、图片、表格和每篇文档的转换报告整理。

这个 GitHub 仓库只用于普通用户下载，不提供源码运行入口。

## 普通用户怎么用

请只下载并运行这个文件：

```text
PDF2Markdown-Installer_v0.exe
```

不要直接下载 `Code → Download ZIP` 后运行里面的文件。  
如果你下载了源码 zip，里面也只有安装器是给普通用户双击的入口。

## 安装后会发生什么

双击 `PDF2Markdown-Installer_v0.exe` 后，安装器会让你选择一种模式：

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

## 安装完成后怎么转换 PDF

安装完成后，请进入安装目录，而不是 GitHub 下载目录。

例如 Local 模式：

```text
Downloads/PDF2Markdown_Local/
```

使用步骤：

1. 把 PDF 放入 `input/`。
2. 双击 `PDF2Markdown_Local.cmd` 或 `PDF2Markdown_API.cmd`。
3. 转换结果会出现在 `output/原PDF文件名/`。
4. 主要查看 `article.md` 和该文档的 `README.md`。

## 输出结果包含什么

每篇 PDF 会生成一个独立文件夹，通常包含：

```text
article.md
README.md
assets/figures/
```

- `article.md`：转换后的 Markdown 正文。
- `assets/figures/`：正文引用的图片。
- `README.md`：该篇文档的转换记录、耗时、模式和准确性提醒。

## 重要提醒

- 这个安装包是联网引导安装器，不是离线完整包。
- 仓库不包含用户 PDF、转换结果、本地模型、Python 环境或 API Token。
- Local 模式会在安装时下载较大的本地模型。
- API 模式会把 PDF 上传到 MinerU 服务端解析。
- API Token 由用户自己提供，并在本机加密保存。

## 如果遇到问题

如果看到：

```text
The system cannot find the path specified.
```

通常说明你运行错了文件。

请确认你运行的是：

```text
PDF2Markdown-Installer_v0.exe
```

而不是源码目录里的 `.cmd` 文件。

安装完成后，才运行安装目录里的：

```text
PDF2Markdown_Local.cmd
PDF2Markdown_API.cmd
```

## 版本

当前发布版本：v0

