# 科研雷达

面向气动声学、计算声学和流体力学方向的本地科研信息聚合工具。系统以期刊和会议为主要入口，自动采集公开元数据、计算主题相关性、生成中文日报，并在校园网内提供本地 Web 页面。

## 当前能力

- 以 10 个核心期刊的 ISSN 为一级入口，通过 Crossref 拉取近期 DOI 和元数据。
- 读取 ScienceDirect 官方 RSS，补充 Online First 和卷期信息。
- 可选调用 OpenAlex 补全摘要、引用数和开放获取地址。
- 监测 AIAA AVIATION、AIAA SciTech、INTER-NOISE、ICSV、ASME Turbo Expo、APS DFD 的公开页面。
- DOI 与规范化标题去重，保存每日引用数快照。
- 按期刊层级、主题相关性、引用速度、新颖性、开放程度和人工反馈评分。
- 使用 OpenAI 兼容接口生成中文结构化总结；没有摘要时不生成技术结论。
- 生成 Markdown 和 HTML 日报、周报，可选发送邮件。
- 提供本地论文列表、详情、报告归档、会议动态和反馈页面。
- 订阅全文只生成 DOI 和学校 OpenURL 链接，不自动抓取受限 PDF。

## 工作流

系统每天按以下顺序执行：

1. 从核心期刊的 ISSN、出版社 RSS 和会议公开页面采集条目。
2. 规范化 DOI、标题、日期和摘要，去除跨来源重复记录。
3. 可选使用 OpenAlex 补全摘要、引用数和开放获取信息。
4. 按期刊层级、主题相关性、引用速度、新颖性、开放程度和人工反馈评分。
5. 对高相关论文生成结构化中文总结，摘要缺失时只保留可靠元数据。
6. 生成 Markdown、HTML 日报，写入 SQLite，并可通过邮件推送。
7. 在校园网 Web 页面中提供检索、筛选、全文入口、报告归档和反馈。

## Windows 本地启动

项目已使用 `uv` 管理 Python 3.12 和依赖。

```powershell
$env:UV_CACHE_DIR=(Join-Path (Get-Location) '.uv-cache')
$env:UV_PYTHON_INSTALL_DIR=(Join-Path (Get-Location) '.python')
$env:PYTHONUTF8='1'
uv sync
Copy-Item .env.example .env
uv run python -m app.cli init-db
uv run python -m app.cli seed-demo
.\scripts\start-web.ps1
```

浏览器打开 `http://127.0.0.1:8000`。演示数据均带有 `[示例]` 标记，仅用于确认页面、评分和报告流程。

首次正式运行：

```powershell
uv run python -m app.cli run-daily
```

也可以分步执行：

```powershell
uv run python -m app.cli run-daily --no-report
uv run python -m app.cli report-daily
uv run python -m app.cli report-weekly
```

`scripts/run-daily.ps1` 等价于完整执行一次 `run-daily`。脚本会自动切换到项目根目录，并把 `uv` 缓存和 Python 安装目录限制在项目内，适合被 Windows 任务计划程序调用。

首轮真实验收会因网络、日期和来源更新情况而变化。本机 2026-10-22 的验证结果为：

- Crossref 获取 356 条，ScienceDirect RSS 获取 243 条，去重后写入 497 篇论文。
- OpenAlex 因共享出口 IP 的免费额度返回 HTTP 429，系统按设计降级为 0 条增强记录，不影响报告生成。
- 未配置 AI 接口，因此摘要任务被跳过，日报仍正常生成。
- 任务被标记为 `partial` 而不是 `failed`，表示主采集和报告已成功，但部分可选增强不可用。

## Windows 校园网部署

校园网内建议优先使用 Windows 原生部署，减少 Docker 和虚拟机带来的网络配置。部署前确认浏览器能从目标电脑访问 Crossref、出版社 RSS、OpenAlex 和会议网站。

1. 将项目放在固定目录并通过 `uv sync` 安装依赖。
2. 从 `.env.example` 创建 `.env`，填写真实邮箱、学校 OpenURL 和可选的 API Key。
3. 若要允许同一校园网中的其他设备访问，在 `.env` 中设置：

```dotenv
APP_HOST=0.0.0.0
APP_PORT=8000
```

4. 启动 Web：

```powershell
.\scripts\start-web.ps1
```

5. 查询这台电脑的局域网地址，并使用 Windows Defender 防火墙只对校园网网段开放 8000 端口：

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' } |
  Select-Object InterfaceAlias, IPAddress

New-NetFirewallRule `
  -DisplayName "Research Radar 8000" `
  -Direction Inbound `
  -Protocol TCP `
  -LocalPort 8000 `
  -Action Allow `
  -Profile Domain,Private `
  -RemoteAddress 192.168.0.0/16,10.0.0.0/8,172.16.0.0/12
```

6. 从同网段的另一台电脑访问 `http://目标电脑IP:8000`，并检查 `/health`。

`APP_HOST=0.0.0.0` 表示监听所有网卡，并不等于把端口映射到公网。系统当前没有用户登录和权限隔离，不要将端口直接暴露到互联网；如确实需要远程访问，应在校园 VPN 内使用，或在前方配置带认证的反向代理。

## 自动运行

推荐只运行一个常驻调度器：

```powershell
.\scripts\start-scheduler.ps1
```

默认按 `Asia/Shanghai` 时区执行：

- 每天 06:50：采集、增强、评分、总结、生成日报。
- 每周六 08:00：生成 7 天周报。

