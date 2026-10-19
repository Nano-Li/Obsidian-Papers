# Obsidian Papers

面向 Obsidian 文献收集的 Codex Skill：提供一个或多个论文链接，默认通过校园网下载 PDF，连续调用 MinerU 转成 Markdown，将文件直接放入知识库指定目录。

## 功能

- **连续处理论文链接**：支持 DOI 链接、出版社页面与 PDF 直链，逐篇完成下载和转换；`--pdf-only` 可只下载 PDF。
- **校园网下载**：沿用 AutoPaper 的专用 Edge 下载流程，开始前暂停，要求退出 Clash（包括 TUN 模式）并确认。
- **论文标题命名**：复用 minerU-kit 的命名与首页标题提取代码，空格转下划线，删除文件名禁用字符。
- **直接保存到已有目录**：PDF 与 Markdown 平铺存放，不为论文或批次新建目录；图片共用 `images/`。
- **自动清理转换产物**：仅在临时子目录处理 ZIP、JSON 等，提取 Markdown 和图片后删除整个临时目录。
- **首次 token 引导**：未配置 MinerU token 时先提示提供并保存到独立的本地私人配置，后续复用。
- **保护现有文献**：不覆盖不同内容的 PDF、Markdown 或图片；转换中断可继续原远端任务。

```text
论文链接（一个或多个）→ 校园网确认 → 下载 PDF → MinerU 转换 → 知识库中的 PDF、Markdown 和图片
```

## 安装

需要 Windows、Python 3.11+、Git、Microsoft Edge、目标论文的校园访问权限及 MinerU token。仅下载 PDF 不需要 token。

```powershell
git clone https://github.com/Nano-Li/Obsidian-Papers.git
cd Obsidian-Papers
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

本项目根目录就是技能目录，入口为 [SKILL.md](SKILL.md)。作为 Codex Skill 安装时，将完整项目放入 skills 目录并命名为 `obsidian-papers`，在该目录执行安装；也可放入某项目的 `.agents/skills/obsidian-papers/`。不能只复制 `SKILL.md`。

### 首次配置 MinerU token

安装会从公开模板生成被 Git 忽略的 `config/mineru.local.toml`，保留已有配置。首次运行默认工作流时，若未配置 token，会先提示提供并保存，尚未开始下载。也可提前执行：

```powershell
.venv/Scripts/obsidian-papers.exe --configure-mineru
```

在交互终端隐藏输入 token，程序写入本地私人配置；后续不重复询问。非交互运行发现缺少 token 时会停止并说明配置方法，不会静默跳过转换。也可以直接填写 `config/mineru.local.toml`，或设置 `MINERU_TOKEN` 环境变量。不要将 token 填入公开模板或命令行参数。

PDF 将上传至 MinerU，使用账号的可用额度。配置项包括模型、语言、OCR 和 MinerU 网络选项；MinerU 网络配置独立于校园下载。

## 使用

在 Codex 中可直接说：

> 使用 $obsidian-papers，把这些论文链接下载并转成 Markdown，直接放入知识库现有的论文目录。

脚本入口：

```powershell
# 默认下载 PDF 并转换 Markdown，输出目录可以已经有其他论文
.venv/Scripts/obsidian-papers.exe "论文链接1" "论文链接2" --output "D:/Notes/Papers"
# 只下载 PDF
.venv/Scripts/obsidian-papers.exe "论文链接" --output "D:/Notes/Papers" --pdf-only
# 元数据缺少准确标题时手动指定；多个链接时按顺序重复 --title
.venv/Scripts/obsidian-papers.exe "论文链接" --title "A Paper: An Example" --output "D:/Notes/Papers"
```

脚本不带 `--output` 时保存到本项目的 `downloads/`。通过 Skill 使用时优先根据指定知识库和已有文献分类确定目录；目标不明确时先询问。不会自行按论文或批次新建子文件夹；需要新目录时明确指定该目录即可。

### 校园网确认与登录

**专用 Edge 不能避开系统 TUN。** 程序沿用 AutoPaper 的下载暂停机制，在启动浏览器和网络下载前提示：

```text
请退出 Clash（包括 TUN 模式），关闭 Obsidian Papers 专用 Edge 窗口。
断开代理后，本脚本仍会独立运行；每篇完成后会自动保存结果。
确认已经完成上述操作，并允许专用 Edge 开始下载？输入 YES 后回车：
```

只有输入 `YES` 才继续；取消、无输入或未确认都不会开始下载。Codex 已在对话中取得本批次相同确认时可用 `--campus-confirmed`，不能自行省略用户确认。确认后整批下载与转换连续执行，不逐篇打断。

专用 Edge 使用 `browser_profiles/edge-obsidian-papers/`，不使用日常 profile。它忽略代理环境变量并使用 `--no-proxy-server`，但不会退出 Clash 或修改系统网络。需要校园登录时：

```powershell
.venv/Scripts/obsidian-papers.exe "论文链接" --prepare-profile
```

同样完成校园确认，在打开的专用 Edge 中登录，回终端按回车关闭，再运行正常工作流。

### 输出与命名

```text
知识库已有目录/
  原有的其他论文.md
  A_Paper_An_Example.pdf
  A_Paper_An_Example.md
  Another_Paper.pdf
  Another_Paper.md
  images/                       # 多篇论文共享，仅有图片时创建
