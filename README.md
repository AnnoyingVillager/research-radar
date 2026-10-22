# 科研雷达

面向气动声学、计算声学和流体力学方向的本地科研信息聚合工具。系统优先从核心期刊、出版社 RSS 和重要会议公开页面采集信息，不要求用户直接浏览 arXiv。

## 主要能力

- 以期刊 ISSN、出版社 RSS 和会议公开页面为主要信息源。
- 使用 Crossref、OpenAlex 补全论文元数据、摘要、引用和开放获取信息。
- 监测 AIAA、INTER-NOISE、ICSV、ASME、APS 等方向的期刊和会议动态。
- 按期刊层级、主题相关性、引用速度、新颖性、开放程度和人工反馈评分。
- 使用 OpenAI 兼容接口生成中文结构化总结，并可在论文页面手动更新单篇总结。
- 生成 Markdown、HTML 日报和周报，可选通过 SMTP 发送邮件。
- 提供论文检索、详情、报告归档、会议动态和管理员设置页面。

## 安全设计

- Web 默认直接启用 HTTPS，并自动生成包含所配主机名和 IP 的自签名证书。
- 管理员密码使用 PBKDF2-SHA256 加盐哈希保存，不保存可恢复的明文密码。
- OpenAlex API Key、LLM API Key 和 SMTP 密码使用 Fernet 认证加密后写入 SQLite。
- 设置页面只显示“已保存”，不会把已保存的密钥回填到 HTML。
- 登录 Cookie 使用随机密钥进行 HMAC 签名，并设置 `HttpOnly`、`Secure` 和 `SameSite=Lax`。
- 配置 LLM API Key 时只允许 HTTPS 接口；SMTP 凭据只允许通过 SSL 或 STARTTLS 发送。
- SMTP TLS 会校验服务器证书；OpenAlex 固定使用 HTTPS。
- 数据库迁移会加密旧版明文设置，并清理 SQLite WAL 和空闲页中的旧明文残留。
- 应用默认不加载 `.env`。数据库管理的敏感字段不会被同名环境变量覆盖。

加密设置依赖 `radar-secrets` 卷中的 `settings-encryption.key`。数据库和该密钥必须一起备份，但建议分开保管；只有 `radar-data` 无法解密 API Key 和 SMTP 密码。

主机管理员权限被攻陷、容器被以 root 权限控制或浏览器终端本身被控制时，任何本地加密方案都无法继续保护已解密到内存中的密钥。请限制 SSH、Docker 和备份目录权限。

## x86_64 iStoreOS 一键部署

目标环境需要：

- x86_64 iStoreOS 或其他 Linux。
- Docker Engine。
- Docker Compose v2。
- 能访问 `ghcr.io`、Crossref、出版社站点、OpenAlex 和所选 LLM 接口。

不需要 `.env`、源码、Python、手动创建数据目录或执行 `chown`。部署只需要一个 `docker-compose.yml`。

### 1. 下载 Compose 文件

通过 SSH 登录 iStoreOS：

```sh
mkdir -p /root/research-radar
cd /root/research-radar
curl -fsSLO https://raw.githubusercontent.com/AnnoyingVillager/research-radar/main/docker-compose.yml
```

如果 GitHub Raw 访问不稳定，也可以在浏览器打开仓库中的 `docker-compose.yml`，将内容保存到该目录。

### 2. 修改 Compose 中的必要参数

至少修改以下两项：

- `TLS_HOSTNAMES`：加入软路由实际的局域网 IP 或域名。例如软路由是 `192.168.1.50`，就写成 `research-radar.local,192.168.1.50,localhost,127.0.0.1`。
- `CROSSREF_EMAIL`、`USER_AGENT`、`OPENALEX_MAILTO`：改成真实联系邮箱。

常用设置：

| 参数 | 用途 | 默认值 |
| --- | --- | --- |
| `APP_NAME` | 网页标题 | `科研雷达` |
| `APP_TIMEZONE` | 时区 | `Asia/Shanghai` |
| `TLS_ENABLED` | 启用内置 HTTPS | `true` |
| `TLS_HOSTNAMES` | 证书包含的域名或 IP | 示例私网地址 |
| `SESSION_MAX_AGE_HOURS` | 登录有效期 | `168` |
| `SESSION_HTTPS_ONLY` | 登录 Cookie 仅通过 HTTPS | `true` |
| `CROSSREF_EMAIL` | Crossref 联系邮箱 | 示例邮箱 |
| `DAILY_RUN_HOUR` / `DAILY_RUN_MINUTE` | 每日采集时间 | `6:50` |
| `WEEKLY_RUN_DAY` | 周报星期 | `sat` |
| `HTTP_PROXY` / `HTTPS_PROXY` | 校园网出网代理 | 空 |

端口默认为：

```yaml
ports:
  - "${WEB_BIND:-0.0.0.0}:${WEB_PORT:-8443}:8443"
```

不创建 `.env` 时，默认监听所有网卡的 `8443` 端口。如只需 LAN 访问，可把 `WEB_BIND` 对应默认值改为具体 LAN IP；如需换端口，可直接编辑这一行。

