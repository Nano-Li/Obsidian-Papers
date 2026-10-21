# Obsidian Papers

面向 Obsidian 文献收集的 Codex Skill：提供一个或多个论文链接，默认通过校园网下载 PDF，连续调用 MinerU 转成 Markdown，将笔记直接放入知识库指定目录，成功转换后默认删除 PDF。

## 功能

- **对话中给链接即可收集论文**：把一个或多个 DOI、出版社页面或 PDF 链接发给 Codex，确认校园网已就绪后，自动通过校园订阅下载正文。
- **下载后连续转成 Markdown**：自动调用 MinerU，将论文转换为包含公式、表格和图片的笔记；转换成功后默认删除 PDF，也可要求保留或仅下载 PDF。
- **直接整理进 Obsidian**：按论文标题命名，文件直接放入指定的已有目录，图片共享 `images/`，不为论文额外建文件夹，并自动清理转换中间产物。

```text
对话中提供论文链接 → 本地窗口确认并下载（期间可能断线）→ 恢复代理 → 模型转换与整理
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

> 使用 $obsidian-papers，把这些论文链接通过校园网下载并转成 Markdown，放入知识库现有的论文目录。

下面是直接终端模式；需要关闭代理、可能与模型断线时，优先使用下一节的独立两阶段任务：

```powershell
# 默认下载 PDF 并转换 Markdown，输出目录可以已经有其他论文
.venv/Scripts/obsidian-papers.exe "论文链接1" "论文链接2" --output "D:/Notes/Papers"
# 转换后同时保留 PDF
.venv/Scripts/obsidian-papers.exe "论文链接" --output "D:/Notes/Papers" --keep-pdf
# 只下载 PDF
.venv/Scripts/obsidian-papers.exe "论文链接" --output "D:/Notes/Papers" --pdf-only
# 元数据缺少准确标题时手动指定；多个链接时按顺序重复 --title
.venv/Scripts/obsidian-papers.exe "论文链接" --title "A Paper: An Example" --output "D:/Notes/Papers"
```

脚本不带 `--output` 时保存到本项目的 `downloads/`。通过 Skill 使用时优先根据指定知识库和已有文献分类确定目录；目标不明确时先询问。不会自行按论文或批次新建子文件夹；需要新目录时明确指定该目录即可。

### 关闭代理后仍可执行：独立本地任务

**不需要关闭 Clash 后回到 Codex 回复 YES。** 原 AutoPaper 使用独立 `.bat` 窗口接收确认并下载，本项目沿用同一机制。

代理还开着、Codex 仍在线时，先准备链接、目录、token 和本地任务：

```powershell
.venv/Scripts/obsidian-papers.exe "论文链接1" "论文链接2" --output "D:/Notes/Papers" --prepare-task
# 如果只要 PDF，准备任务时加 --pdf-only
```

命令返回实际的 `start.bat` 和 `STATUS.md` 路径，位于本技能的 `config/.state/tasks/<任务ID>/`；此时没有开始下载。Codex 可以打开该启动文件，也可以自己双击。

1. **先打开 `start.bat`**，确认独立本地窗口已经在等待。
2. 退出 Clash（包括 TUN 模式），关闭本技能的专用 Edge。
3. **在该本地窗口输入 `YES`**，不用在 Codex 对话中回复。窗口中的提示为：

   ```text
   请退出 Clash（包括 TUN 模式），关闭 Obsidian Papers 专用 Edge 窗口。
   断开代理后，本脚本仍会独立运行；每篇完成后会自动保存结果。
   请在此本地窗口输入 YES，不需要在关闭代理后回复 Codex。
   确认已经完成上述操作，并允许专用 Edge 开始下载？输入 YES 后回车：
   ```

4. 关闭代理后可能无法与 Codex 对话。本地脚本只下载原始 PDF，保存到任务的 `raw/<序号>/source.pdf`；不写入知识库，不做标题重命名、转换或 PDF 删除。无需模型在线；未输入 YES 或取消不会开始下载。下载后窗口停留，状态为 `awaiting_model`。
5. **恢复代理和模型连接后**，让 Codex 检查同一任务的 `STATUS.md`、`downloads.json`、日志、标题和目标位置。模型可以先预览，再执行整理：

   ```powershell
   .venv/Scripts/obsidian-papers.exe --finish-task "任务目录" --dry-run
   .venv/Scripts/obsidian-papers.exe --finish-task "任务目录"
   ```

   此时才转换为 Markdown、按标题命名并归档到知识库，删除成功转换的 PDF 及清理空暂存目录。`--pdf-only` 和 `--keep-pdf` 的原有选项仍有效。不要把整理命令放进独立启动文件；重命名和删除等操作留给重新联网后的模型执行。下载结束只是阶段完成，不代表知识库已整理完成，也无需重新下载一次。

任务文件不含 token，只引用本地私人配置；如果原来只在当前会话的 `MINERU_TOKEN` 环境变量中配置了 token，准备任务时会将它保存到 `mineru.local.toml`，供独立窗口读取。任务目录与日志都被 Git 忽略，不写入知识库。

专用 Edge 使用 `browser_profiles/edge-obsidian-papers/`，不使用日常 profile。它忽略代理环境变量并使用 `--no-proxy-server`，但不能避开系统 TUN，也不会替你退出 Clash。直接在自己的终端运行不带 `--prepare-task` 的命令时，也会在该终端等待 YES 并独立执行。

需要校园登录时也可先准备独立任务：

```powershell
.venv/Scripts/obsidian-papers.exe "论文链接" --prepare-profile --prepare-task
```

在本地窗口确认后进入专用 Edge 登录，回到该窗口按回车关闭，再准备正常下载任务。不使用聊天确认或跳过本地确认的参数。

### 输出与命名

默认只保留成功转换的 Markdown 和图片。只有 Markdown、图片导出及临时目录清理全部成功后才删除对应 PDF；转换失败或中断时保留 PDF 以便续跑。`--keep-pdf` 可保留转换后的 PDF，`--pdf-only` 始终保留 PDF。目录中其他论文不受影响。

```text
知识库已有目录/
  原有的其他论文.md
  A_Paper_An_Example.md
  Another_Paper.md
  images/                       # 多篇论文共享，仅有图片时创建
