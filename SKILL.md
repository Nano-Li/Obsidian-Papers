---
name: obsidian-papers
description: 将给定的一个或多个论文链接通过校园网下载为 PDF，默认连续使用 MinerU 转成 Markdown，并将标题命名的文件直接存入 Obsidian 知识库指定目录；也支持仅下载 PDF。
---

# Obsidian Papers

给定论文链接后，默认执行“校园网下载 PDF → 上传 MinerU 转换 → PDF、Markdown 和图片保存到知识库合适位置”。仅当用户指定只要 PDF 时使用 `--pdf-only`。不做检索、筛选或摘要生成。

## 首次使用与目标目录

- 以下路径相对于本技能目录。首次运行 `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1`。安装、命令与文件约定见 [README.md](README.md)。
- **转换前先检查 token 是否存在，仅返回有无，不输出值。** 默认读取被 Git 忽略的 `config/mineru.local.toml`，也支持 `MINERU_TOKEN`。缺少 token 时暂停并提示用户提供 MinerU token，说明会将 PDF 上传至 MinerU，保存到独立的本地私人配置后继续。推荐让用户在交互终端运行 `.venv/Scripts/obsidian-papers.exe --configure-mineru`，隐藏输入并保存；用户已明确提供 token 时可直接保存至本地配置，不复述 token，不写入公开模板或 Git。仅下载 PDF 时不要求 token。
- 使用用户指定的目录；未明确指定时结合已有 vault、当前笔记位置和文献分类选择已有合适位置，不能确定则询问目标目录。不要自行创建某篇论文或本批论文的子文件夹。用户明确要求新建目录时才创建，并将该目录传给 `--output`。不要修改 `.obsidian` 配置。

## 校园网暂停确认（沿用 AutoPaper）

专用 Edge 的 `--no-proxy-server` 和清除代理环境变量不能绕过系统 TUN。**每次开始校园订阅下载前，先暂停，提示用户退出 Clash（包括 TUN 模式），关闭专用 Edge，并确认可以开始下载；未收到确认不得启动浏览器或下载。** 原项目提示为：

> 请退出 Clash（包括 TUN 模式），关闭 AutoPaper 专用 Edge 窗口。
> 断开代理后，本脚本仍会独立运行；每篇完成后会自动更新 STATUS。
> 确认已经完成上述操作，并允许专用 Edge 开始下载？输入 YES 后回车：

本技能沿用该暂停及 `YES` 确认机制，提示中的项目名改为 Obsidian Papers，状态说明改为自动保存结果。CLI 默认在下载前输出提示并等待 `YES`。在 Agent 对话中已明确取得**本批次**相同确认后，使用 `--campus-confirmed` 避免再次卡在终端；不得仅因用户提供论文链接、曾经配置校园网或要求连续完成而自行加此参数。不要自动修改系统代理或关闭其他应用。

## 连续执行

```powershell
# 默认：一个或多个链接，逐篇下载后立即转换，直接放入已有目标目录
.venv/Scripts/obsidian-papers.exe "链接1" "链接2" --output "知识库已有目录"
# 用户只要求 PDF
.venv/Scripts/obsidian-papers.exe "链接1" "链接2" --output "知识库已有目录" --pdf-only
```

- 已获得校园确认、已配置 token 且目标明确后，一气完成下载与转换，不在每篇论文或转换阶段反复确认。默认工作流本身包括向 MinerU 上传，无需额外的 `--markdown`。
- 支持 DOI 链接、出版社页面和 PDF 直链。优先获取准确论文标题；元数据缺失或有误时通过重复的 `--title "标题"` 按链接顺序指定。标题不可靠时先查清，不使用 DOI 或 `full.md` 作为论文标题。
- 登录失败时可运行 `.venv/Scripts/obsidian-papers.exe "链接" --prepare-profile`，让用户在专用 Edge 登录；该操作仍须上述校园确认。失败后检查原因，不绕过验证码或无限重试。
- PDF 已存在但转换中断时，用 `.venv/Scripts/obsidian-papers.exe --convert-pdf "PDF绝对路径" --title "论文标题"` 继续。此命令不启动校园下载，无需重新确认关闭代理。
- MinerU 网络错误或超时保存远端任务供续跑；认证、配额或服务端任务错误停止，不自动反复创建任务。完成后检查点删除。

## 命名与清理

直接复用 minerU-kit 的 `_clean_for_path` 和首页标题提取函数：删除 `\ / : * ? " < > |` 及控制字符，空白转 `_`，合并连续 `_`，去掉首尾点和下划线，最多 120 字符。额外删除 Obsidian 链接保留字符 `[]#^`，处理 Windows 设备名和 UTF-8 文件名长度。PDF 根据论文元数据标题命名；Markdown 优先采用 MinerU `layout.json` 中的首页论文标题，无标题块时使用已确认的论文标题。

最终目录只新增 `<论文标题>.pdf`、`<论文标题>.md` 和必要的共享 `images/`；不会新增 `paper.json`、`markdown/` 或每篇论文目录。原有其他论文不受影响。

转换 ZIP、JSON、其他解析产物只在临时 `.mineru-*` 子目录中处理；成功或失败都清理临时目录。Markdown 平铺后图片进入共享 `images/`，调整引用；同名图片内容不同则换用内容哈希名称，不能覆盖原图。仅未完成的续跑检查点和运行锁放在技能自己的 `config/.state/`，不写入知识库，也不上传 Git。

同名 PDF 或 Markdown 内容不同时停止处理该篇，不能覆盖现有笔记。完成后报告实际路径及未完成项；不要把参数预演描述为真实下载或转换成功。