> 不建议在代理 URL 中填写用户名和密码，因为 Compose 环境变量属于明文配置。需要认证代理时，优先使用主机级透明代理或独立的代理服务。

### 3. 启动

```sh
cd /root/research-radar
docker compose pull
docker compose up -d
docker compose ps
```

首次启动会创建命名卷，并自动生成：

- 一次性初始化令牌。
- 登录会话签名密钥。
- 设置加密密钥。
- 自签名 TLS 证书和私钥。

检查启动日志：

```sh
docker compose logs --tail=100 web
```

### 4. 创建管理员

读取一次性初始化令牌：

```sh
docker compose exec web cat /app/secrets/setup-token
```

在浏览器打开：

```text
https://软路由局域网IP:8443/setup
```

输入刚读取的令牌、管理员用户名和至少 12 个字符的密码。创建成功后：

- 一次性令牌文件会被删除。
- 管理员密码以 PBKDF2 哈希保存。
- 浏览器会自动登录。

初始化令牌等同于首次安装控制权，不要发到聊天群、工单或截图中。若怀疑泄露，应在完成初始化前删除 `radar-secrets` 卷后重新启动。

### 5. 处理自签名证书

默认证书可以立即提供加密连接，但新设备第一次访问时会出现证书警告。长期使用建议把证书导入访问设备的受信任根证书：

```sh
cd /root/research-radar
docker compose cp web:/app/secrets/tls-cert.pem ./research-radar-cert.pem
```

然后将 `research-radar-cert.pem` 导入电脑或手机的受信任证书存储。不要形成“看到证书错误就永久忽略”的习惯，因为这会削弱对主动中间人攻击的防护。

修改 `TLS_HOSTNAMES` 后重启 `web`，应用会重新生成匹配新地址的证书，需要重新导入：

```sh
docker compose up -d --force-recreate web
```

### 6. 在网页配置外部服务

登录后打开“系统设置”：

- OpenAlex API Key。
- 学校 OpenURL 地址和 DOI 参数。
- OpenAI 兼容 LLM 地址、模型和 API Key。
- SMTP 主机、端口、用户名、密码、发件人和收件人。
- 管理员新密码。

密钥输入框留空表示保持数据库中的原值；勾选对应“清除”选项可删除密钥。保存后，下一次采集任务会自动读取新配置，不需要重启容器。

SMTP 必须启用 SSL 或 STARTTLS，且服务器证书必须能被容器信任。LLM API Key 只能发送到 HTTPS 地址；不含密钥的局域网 HTTP 模型服务仍可使用。

### OpenCode 接口配置

本项目调用 OpenAI 兼容的 Chat Completions 接口。使用 OpenCode Go 时填写：

```text
基础地址：https://opencode.ai/inference/go/openai/v1
模型：glm-5.3-flash、glm-5.3、kimi-k3、deepseek-v4.1-flash 等
```

旧地址 `https://opencode.ai/zen/go/v1` 会在运行时自动转换为新地址。模型必须支持该服务的 Chat Completions 接口；OpenCode 把部分 GPT 型号放在 Responses 接口，把部分 Claude、Qwen 型号放在 Messages 接口，这些型号不能直接填入本项目。模型 ID 应填写接口返回的 ID，不要填写网页上带空格和后缀的展示名称。

OpenCode Go 官方定位为编程代理流量，普通论文总结是否符合其使用范围应以该服务条款为准。若主要用于非编程任务，建议使用 OpenCode Console 的按量付费接口或其他兼容 Chat Completions 的模型服务。

### 7. 防火墙

只允许校园网、VPN 或可信 LAN 网段访问 `8443`。不要把该端口直接映射到公网，也不要在路由器上关闭 TLS 后继续从不可信网络登录。

## 从公开 GHCR 拉取镜像

仓库公开后，Actions 会自动构建并推送：

```text
ghcr.io/annoyingvillager/research-radar:latest
```

如果匿名拉取提示 `denied`，请在 GitHub 的 `Packages` 中找到 `research-radar`，进入 `Package settings`，将包可见性设为 `Public`。代码仓公开不会自动保证关联容器包也公开。

确认镜像可匿名拉取：

```sh
docker pull ghcr.io/annoyingvillager/research-radar:latest
```

## 更新

```sh
cd /root/research-radar
docker compose pull
docker compose up -d --remove-orphans
```

`latest` 适合持续获取更新。需要可回滚的生产部署时，可将 Compose 中的镜像固定为 Actions 生成的 `sha-<commit>` 标签。

## 数据、备份与恢复

Compose 使用五个命名卷：

| 卷名 | 内容 |
| --- | --- |
| `radar-data` | SQLite 数据库和报告文件 |
| `radar-secrets` | 加密密钥、会话密钥、TLS 私钥和首次初始化令牌 |
| `radar-logs` | 运行日志 |
| `radar-cache` | 临时缓存 |
| `radar-papers` | 用户保存的全文文件 |

实际卷名通常带 Compose 项目名前缀，可查看：