```

命名直接取自 minerU-kit 的 `_clean_for_path`：删除 `\ / : * ? " < > |` 和控制字符，空白转 `_`，合并连续下划线，去掉首尾点和下划线，最多 120 字符。额外删除 Obsidian 链接保留字符 `[]#^`，处理 Windows 设备名及 UTF-8 文件名长度。PDF 使用论文元数据标题；Markdown 优先从 MinerU 的 `layout.json` 提取首页标题，失败时回退到已确认的论文标题。

结果包在临时 `.mineru-*` 子目录解压，仅导出 Markdown 与图片；嵌套的主 Markdown 也会平铺到目标目录，并调整图片引用。同名图片内容不同会使用带内容哈希的名称。临时目录在成功或失败时都会删除，JSON、ZIP 及其他解析中间文件不会留在知识库。不会修改或删除目录中已有的论文。

### 转换中断后继续

```powershell
.venv/Scripts/obsidian-papers.exe --convert-pdf "D:/Notes/Papers/A_Paper_An_Example.pdf" --title "A Paper: An Example"
```

只转换已有 PDF，不启动校园下载，无需重新确认关闭代理。成功后同样默认删除该 PDF；需要保留时加 `--keep-pdf`。未完成任务的远端批次与参数保存在技能的 `config/.state/`，不会放进知识库或上传 Git；成功后删除该任务检查点。重试优先复用原任务，PDF 或解析参数发生变化时拒绝静默复用。已存在的同名 Markdown 不会自动覆盖或触发新的付费转换；请先检查现有笔记。认证、配额或远端失败需要核实后处理，不会无限重试。

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
