# Obsidian Papers

一个面向 Obsidian 文献收集的 Codex Skill：提供论文链接，即可通过校园网下载 PDF，并可选使用 MinerU 转成 Markdown，直接保存到笔记库。

## 功能

- **链接下载**：接收 DOI 链接、出版社页面或 PDF 直链，通过专用 Edge 会话使用校园网访问权限下载正文 PDF。
- **标题命名**：自动读取论文标题，为 PDF 和 Markdown 命名；不适合文件名的字符替换为下划线，也支持手动指定准确标题。
- **Obsidian 集成**：将文件保存到指定 vault 目录，Markdown 保留图片和原有相对路径。
- **可选 Markdown 转换**：使用 MinerU 处理已下载的论文，也可以直接转换已有 PDF。
- **中断续跑与文件保护**：保存 MinerU 任务进度，重跑时复用远端任务；遇到同名但来源或内容不同的文件时停止，避免覆盖。
- **本地私人配置**：token 保存在独立、被 Git 忽略的配置文件中，浏览器会话、转换进度及默认下载目录也不纳入版本管理。

```text
论文链接 → 校园网下载 → 论文标题.pdf → 可选 MinerU → 论文标题.md + 图片
```

## 安装与使用

需要 Windows、Python 3.11+、Git、Microsoft Edge，以及目标论文的校园网访问权限。安装时可以使用代理；下载时需校园网直连。程序不会替你关闭系统代理或 TUN。

获取仓库后，在项目目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
.venv/Scripts/obsidian-papers.exe "https://doi.org/10.1103/2yzc-fsm3" --output "D:/Notes/Papers"
```

支持 DOI 链接、出版社页面及 PDF 直链。优先采用网页的论文标题元数据，直链可读取 PDF 标题；缺失或不准确时用 `--title "准确论文标题"`。网页结构、登录与出版社反自动化机制可能导致失败，不能保证所有链接成功。

专用 Edge 会话保存在 `browser_profiles/edge-obsidian-papers/`，不会使用日常 Edge profile。需要登录时运行下面的命令，在打开的 Edge 中验证校园权限，然后回终端按回车关闭：

```powershell
.venv/Scripts/obsidian-papers.exe "https://doi.org/你的DOI" --prepare-profile
```

### 可选 MinerU

安装脚本会从公开模板生成独立的私人配置 `config/mineru.local.toml`，已有配置不会被覆盖。将 MinerU token 填入这个本地文件，不要修改或填写公开模板 `config/mineru.example.toml`。也可使用环境变量 `MINERU_TOKEN` 覆盖本地 token。添加 `--markdown` 会将 PDF 上传至 MinerU，消耗该账号的可用额度：

```powershell
.venv/Scripts/obsidian-papers.exe "https://doi.org/你的DOI" --title "论文标题" --output "D:/Notes/Papers" --markdown
# 转换失败或中断后，直接复用下载的 PDF 和远端任务
.venv/Scripts/obsidian-papers.exe --convert-pdf "D:/Notes/Papers/论文标题/论文标题.pdf" --title "论文标题"
```

转换检查点在 PDF 旁的 `.mineru.json`，可能含临时签名地址，只留本地。超时重跑上述转换命令继续查询原任务。PDF、标题或解析参数变化时拒绝复用检查点。远端任务失败或签名地址过期时，先检查 MinerU 控制台，再用新目录重建任务；当前不提供自动删除检查点或无限重试。

输出：

```text
目标目录/论文标题/
  论文标题.pdf
  paper.json
  论文标题.mineru.json        # 启用转换时生成，本地进度
  markdown/
    论文标题.md             # 保留 MinerU 原层级，可能在子目录内
    images/                 # 图片和其他解析结果
```

文件名中的 `<>:"/\|?*[]#^` 和控制字符替换为下划线，保留空格；设备名加前缀，过长标题截断，原始标题保留在来源记录。同名冲突不覆盖。Markdown 只改文件名，保留正文及图片相对路径。`--output` 默认是本项目 `downloads/`；指定 vault 内目录即可在 Obsidian 中使用。

## 作为 Skill 使用

本项目根目录就是技能目录，入口为 [SKILL.md](SKILL.md)。将整个项目复制到 Codex 的 skills 目录，目录名保持 `obsidian-papers`，然后在复制后的目录执行安装。不要只复制 `SKILL.md`，它依赖同目录的脚本和配置。也可把项目完整放到某个项目的 `.agents/skills/obsidian-papers/` 中。

示例请求：使用 `$obsidian-papers`，把这个论文链接下载到我的 Obsidian 文献目录，只要 PDF。需要 Markdown 时请明确说明。

## 开发验证

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/obsidian-papers.exe "https://doi.org/10.1234/example" --title "Title: example" --dry-run
```

测试使用本地构造 PDF、ZIP 和模拟 MinerU 客户端，不上传论文。真实校园下载需校园权限，真实转换需有效 token。

## 配置与本地数据

| 路径 | 用途 | 是否纳入 Git |
| --- | --- | --- |
| `config/mineru.example.toml` | 不含 token 的公开配置模板 | 是 |
| `config/mineru.local.toml` | 个人 token、MinerU 模型和网络选项 | 否 |
| `config/ref_downloader_edge.toml` | 专用浏览器和校园 IP 下载的公共默认值 | 是 |
| `browser_profiles/` | Edge 登录状态、Cookie 和会话 | 否 |
| `downloads/` | 默认论文输出及来源记录 | 否 |
| `*.mineru.json`、`*.mineru.lock` | 转换进度及运行锁 | 否 |
| `_references/`、`.venv/` | 安装取得的下载引擎及 Python 环境 | 否 |

自定义 `--output` 可以指向项目外的 vault。该位置的文件由 vault 自己管理；如 vault 也使用 Git，请自行排除转换检查点和其他不准备同步的文件。程序不会修改 vault 的 Git 或 Obsidian 配置。

## 适用范围

这是 Codex Skill 和命令行工具，不是 Obsidian 插件。当前面向 Windows 与 Microsoft Edge，不包含文献检索、摘要筛选或自动摘要生成。下载取决于校园订阅、登录状态及出版社页面；MinerU 转换取决于有效 token、可用额度和服务端限制。

## 功能来源

校园网下载与 MinerU 转换相关功能取自 [Nano-Li/AutoPaper](https://github.com/Nano-Li/AutoPaper/tree/c5612cb4cb67c5d96fdac9664bfb4652e0cfe55b)，经精简后独立运行，无需安装或保留 AutoPaper 项目：

- `autopaper/edge_download.py` → `scripts/obpaper/edge.py`：正文 PDF 下载原语。
- `autopaper/ref_downloader_adapter.py` → `publisher.py`：出版社识别。
- `autopaper/download.py` → `validation.py`：PDF 签名和体积验证。
- `autopaper/mineru.py` → `mineru.py`：MinerU 客户端、安全解压与暂存；移除筛选数据库耦合，转换进度由 `convert.py` 保存。
- 下载引擎沿用 [ref-downloader](https://github.com/ltczding-gif/ref-downloader/tree/1cc667351875410197acf4471e667ac272a0092e)，安装时下载固定提交，第三方源码不纳入本项目 Git。