```

命名直接取自 minerU-kit 的 `_clean_for_path`：删除 `\ / : * ? " < > |` 和控制字符，空白转 `_`，合并连续下划线，去掉首尾点和下划线，最多 120 字符。额外删除 Obsidian 链接保留字符 `[]#^`，处理 Windows 设备名及 UTF-8 文件名长度。PDF 使用论文元数据标题；Markdown 优先从 MinerU 的 `layout.json` 提取首页标题，失败时回退到已确认的论文标题。

结果包在临时 `.mineru-*` 子目录解压，仅导出 Markdown 与图片；嵌套的主 Markdown 也会平铺到目标目录，并调整图片引用。同名图片内容不同会使用带内容哈希的名称。临时目录在成功或失败时都会删除，JSON、ZIP 及其他解析中间文件不会留在知识库。不会修改或删除目录中已有的论文。

### 转换中断后继续

```powershell
.venv/Scripts/obsidian-papers.exe --convert-pdf "D:/Notes/Papers/A_Paper_An_Example.pdf" --title "A Paper: An Example"
```

只转换已有 PDF，不启动校园下载，无需重新确认关闭代理。未完成任务的远端批次与参数保存在技能的 `config/.state/`，不会放进知识库或上传 Git；成功后删除该任务检查点。重试优先复用原任务，PDF 或解析参数发生变化时拒绝静默复用。已存在的同名 Markdown 不会自动覆盖或触发新的付费转换；请先检查现有笔记。认证、配额或远端失败需要核实后处理，不会无限重试。

## 配置与本地数据

| 路径 | 用途 | 纳入 Git |
| --- | --- | --- |
| `config/mineru.example.toml` | token 为空的公开配置模板 | 是 |
| `config/mineru.local.toml` | 个人 token、模型及网络选项 | 否 |
| `config/.state/` | 未完成的转换检查点和运行锁 | 否 |
| `config/ref_downloader_edge.toml` | 专用浏览器和校园 IP 的公共默认值 | 是 |
| `browser_profiles/` | Edge 登录状态及 Cookie | 否 |
| `downloads/` | 默认输出 | 否 |
| `_references/`、`.venv/` | 固定版本下载引擎及 Python 环境 | 否 |

私人配置不覆盖公共模板，安装不覆盖已有 token。自定义输出目录由知识库自身管理，程序不会修改 vault 的 Git 或 Obsidian 配置。

## 开发验证

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/obsidian-papers.exe "https://doi.org/10.1234/example" --title "Title: example" --dry-run
```

测试使用本地数据和模拟客户端，不上传论文。真实校园下载依赖订阅、登录状态及出版社页面；真实转换依赖有效 token、额度和 MinerU 服务限制。当前支持普通论文，尚不包含长文档自动分段。

## 功能来源

- [AutoPaper](https://github.com/Nano-Li/AutoPaper/tree/c5612cb4cb67c5d96fdac9664bfb4652e0cfe55b)：正文 PDF 下载、校园网暂停确认、PDF 验证、MinerU 客户端及安全解压。移除检索、筛选和数据库耦合后独立运行。
- [minerU-kit](https://github.com/Nano-Li/minerU-kit/tree/db9e99b22f4418435392ef9ed0a422f111d96478)：直接提取 `mineru_client.py` 的命名和标题提取函数，沿用 `move_llm_minerU.py`、`batch_run.py` 的平铺导出、共享图片和临时目录清理方式，补充冲突校验及引用重写。
- [ref-downloader](https://github.com/ltczding-gif/ref-downloader/tree/1cc667351875410197acf4471e667ac272a0092e)：安装时获取固定提交的校园下载引擎，源码不纳入本仓库。
