---
name: obsidian-papers
description: 将给定的一个或多个论文链接通过校园网下载为 PDF，默认连续使用 MinerU 转成 Markdown，并将标题命名的文件直接存入 Obsidian 知识库指定目录；也支持仅下载 PDF。
---

# Obsidian Papers

给定论文链接后，默认执行“校园网下载 PDF → 上传 MinerU 转换 → Markdown 和图片保存到知识库合适位置，成功后删除对应 PDF”。仅当用户指定只要 PDF 时使用 `--pdf-only`。用户明确要求保留 PDF 时加 `--keep-pdf`；用户未提及时默认删除转换成功的 PDF。仅下载 PDF、转换失败或中断时保留 PDF。关闭代理会导致模型断线的场景必须使用下方两阶段任务，恢复连接后才执行命名、归档和删除。不做检索、筛选或摘要生成。

## 首次使用与目标目录

- 以下路径相对于本技能目录。首次运行 `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`。安装、命令与文件约定见 [README.md](README.md)。
- **转换前先检查 token 是否存在，仅返回有无，不输出值。** 默认读取被 Git 忽略的 `config/mineru.local.toml`，也支持 `MINERU_TOKEN`。缺少 token 时暂停并提示用户提供 MinerU token，说明会将 PDF 上传至 MinerU，保存到独立的本地私人配置后继续。推荐让用户在交互终端运行 `.venv/Scripts/obsidian-papers.exe --configure-mineru`，隐藏输入并保存；用户已明确提供 token 时可直接保存至本地配置，不复述 token，不写入公开模板或 Git。仅下载 PDF 时不要求 token。
- 使用用户指定的目录；未明确指定时结合已有 vault、当前笔记位置和文献分类选择已有合适位置，不能确定则询问目标目录。不要自行创建某篇论文或本批论文的子文件夹。用户明确要求新建目录时才创建，并将该目录传给 `--output`。不要修改 `.obsidian` 配置。

## 校园网下载：先准备本地任务，再断开模型连接

沿用 AutoPaper `download_approved.bat` 的机制：**暂停与 YES 确认发生在独立本地窗口，不是在 Codex 对话中。** 专用 Edge 的直连参数不能避开系统 TUN，但关闭 Clash 后 Codex 可能断线，所以不能要求用户“关闭 Clash 后回来回复 YES”。

1. **保持代理开启、Codex 在线时**，完成环境安装、链接/标题核对、输出目录和 token 配置。用下列入口准备本地任务（只写入本地文件并检查环境，不启动浏览器或下载）：

   ```powershell
   .venv/Scripts/obsidian-papers.exe "链接1" "链接2" --output "知识库已有目录" --prepare-task
   # 用户只要 PDF 时，准备任务也必须加 --pdf-only
   ```

   启动入口为技能 `config/.state/tasks/<任务ID>/start.bat`，同目录有 `STATUS.md` 和运行后生成的 `task.log`。任务只保存链接、参数及配置路径，不保存 token 值。准备阶段就应告知用户：关闭代理后可能无法与模型对话；本地仅下载，改名、删除与归档等操作等恢复连接后由模型执行。环境变量中的 token 若尚未写入私人配置，会保存到已有 `mineru.local.toml`，确保独立窗口能读取。
2. **在用户关闭代理之前**，先打开生成的 `start.bat`，使其在独立、可见的本地窗口等待输入。可通过系统打开该文件（Windows `Start-Process -FilePath "启动文件绝对路径" -WindowStyle Normal`）；若无法打开则给用户实际文件链接，让其双击。不要用依赖当前 Agent 回合存活的后台执行或 stdin 工具来代替独立窗口，也不要通过工具代用户输入 YES。
3. 告知用户：“本地任务已准备，请先确认启动窗口已打开，再退出 Clash（包括 TUN 模式）、关闭专用 Edge，**在该本地窗口输入 YES**。无需在 Codex 回复；本地只下载原始 PDF，下载结束后恢复代理，再让我继续转换和整理。”保留原脚本确认提示：

   > 确认已经完成上述操作，并允许专用 Edge 开始下载？输入 YES 后回车：

   只有本地窗口收到 `YES` 后才启动浏览器和校园下载；未确认或取消则不下载。不要自动修改系统代理或关闭其他应用。关闭代理将存在模型断线过程。任务只调用原有 Edge 下载流程，将原始文件写入任务的 `raw/<序号>/source.pdf`，不按标题改名，不写入知识库，不转换或删除 PDF。关闭 Codex、模型断线都不会终止本地下载。