如果计算机不保持常驻，也可以让 Windows 任务计划程序每天调用：

```powershell
$project = "D:\Projects\article search"
$action = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$project\scripts\run-daily.ps1`""
$trigger = New-ScheduledTaskTrigger -Daily -At "06:50"
Register-ScheduledTask `
  -TaskName "ResearchRadar-Daily" `
  -Action $action `
  -Trigger $trigger `
  -Description "每日采集科研论文并生成报告"
```

Web 服务可在任务计划程序中设置为用户登录时启动 `scripts/start-web.ps1`，或者长期保留一个 PowerShell 窗口。任务计划程序中的“起始于”应填写项目根目录 `D:\Projects\article search`。

## 必要配置

编辑 `.env`：

```dotenv
CROSSREF_EMAIL=你的邮箱
USER_AGENT=ResearchRadar/0.1 (mailto:你的邮箱)
OPENALEX_MAILTO=你的邮箱
OPENALEX_API_KEY=
```

Crossref 的 `mailto` 用于礼貌池限流。OpenAlex 免费 API 可能受到共享 IP 的每日预算限制；在 [OpenAlex 官方说明](https://help.openalex.org/api/authentication/) 中申请免费 Key 后填入 `OPENALEX_API_KEY`。没有 Key 时，系统会降级到 Crossref 和 RSS，不会中断日报。

学校 OpenURL 链接因图书馆系统而异，需要从学校图书馆页面获取基础地址：

```dotenv
OPENURL_BASE=https://library.example.edu.cn/openurl
OPENURL_DOI_PARAM=id=doi:
```

如果不配置 OpenURL，报告中的全文入口会退化为 `https://doi.org/` 链接。

## AI 总结

支持 OpenAI 兼容的 `/chat/completions` 接口：

```dotenv
LLM_ENABLED=true
LLM_BASE_URL=https://your-endpoint.example/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model
```

本地 Ollama、vLLM 或其他兼容服务也可以使用。云端模式只发送公开标题、期刊和摘要，不发送订阅 PDF。未配置模型时，系统仍会完成采集、评分、列表和报告，只是论文详情显示“未生成 AI 技术总结”。

## 邮件

```dotenv
SMTP_HOST=smtp.example.edu.cn
SMTP_PORT=587
SMTP_USERNAME=radar@example.edu.cn
SMTP_PASSWORD=your-password
SMTP_FROM=radar@example.edu.cn
SMTP_TO=you@example.edu.cn
SMTP_STARTTLS=true
SMTP_SSL=false
```

多个收件人可用英文逗号分隔。

## Linux 与 Docker 部署

如果希望使用 Linux，可以在 Windows 主机上通过 Hyper-V 创建 Ubuntu Server 24.04 LTS 虚拟机，并桥接到校园网。4 vCPU、8 GB 内存和 100 GB 磁盘可运行不包含本地大模型的服务。

Docker 模式使用 `.env` 中的 `WEB_BIND` 控制主机监听地址，容器内固定为 `APP_HOST=0.0.0.0`：

```bash
cp .env.example .env
# 编辑 .env 和 config/venues.yaml
docker compose build
docker compose up -d
```

只允许校园网访问时，在 `.env` 中设置：

```dotenv
WEB_BIND=192.168.1.50
```

注意 `WEB_BIND` 只供 Docker Compose 使用；原生 Windows 启动读取的是 `APP_HOST`。同时使用主机防火墙限制来源地址段，不要把 8000 端口映射到公网。若使用本地大模型，建议把 LLM 服务放在同一局域网内具备 GPU 的机器上。

Linux 绑定目录若出现权限问题，可执行：

```bash
sudo chown -R 10001:10001 data logs cache papers
```

当前开发机没有安装 Docker，因此本轮只完成了 `docker-compose.yml` 配置检查，没有实际构建镜像。Windows 原生模式已经完成测试和真实采集验证。

## 数据目录

```text
config/             期刊、会议、兴趣词和采集策略
data/radar.db       SQLite 数据库
data/reports/       Markdown 与 HTML 报告
logs/radar.log      运行日志
cache/              临时缓存
papers/             用户人工保存的全文文件
```

数据库、配置和报告均保存在本地。建议每天备份 `data/` 和 `config/`，并保留最近的 `.env` 安全备份。

## 使用边界

- 系统不会绕过付费墙、验证码、CARSI/Shibboleth 登录或学校访问控制。
- 订阅期刊全文由用户通过学校网络或 VPN 点击链接获取。
- 批量自动下载订阅 PDF 可能违反出版社协议，本工具默认不做此类下载。
- 会议页面监测用于公开 CFP、技术程序和论文集页面，并遵守低频访问原则。
- AI 总结只依据来源提供的摘要。摘要缺失时，页面不会用模型推测论文结论。

## 常用维护命令

```powershell
uv run pytest -q
uv run ruff check .
uv run python -m app.cli init-db
.\scripts\run-daily.ps1
```

健康检查：`GET /health`。如果连续多日没有 `success` 或 `partial` 任务，应检查校园网、DNS、代理、来源页面结构以及 `logs/radar.log`。

本轮验收时 12 项自动化测试全部通过，Ruff 无告警。会议页面中 INTER-NOISE、ASME Turbo Expo 和 APS DFD 已验证可达；ICSV33 从当前出口返回连接重置，属于外部站点可达性问题，系统会在日报的采集警告中保留该错误。

