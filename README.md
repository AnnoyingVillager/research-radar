# 科研雷达

面向气动声学、计算声学和流体力学方向的本地科研信息聚合工具。系统以期刊和会议为主要入口，自动采集公开元数据、相关性与热度信号，生成中文日报，并在校园网内提供本地 Web 页面。

## 主要能力

- 以核心期刊 ISSN、出版社 RSS 和会议公开页面为主要信息源，不要求用户直接浏览 arXiv。
- 使用 Crossref、ScienceDirect RSS、OpenAlex 补全论文元数据、摘要、引用和开放获取信息。
- 监测 AIAA、INTER-NOISE、ICSV、ASME、APS 等方向的重要会议页面。
- 按期刊层级、主题相关性、引用速度、新颖性、开放程度和人工反馈评分。
- 使用 OpenAI 兼容接口生成中文结构化总结。
- 生成 Markdown、HTML 日报和周报，可选通过 SMTP 发送邮件。
- 提供论文检索、详情、报告归档、会议动态和反馈页面。
- 提供管理员登录和网页设置页面，SMTP、OpenAlex Key、LLM Key 等保存在数据库中。
- 只保存 DOI、公开元数据和学校 OpenURL 入口，不自动绕过出版社访问控制。

## 一键 Docker 部署

目标主机需要满足：

- x86_64 Linux，例如 iStoreOS、OpenWrt、Debian 或 Ubuntu。
- 已安装 Docker Engine 和 Docker Compose v2。
- 能访问 GitHub Container Registry 以及 Crossref、出版社、OpenAlex 等外部站点。

Docker 部署不需要 `.env`、源码、Python、单独创建数据目录或执行 `chown`。只需要 `docker-compose.yml`。

### 1. 获取 Compose 文件

仓库公开后，可直接下载：

```sh
mkdir -p /root/research-radar
cd /root/research-radar
curl -fsSLO https://raw.githubusercontent.com/AnnoyingVillager/research-radar/main/docker-compose.yml
```

仓库仍为私有时，从仓库复制 `docker-compose.yml` 到该目录。

### 2. 编辑 `docker-compose.yml`

至少修改以下三项：

```yaml
ADMIN_USERNAME: "admin"
ADMIN_PASSWORD: "替换为至少10位的强密码"
SESSION_SECRET: "替换为一段足够长的随机字符串"
```

同时建议修改真实联系邮箱：

```yaml
CROSSREF_EMAIL: "你的邮箱"
USER_AGENT: "ResearchRadar/0.1 (mailto:你的邮箱)"
OPENALEX_MAILTO: "你的邮箱"
```

常用可调参数都在 `x-radar-environment` 中：

| 参数 | 用途 | 默认值 |
| --- | --- | --- |
| `APP_NAME` | 网页标题 | `科研雷达` |
| `APP_TIMEZONE` | 时区 | `Asia/Shanghai` |
| `ADMIN_USERNAME` | 首次创建的管理员用户名 | `admin` |
| `ADMIN_PASSWORD` | 首次创建的管理员密码 | 必须修改 |
| `SESSION_SECRET` | 登录 Cookie 签名密钥 | 必须修改 |
| `CROSSREF_EMAIL` | Crossref 联系邮箱 | 示例邮箱 |
| `DAILY_RUN_HOUR` / `DAILY_RUN_MINUTE` | 每日采集时间 | `6:50` |
| `WEEKLY_RUN_DAY` | 周报星期 | `sat` |
| `HTTP_PROXY` / `HTTPS_PROXY` | 校园网出网代理 | 空 |

端口映射在 `web.ports` 中：

```yaml
ports:
  - "${WEB_BIND:-0.0.0.0}:${WEB_PORT:-8000}:8000"
```

`WEB_BIND` 控制监听地址，`WEB_PORT` 控制主机端口。直接编辑默认值也可以，例如改成 `192.168.1.50:8000:8000`。如果希望只允许本机反向代理访问，可使用 `127.0.0.1:8000:8000`。

### 3. 启动

```sh
cd /root/research-radar
docker compose up -d
```

Compose 会自动拉取镜像、创建命名卷、启动 Web 和调度器。检查状态：

```sh
docker compose ps
docker compose logs -f web
```

浏览器访问 `http://软路由局域网IP:8000`，点击“管理员登录”，使用 Compose 中的管理员账号登录。

### 4. 在网页配置密钥

登录后打开“系统设置”，配置：

- OpenAlex API Key。
- 学校 OpenURL 地址和 DOI 参数。
- OpenAI 兼容接口地址、模型和 API Key。
- SMTP 主机、端口、用户名、密码、发件人和收件人。
- AI 与邮件功能开关。
- 新管理员密码。

设置保存在 `radar-data` 命名卷中的 SQLite 数据库里，下一次采集任务会自动读取，无需重启容器。密钥输入框留空表示保持数据库中的原值；勾选“清除”可删除已保存密钥。

> `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 只用于空数据库的首次初始化。数据库已有用户后，再修改 Compose 中的密码不会覆盖现有密码，请使用“系统设置”页面修改。

## iStoreOS 部署

以下流程适用于在 iStoreOS 上安装官方 Docker 和 Docker Compose 的 x86_64 设备。

1. 在 iStoreOS 的“系统” -> “磁盘管理”中确认 Docker 数据目录位于容量足够的磁盘。
2. 通过 SSH 登录软路由。
3. 检查版本：

```sh
docker --version
docker compose version
docker version --format '{{.Server.Arch}}'
```

最后一条命令应输出 `amd64` 或 `x86_64`。

4. 创建部署目录并放入 `docker-compose.yml`：

```sh
mkdir -p /root/research-radar
cd /root/research-radar
vi docker-compose.yml
```

5. 修改管理员密码、会话密钥、联系邮箱、端口和代理后启动：

```sh
docker compose up -d
docker compose ps
```

6. 在 iStoreOS 防火墙中只对校园网或 LAN 网段开放映射端口。不要将 8000 端口直接映射到公网。
7. 浏览器访问 `http://软路由IP:8000`，登录后完成网页配置。