4. 独立窗口完成下载后停留，状态为 `awaiting_model`，仅代表原始 PDF 已暂存，**不代表转换或知识库整理已完成**。用户恢复代理并重新联系模型后，先读取该任务的 `STATUS.md`、`downloads.json` 和必要的 `task.log`，检查暂存 PDF、原始标题、目标位置及保留 PDF 选项。可用 `.venv/Scripts/obsidian-papers.exe --finish-task "任务目录" --dry-run` 预览；发现缺失标题或同名冲突先处理。核对后由模型执行同命令去掉 `--dry-run`，此时才转换、按标题命名、写入知识库，以及按既有授权删除成功转换的暂存 PDF 和清理空目录。仅下载 PDF 的任务也由模型在此阶段命名归档。不要将 `--finish-task` 写入 `.bat` 或交给断线期间的自动流程，不要求用户在断线时手动执行文件整理。
5. 看到“等待确认/下载中/等待模型”时不能误报整项完成，不要重复启动同一任务。失败时先检查已下载记录和转换检查点，保留原始 PDF，不自动重跑整个下载批次。

不再使用聊天中的“已关闭代理”作为技术前提，也不再提供 `--campus-confirmed` 来跳过本地确认。直接命令行模式仍保留终端中的 `YES` 确认，但 Agent 遇到校园断线场景必须使用上述两阶段任务方式，不能调用直接模式在断线期间执行命名或删除。公开链接是否需要校园权限应根据实际访问判断；不要用“也许能公开下载”替代这套独立运行机制。

## 直接终端模式（校园断线场景使用上面的两阶段任务）

```powershell
# 默认：一个或多个链接，逐篇下载后立即转换，直接放入已有目标目录
.venv/Scripts/obsidian-papers.exe "链接1" "链接2" --output "知识库已有目录"
# 用户要求转换后也保留 PDF
.venv/Scripts/obsidian-papers.exe "链接1" --output "知识库已有目录" --keep-pdf
# 用户只要求 PDF
.venv/Scripts/obsidian-papers.exe "链接1" "链接2" --output "知识库已有目录" --pdf-only
```

- 链接、配置和目录在模型在线时确定；本地窗口获得校园确认后独立下载。恢复代理和模型连接后，再连续完成转换与整理，不逐篇反复确认。默认工作流本身包括向 MinerU 上传，无需额外的 `--markdown`。
- 支持 DOI 链接、出版社页面和 PDF 直链。优先获取准确论文标题；元数据缺失或有误时通过重复的 `--title "标题"` 按链接顺序指定。标题不可靠时先查清，不使用 DOI 或 `full.md` 作为论文标题。
- 登录失败时可运行 `.venv/Scripts/obsidian-papers.exe "链接" --prepare-profile`，让用户在专用 Edge 登录；由同样的独立任务机制启动（`--prepare-profile --prepare-task`），仍须在本地窗口确认。失败后检查原因，不绕过验证码或无限重试。
- PDF 已存在但转换中断时，用 `.venv/Scripts/obsidian-papers.exe --convert-pdf "PDF绝对路径" --title "论文标题"` 继续。此命令不启动校园下载，无需重新确认关闭代理；成功后也默认删除源 PDF，用户要求保留时加 `--keep-pdf`。
- MinerU 网络错误或超时保存远端任务供续跑；认证、配额或服务端任务错误停止，不自动反复创建任务。完成后检查点删除。

## 命名与清理

直接复用 minerU-kit 的 `_clean_for_path` 和首页标题提取函数：删除 `\ / : * ? " < > |` 及控制字符，空白转 `_`，合并连续 `_`，去掉首尾点和下划线，最多 120 字符。额外删除 Obsidian 链接保留字符 `[]#^`，处理 Windows 设备名和 UTF-8 文件名长度。PDF 根据论文元数据标题命名；Markdown 优先采用 MinerU `layout.json` 中的首页论文标题，无标题块时使用已确认的论文标题。

最终默认只保留 `<论文标题>.md` 和必要的共享 `images/`。仅在 Markdown 和图片全部导出、临时目录清理成功后删除本次转换的 PDF；删除前校验文件未在转换期间被修改。`--keep-pdf` 或 `--pdf-only` 时保留 PDF；不会新增 `paper.json`、`markdown/` 或每篇论文目录。原有其他论文不受影响。

转换 ZIP、JSON、其他解析产物只在临时 `.mineru-*` 子目录中处理；成功或失败都清理临时目录。Markdown 平铺后图片进入共享 `images/`，调整引用；同名图片内容不同则换用内容哈希名称，不能覆盖原图。仅未完成的续跑检查点和运行锁放在技能自己的 `config/.state/`，不写入知识库，也不上传 Git。

同名 PDF 或 Markdown 内容不同时停止处理该篇，不能覆盖现有笔记。完成后报告实际路径及未完成项；不要把参数预演描述为真实下载或转换成功。
