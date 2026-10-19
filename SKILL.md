---
name: obsidian-papers
description: 根据指定的论文链接，使用校园网与专用 Edge 下载 PDF 到 Obsidian vault 或本地目录，并可选使用 MinerU 转成保留图片的 Markdown，以论文标题命名文件。
---

# Obsidian Papers

用于指定论文链接的下载与可选转换，不做文献检索或摘要筛选，也不是 Obsidian 插件。

## 执行

- 以下路径均相对于本技能目录。首次运行 `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`，创建环境并取得固定版本下载引擎。详细安装和输出约定见 [README.md](README.md)。
- 使用用户指定的 vault/目录作为 `--output`。如果未指定且上下文无法确定，先保存到本技能的 `downloads/`，告知实际路径，不猜测 vault。不要修改 `.obsidian` 配置。
- 校园访问使用当前网络和独立 Edge profile。提醒用户校园网必须可用；如果代理或 TUN 影响校园身份，用户需自行关闭。代码忽略代理环境变量并给 Edge 加直连参数，不改变系统网络设置。已有校园网可用的确认不必重复询问。
- 运行 `.venv/Scripts/obsidian-papers.exe "论文链接" --output "目标目录"`。支持 DOI 链接、出版社页面、直接 PDF 链接。可用 `--title "论文准确标题"` 补充或纠正元数据。无法取得可靠标题时先查清标题，不使用 DOI 或 `full.md` 充当论文标题。
- 用户明确要求 Markdown 时加 `--markdown`；否则只下载 PDF。转换会将 PDF 上传至 MinerU，明确的转换请求即授权该步骤。首次说明上传目的，token 仅通过 `MINERU_TOKEN` 或 `config/mineru.local.toml` 提供，不写入聊天、公开配置或 Git。
- 登录或校园访问失败时，可运行 `.venv/Scripts/obsidian-papers.exe "论文链接" --prepare-profile`，让用户在专用 Edge 完成登录。不要尝试绕过验证码或无订阅权限；一次失败后检查原因，不无限重试。
- PDF 已下载但转换中断时，运行 `.venv/Scripts/obsidian-papers.exe --convert-pdf "PDF绝对路径" --title "原论文标题"`，复用本地检查点查询远端任务，避免再次下载。远端失败、过期上传地址需用户核实 MinerU 任务后使用新目录重新开始；不要自动反复创建付费任务。

## 输出

`目标目录/<安全论文标题>/<安全论文标题>.pdf`，来源记录为同目录 `paper.json`。
Markdown 位于 `markdown/` 下原结果层级，主文件改名为 `<安全论文标题>.md`，图片保持与主文件原有相对目录。Obsidian 以文件名显示笔记标题，不改写正文内容。

文件名保留标题中的空格和中文，将 Windows 禁用字符及 Obsidian 链接保留字符（如 `: / \\ ? * [ ] # ^`）替换为 `_`。末尾空格和点移除，Windows 设备名加 `_`，过长标题按 UTF-8 字节预算截断。原始完整标题保存在 `paper.json`。

同名目录来源不同或同名 PDF 内容不同时停止，不能覆盖用户笔记。完成后报告 PDF、可选 Markdown 的实际路径及失败原因，不把仅完成参数检查描述为真实下载成功。