### 当前私有仓库的 GHCR 登录

仓库和 GHCR 包尚未公开时，软路由无法匿名拉取镜像。需要在 GitHub 创建仅含 `read:packages` 权限的经典 Token，然后执行一次：

```sh
echo "你的GitHub_Token" | docker login ghcr.io -u AnnoyingVillager --password-stdin
```

登录凭证通常保存在 `/root/.docker/config.json`。之后执行 `docker compose up -d` 即可。

代码仓公开后，请把 `research-radar` Package 的可见性也改为 Public。之后匿名拉取可用，不需要 `docker login`，Compose 文件本身也不需要保存 GitHub Token。

## Docker 数据与更新

Compose 使用四个命名卷：

| 卷名 | 内容 |
| --- | --- |
| `radar-data` | SQLite 数据库和报告文件 |
| `radar-logs` | 运行日志 |
| `radar-cache` | 临时缓存 |
| `radar-papers` | 用户保存的全文文件 |

实际卷名前缀通常来自部署目录，可通过以下命令查看：

```sh
docker volume ls
docker compose ps
```

更新部署：

```sh
cd /root/research-radar
docker compose pull
docker compose up -d --remove-orphans
```

删除容器但保留数据库和配置：

```sh
docker compose down
```

不要使用 `docker compose down -v`，除非确认要连同数据库、报告和网页保存的密钥一起删除。

数据库包含 SMTP 密码和 API Key。备份和复制命名卷时应按敏感数据保护；普通页面密码使用 PBKDF2 哈希存储，登录 Cookie 使用 `SESSION_SECRET` 做 HMAC 签名。

## 镜像构建与 GitHub Actions

仓库推送到 `main` 或推送 `v*` 标签时，GitHub Actions 会：

1. 安装锁定依赖。
2. 执行 Pytest 和 Ruff。
3. 构建 `linux/amd64` 镜像。
4. 推送至 GitHub Container Registry。

镜像地址：

```text
ghcr.io/annoyingvillager/research-radar:latest
```

主分支同时生成 `main` 和 `sha-<commit>` 标签，版本标签生成对应版本镜像。生产部署可在 Compose 中固定 `sha-<commit>`，需要自动更新时使用 `latest`。

工作流通过仓库内置的 `GITHUB_TOKEN` 推送，不需要保存 Docker 用户名或 PAT。代码仓公开后，在 GitHub 的 `Packages` -> `research-radar` -> `Package settings` 中把包改为 Public。

## 源码开发

项目使用 Python 3.12 和 `uv`。

### Windows

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

访问 `http://127.0.0.1:8000`。`[示例]` 数据只用于验证页面、评分和报告流程。

### Linux

```sh
uv sync
cp .env.example .env
uv run python -m app.cli init-db
uv run python -m app.run
```

原生开发模式仍可通过 `.env` 提供初始值。网页 `/settings` 中保存的值优先级高于环境变量。

### 手动运行任务

```sh
uv run python -m app.cli run-daily
uv run python -m app.cli run-daily --no-report
uv run python -m app.cli report-daily
uv run python -m app.cli report-weekly
uv run python -m app.cli scheduler
```

Windows 也可以使用：

```powershell
.\scripts\run-daily.ps1
.\scripts\start-scheduler.ps1
```

## 配置优先级

运行配置按以下顺序生效：

1. `app/config.py` 中的默认值。
2. 环境变量或原生开发的 `.env`。
3. 网页 `/settings` 保存到 `app_settings` 表的数据库值。

Compose 中的环境变量负责部署级参数和管理员初始化。SMTP、OpenAlex Key、LLM Key 等运行参数应在网页配置。

## 目录结构

```text
app/                  FastAPI、采集、评分、报告、认证和设置
config/               期刊、会议、兴趣词和采集策略
data/                 源码模式下的 SQLite 与报告
logs/                 源码模式下的日志
cache/                临时缓存
papers/               用户人工保存的全文文件
tests/                自动化测试
Dockerfile            容器镜像定义
docker-compose.yml    单文件部署配置
```

Docker 模式下 `config/` 已内置到镜像，数据目录改为命名卷。

## 维护与诊断

```sh
docker compose logs --tail=200 web
docker compose logs --tail=200 worker
docker compose exec web python -m app.cli init-db
curl --fail http://127.0.0.1:8000/health
```

本地开发检查：

```powershell
uv run pytest -q
uv run ruff check .
```

如果采集任务长期没有成功记录，依次检查校园网 DNS、HTTP/HTTPS 代理、出版社页面结构、OpenAlex 限额、LLM 服务和 `radar-logs` 中的日志。

## 使用边界

- 不绕过付费墙、验证码、CARSI/Shibboleth 登录或学校访问控制。
- 订阅全文由用户通过校园网或 VPN 点击 OpenURL 获取。
- 默认不批量下载订阅 PDF。
- 会议监测只访问公开 CFP、技术程序和论文集页面。
- AI 只依据来源提供的标题和摘要，不推测缺失的论文结论。