```sh
docker volume ls
docker compose config --volumes
```

备份 `radar-data` 时必须同时备份 `radar-secrets`。建议：

1. 将两份备份加密。
2. 分开存放在不同位置。
3. 限制备份文件为当前管理员可读。
4. 定期验证恢复流程。

只恢复数据库而丢失 `radar-secrets` 会导致 API Key、SMTP 密码无法解密，网页设置会明确报错，不会用新密钥覆盖旧密文。

停止容器但保留数据：

```sh
docker compose down
```

不要执行 `docker compose down -v`，除非确认要彻底删除数据库、报告、密钥和 TLS 私钥。

## 源码开发

项目使用 Python 3.12 和 `uv`。

### Linux

```sh
uv sync --frozen
uv run python -m app.cli init-db
uv run python -m app.run
```

### Windows PowerShell

```powershell
$env:UV_CACHE_DIR=(Join-Path (Get-Location) '.uv-cache')
$env:UV_PYTHON_INSTALL_DIR=(Join-Path (Get-Location) '.python')
$env:PYTHONUTF8='1'
uv sync --frozen
uv run python -m app.cli init-db
uv run python -m app.run
```

源码模式默认访问：

```text
https://127.0.0.1:8443/setup
```

原生运行会在项目下的 `secrets/` 中生成密钥和 TLS 文件。该目录已被 Git 忽略，不要打包、上传或提交。

仅供本机调试时，可以显式关闭 TLS，但此时登录密码会以明文经过网络，不得在校园网共享网卡上使用：

```powershell
$env:TLS_ENABLED='false'
$env:SESSION_HTTPS_ONLY='false'
uv run python -m app.run
```

### 手动运行任务

```sh
uv run python -m app.cli run-daily
uv run python -m app.cli run-daily --no-report
uv run python -m app.cli report-daily
uv run python -m app.cli report-weekly
uv run python -m app.cli scheduler
```

网页保存的运行时设置会由采集、总结、报告和邮件模块自动读取。

“单次最多总结”表示每次任务固定检查按排序取出的前 N 篇论文。前 N 篇中已有 AI 总结的论文会跳过，但不会因此继续顺延总结第 N 篇之后的论文。管理员也可以在首页或论文详情页手动更新指定论文的 AI 总结。

## Docker 镜像构建

GitHub Actions 在 `main` 分支、`v*` 标签和手动触发时执行：

1. 安装锁定依赖。
2. 执行 Pytest 和 Ruff。
3. 构建 `linux/amd64` 镜像。
4. 推送 GHCR 镜像。

工作流使用仓库内置的 `GITHUB_TOKEN` 推送，不保存 Docker PAT。

本机构建：

```sh
docker build -t research-radar:local .
docker run --rm -p 8443:8443 \
  -e APP_HOST=0.0.0.0 \
  -e APP_PORT=8443 \
  -e TLS_HOSTNAMES=192.168.1.50 \
  -v research-radar-data:/app/data \
  -v research-radar-secrets:/app/secrets \
  research-radar:local
```

## 项目结构

```text
app/                  FastAPI、采集、评分、报告、认证和加密
config/               期刊、会议、兴趣词和采集策略
data/                 源码模式下的 SQLite 与报告
logs/                 源码模式下的日志
cache/                临时缓存
papers/               用户人工保存的全文文件
secrets/              本地密钥与证书，禁止提交
tests/                自动化测试
Dockerfile            容器镜像定义
docker-compose.yml    x86_64 单文件部署配置
```

## 诊断

```sh
docker compose logs --tail=200 web
docker compose logs --tail=200 worker
docker compose exec web python -m app.cli init-db
curl --insecure --fail https://127.0.0.1:8443/health
```

`curl --insecure` 只用于本机健康探测，不应在普通外发 API 客户端中关闭证书校验。

本地开发检查：

```powershell
uv run pytest -q
uv run ruff check .
git diff --check
```

若采集长期没有成功记录，依次检查校园网 DNS、代理、出版社页面结构、OpenAlex 限额、LLM 服务和 `radar-logs`。

LLM 返回 4xx 时，日志会记录经过脱敏的 HTTP 状态、错误类型、错误代码、错误参数和服务端消息，不会记录 API Key、Authorization 请求头或完整提示词。排查时重点查看：

```sh
docker compose logs --tail=200 worker | grep "LLM request failed"
```

若错误为 `model_not_found`，检查模型 ID；若提示接口族或路径不支持，说明该模型不走 `/chat/completions`；若为 `401` 或 `403`，检查 API Key 和账户额度；若为连接超时，检查软路由 DNS、代理和 LLM 服务可达性。

## 使用边界

- 不绕过付费墙、验证码、CARSI/Shibboleth 登录或学校访问控制。
- 订阅全文由用户通过校园网或 VPN 点击 OpenURL 获取。
- 默认不批量下载订阅 PDF。
- 会议监测只访问公开 CFP、技术程序和论文集页面。
- AI 只依据来源提供的标题和摘要，不推测缺失的论文结论。
