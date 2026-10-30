# XApis Web 控制台

这是在原 Python SDK 外层增加的自部署运营台。保留 CLI 与原 SDK，使用 FastAPI + MySQL 8.4 + 原生浏览器前端。所有 X 请求经过 Go `tls-client` 网关，再使用账号已绑定的 HTTP / HTTPS / SOCKS5 代理。AI 和资讯源通过独立、受限的 HTTP 客户端访问。

## Docker 启动

需要 Docker Engine 与 Docker Compose v2。默认绑定 `127.0.0.1:8000`。

```bash
docker compose up -d --build --wait
docker compose exec web python -m console.manage setup-token
```

打开 [控制台](http://localhost:8000)，粘贴终端显示的初始化令牌，创建用户名和至少 12 位密码。**成功初始化的第一个用户自动成为管理员**，此后初始化接口关闭。管理员在“设置 → 工作台用户”添加其他用户；没有公开注册入口。

首次启动会自动生成并持久化：

- `mysql-data`：MySQL 数据库，保存用户、账号、草稿、队列、关键词、养护状态与发布计数。
- `console-data`：Cookie / 代理 / AI 密钥的加密密钥、初始化令牌。
- `mysql-user-secret` / `mysql-root-secret`：初始化服务自动生成的独立数据库凭据；Web 只挂载普通用户凭据。
- `gateway-secret`：Web 与 Go 网关的内部认证令牌。网关没有映射宿主端口。

Web 与 Go 网关以非 root 用户运行、根文件系统只读。MySQL 使用官方镜像和专用持久卷；数据库与网关默认均不映射宿主端口。启动顺序为生成凭据 → MySQL / 网关健康 → Web。

### 远程服务器 / HTTPS

复制 `.env.example` 为 `.env`，配置以下值后重建服务：

```dotenv
CONSOLE_BIND=127.0.0.1
CONSOLE_PORT=8000
CONSOLE_PUBLIC_URL=https://xops.example.com
CONSOLE_COOKIE_SECURE=1
```

让宿主上的 Caddy / Nginx 反向代理至 `127.0.0.1:8000`，保留原始 `Host`，启用 HTTPS。`CONSOLE_PUBLIC_URL` 必须与浏览器访问地址一致，含协议、可选端口，不含末尾 `/`。网关认证、初始化令牌与会话 Cookie 不应出现在代理日志中。若明确需要直接监听其他网卡，可自行修改 `CONSOLE_BIND`；公网访问应使用 HTTPS。

简单 Caddy 配置：

```caddyfile
xops.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

默认不信任转发的客户端 IP，因此登录限流在反向代理后也可能共享来源 IP。不要直接启用信任任意客户端的转发头。

### macOS Colima

部分 Colima 配置不自动把虚拟机的 loopback 端口转发到 macOS。若容器健康且 `colima ssh -- curl --noproxy '*' http://127.0.0.1:8000/healthz` 正常，但宿主浏览器无法连接，可以只在本机建立转发：

```bash
ssh -F "$HOME/.colima/_lima/colima/ssh.config" \
  -o ExitOnForwardFailure=yes -N \
  -L 127.0.0.1:8000:127.0.0.1:8000 lima-colima
```

这不需要公开 Go 网关或更改全局网络设置。不同 Colima profile 的 SSH 配置路径可能不同。

## 使用流程

1. **添加账号、绑定代理**：默认只读养护周期为 4 天，可在添加时设置。在“账号管理”填写显示名称和完整代理地址；可包含代理用户名密码。未配置代理不能创建账号或发起 X 登录。
2. **登录 X**：选择账密登录，或导入包含 `auth_token` 和 `ct0` 的 Cookie。先通过已绑定的代理请求 X Viewer 验证身份，成功后才视为连接完成，并开始计算养护周期与前七天保护期。X 密码只在当次请求内存中使用，不保存。
3. **连接 AI**：在“设置”填写 OpenAI 兼容服务的基础地址（通常以 `/v1` 结尾）、模型标识和 API Key。服务需支持 `POST /chat/completions` 的非流式 `choices[0].message.content` 返回格式。API Key 留空会保留已存密钥；无密钥的本地服务可首次留空。
4. **查看内容**：主页显示当前账号时间线；“我的贴文”读取当前账号的真实贴文。搜索支持最新、热门、用户、媒体和列表，也支持用户主页或贴文详情 / 评论。支持游标分页。
5. **一键编写**：编辑器输入主题，点击“一键编写”。也可从热点条目进入编辑器；AI 总结资料后写入正文。发布前可以修改、保存草稿，或设定浏览器本地时区下的时间。
6. **自动化**：添加 RSS / Atom 或网页来源，先采集检查；然后创建规则，选择账号、来源、提示词、执行间隔和每日上限。默认保存草稿，显式选择“直接自动发布”并启用后才会无人值守发布。

### 账号养护与每日发布限制

以该 X 账号第一次成功登录此工作台的时间为起点，默认规则如下：

| 账号阶段 | 读取 | X 写操作 | 发布数量 |
| --- | --- | --- | --- |
| 前 4 × 24 小时 | 搜索、时间线、贴文、评论均可读取 | 全部禁止，包含发帖、回复、引用、点赞/取消、转帖/取消、关注/取消、书签、媒体上传、X 文章草稿和删除 | 0 |
| 第 5～7 天（满 4 天、未满 7 天） | 允许 | 允许 | 每个北京时间自然日最多 2 篇 |
| 满 7 × 24 小时 | 允许 | 允许 | 解除每日两篇限制；各自动化自己的上限仍生效 |

期限在后端按时间实时计算，到期不需要手动解锁。可提前保存本地草稿，或排期到养护结束之后。养护天数可在新增账号时设置为 1～90 天；超过 7 天时仍先满足完整只读期。

“2 篇”是整个 X 账号通过此工作台产生的数量，手动、定时和自动化共用一个 MySQL 台账；回复、引用、长帖和发布文章各算一篇，串文按每条计数。后台在发送前原子预留额度，多个请求同时到达也不能超限。未满 7 天时超过两条的串文会等待到满 7 天后再发送；当天额度不足的已排期任务延到下个北京时间自然日或满 7 天的时刻。X 明确拒绝会归还未使用额度，结果不明的发送保留额度等待核对。

同一 X 数字 ID 在多个工作台用户间共用保护期与发布计数。重新登录、改代理、删掉重加、删除草稿或记录，都不会重置它们。此限制控制本工作台的请求，无法禁止用户直接从 X 官网或其他客户端发帖。

#### 关键词目录与只读养护

在“关键词目录”新建分组，每行一个关键词；一个账号可绑定多个分组，同一个分组也可供多个账号使用。在“账号养护”中设置：

- 每轮间隔：默认 60 分钟，轮次间隔有 ±20% 随机抖动。
- 首页推荐时间线：默认开启，每轮最多 2 页，可调整至 1～10 页。读取当前账号主页的推荐内容。
- 关键词搜索页数：默认 3 页，最多 10 页。每轮先读取首页推荐，再读取绑定分组中抽取的关键词；各来源分别维护游标和页数，重复或缺失游标时停止当前来源并继续下一来源。
- 每页之间随机等待：默认 30～90 秒，可调整范围。
- 读取评论：默认启用，每条抽样贴文最多读取 2 页评论，可调整至 1～5 页。

后台每次只执行一个读取步骤，并将游标、页数和下次运行时间存进 MySQL。随机等待使用持久化排期，不阻塞其他账号。暂停/重启不会跳过等待；“运行一轮”也不能跳过正在等待的翻页间隔。

**养护任务始终只读，绝不关注、转发、点赞、喜欢、回复或发帖。** 即使账号满七天也不改变这一点。未绑定关键词时仍可浏览首页推荐；只有同时关闭首页推荐且未绑定关键词时，才仅定期读取当前用户身份进行保活。X 会话失效时停止养护并提示重新登录，限流时延长等待。升级会为已有养护配置默认开启首页推荐；已经在途的旧搜索轮次先完成，新一轮才加入首页。

每次通过 Go 网关收到 X 的 `Set-Cookie`，都会合并变更、处理 Cookie 过期/删除，并加密写回 MySQL，同时更新当前内存会话。旧请求不能覆盖重新登录或更换代理后的新会话。界面只展示最后同步时间，不展示 Cookie 值。定期读取与 Cookie 更新不能保证 X 永久保留会话，平台仍可能要求再次验证。

“账号养护 → 执行日志”每 5 秒读取一次本地日志，不会因此额外访问 X。每个后台步骤记录：

- 执行中、完成、部分错误、失败或服务中断状态，以及轮次和步骤 ID。
- 来源（首页推荐或关键词）、搜索/推荐/评论页数、返回数量、抽样贴文 ID；游标仅显示是否存在与摘要，便于比较前后页，不暴露完整游标。
- 每次实际 HTTP 请求的方法、路径、状态码、耗时、脱敏错误响应（包含 HTTP 200 中的 GraphQL 错误）。成功响应只留大小和数据概况，不保存贴文正文。
- Cookie 接收、值变化、删除的名称与加密入库时间；明确区分没有 Set-Cookie、公开素材不写回、旧会话被忽略和写入失败。
- 抽取的随机等待秒数、允许范围、下次执行时间、距上步完成的实际间隔及调度延后秒数。失败退避、限流等待和游标终止原因也会记录。

日志保留 30 天，仅账号所属的控制台用户可读取。旧记录保留原摘要，不补造过去的请求详情。服务重启会把尚未结束的记录标成中断并保留已经取得的结果。身份保活只有在 Viewer 返回当前绑定的 X 身份时才记为成功；无新 Cookie 的成功读取不等同于延长登录有效期。

### 账号代理

示例：

```text
http://username:password@proxy.example.com:8080
https://proxy.example.com:8443
socks5://username:password@proxy.example.com:1080
socks5h://proxy.example.com:1080
```

凭据中的特殊字符需要 URL 编码。代理必须从 **Go 网关容器内部**可达：容器里的 `127.0.0.1` 指向该容器，不是宿主机。Docker Desktop 可使用 `host.docker.internal`；Linux 如需宿主代理，可按部署环境添加 `host-gateway` 映射。

更换代理会清除该账号的会话、暂停其自动化并把尚未开始的排期转回草稿。需要重新登录后再启用。登录中或发布中的账号不能换代理、删除或重复登录。

网关使用库当前提供的 Chrome 150 TLS / HTTP2 profile；应用层保留原 SDK 的 Chrome 153 UA / Client Hints / Castle 实抓画像，避免破坏原登录素材。它与原项目的 Chrome 150 传输模板一样属于兼容方案，不宣称与 Chrome 153 的完整指纹完全相同。连接池由“账号 ID + 代理”确定，不跨账号复用会话 Cookie；没有代理、内部认证失败或网关不可用时，**不会回退为直连**。浏览器指纹兼容不等同于保证通过 X 的验证码、设备证明或平台风控。出现挑战时在 X 网页完成验证，再导入会话。

### AI 参数兼容

默认自动选择输出预算参数：OpenAI 官方地址与新版 / 推理模型使用 `max_completion_tokens`，其他兼容服务使用 `max_tokens`，不强制发送 temperature。可在“设置 → 服务兼容选项”手动切换。短贴文在两种模式下的预算分别为 4096 / 500 token，长文为 8192 / 2000 token；新版参数的预算也包含推理 token。官方已将 `max_tokens` 标为弃用，且 o 系列不兼容该参数，参见 [Chat Completions 官方接口文档](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。

### 本地 AI

AI 基础地址和资讯源默认拒绝内网、loopback、链路本地地址，使用 DNS 解析结果固定连接 IP，并限制响应大小、不跟随重定向，避免密钥被转发到其他主机。

若使用本地 AI 服务，由部署者在 `.env` 显式允许主机名：

```dotenv
CONSOLE_PRIVATE_AI_HOSTS=host.docker.internal,ollama
```

然后在设置中填写例如 `http://host.docker.internal:11434/v1`。此允许列表只适用于 AI，不适用于热点来源；并不会绕过 AI 服务自身的认证。

## 功能映射

| 原 SDK 能力 | 控制台入口 |
| --- | --- |
| Jetfuel 账密登录 / Cookie 会话 / Viewer | 账号管理，登录时强制代理和身份验证 |
| 首页时间线、自己的贴文、用户资料与作品 | 主页、我的贴文、探索中的用户主页 |
| 搜索 Top / Latest / People / Media / Lists | 探索 |
| 贴文详情、评论游标、补充详情 | 贴文正文 / 评论图标、探索输入贴文链接、API 工具箱 |
| 发帖、回复、引用、Premium 长帖 | 内容编辑器 |
| Thread 串文 | 编辑器选择“串文”，用单独一行 `---` 分隔 |
| 删除贴文、点赞/取消、转帖/取消、书签/取消 | 时间线贴文操作 |
| 关注 / 取消关注 | 用户搜索结果或用户主页 |
| 图片、多图片、GIF、视频的分片上传与处理 | 编辑器“添加媒体”；最多 4 张图片，或单个视频/GIF |
| 文章 Markdown、标题、正文、封面、草稿更新、发布、删除、列表 | 设置 / 右侧入口中的文章管理；编辑器选择文章 |
| 文章嵌入贴文 | Markdown 独占一行的 X 贴文链接 |
| 文章插图 | 先上传图片，正文写 `![](media:上传ID)`；第一张媒体可作为封面 |
| X Chat 设置、收件箱、会话、成员、公钥 | 私信、API 工具箱；敏感令牌隐藏 |
| X Chat 文字私信 | Cookie 网页接口、密码解锁、会话分页、加密文字发送；养护期只读 |

底层的 INIT / APPEND / FINALIZE / STATUS 等媒体步骤由上传流程统一执行。批量翻页辅助方法通过界面的“加载更多”实现，避免无界抓取。GraphQL / Castle 注册表维护仍保留原 CLI；它是 SDK 维护工具，不在普通用户页面暴露写入运行文件的入口。

点击贴文正文或评论图标会打开独立的 `#post/贴文ID` 详情页，分别展示对话上文、原文和评论；“加载更多评论”沿用 X 返回的游标并去除重复项。刷新详情链接不会丢失当前贴文，返回搜索页时保留关键词及筛选条件。浏览评论与发送回复使用不同入口；只读养护期间仍可查看与翻页，回复按钮不可用。

## 队列与自动化语义

- 每个 MySQL 数据库运行 **一个 Uvicorn worker**，内置队列线程执行任务。MySQL 命名锁保证一个数据库只有一个调度器，InnoDB 行锁与事务保证原子领取和计数。数据库断线后必须重新取得调度锁才能继续，不能直接绕过锁。
- 排期、草稿、运行记录持久化到 MySQL；服务停机期间到期的排期会在恢复后执行。
- 每次新提交带唯一请求 ID；同一用户重复提交相同 ID 不会重复创建发布任务。
- 普通贴文按 SDK 权重校验，超过 280 时必须明确启用 Premium 长帖。自动化只发布 280 权重内的普通贴文；账号在只读期或当天额度用完时先保存草稿；超长输出会记录错误，不静默截断或升级付费类型。
- 串文每发送成功一条就保存其 X ID。中途失败会保留已发布部分。
- X 明确拒绝时标记失败；网络错误或进程在发送期间终止时，标记“待核对”。**不会自动重发结果不明的请求**；先在 X 核对后再决定是否复制新草稿。
- 自动化按“规则 + 来源条目”去重。RSS 使用条目链接识别，网页使用正文摘要哈希标识内容版本。每次最多总结 3 条新内容。
- 间隔至少 15 分钟；每日限制为滚动 24 小时内当前任务生成的内容数，草稿也计入。任务暂停时，尚未发送的自动化内容转回草稿；已经发往 X 的请求无法撤回。
- 热点网页读取静态 HTML，不执行 JavaScript。建议优先使用 RSS / Atom。地址发生重定向时填写最终地址。
- 媒体由 X 托管，控制台仅保存媒体 ID；为避免过期，已上传媒体的排期不得超过上传后 23 小时。过期时需重新上传。单文件目前限 50 MB。
- X Premium 权限、X 限流、会话有效性和实时 GraphQL 变化由 X 决定；控制台会返回可操作的错误信息。

## 登录进度与排查日志

账号管理提供“测试代理”和“登录日志”。登录窗口显示当前阶段和等待时间，失败时在醒目位置展示具体原因。日志保留最近的请求方法、路径、HTTP 状态、耗时、字段名、实际脱敏响应及本地异常位置；密码、Cookie、代理认证、验证码和令牌不记录为明文。HTTP 200 响应也会记录，以排查响应体内的错误。

原始 HAR 抓包可能包含有效会话和密码，默认被 Git 和 Docker 打包忽略。已有抓包的流程对照与本次 CSRF 修复见 [登录流程分析](LOGIN_FLOW_ANALYSIS.md)。

## 安全与维护

用户密码使用带随机盐的 scrypt 哈希；会话仅保存 token 哈希，浏览器使用 HttpOnly / SameSite Cookie，写操作校验 CSRF 和来源。账号、来源、草稿、规则和 AI 配置按用户隔离。管理员仅管理工作台用户，不直接查看他人的 X Cookie 或 AI Key。

Cookie、代理密码、AI Key 使用 Fernet 加密后保存到 MySQL。加密密钥保存在 `console-data` 卷中，与数据库一起备份；这是静态数据保护，不能抵御已经拥有宿主机或数据卷权限的攻击者。应用错误响应和日志避免输出上游凭据。

```bash
# 查看服务状态与日志
docker compose ps
docker compose logs --tail=100 web gateway

# 本地终端恢复用户密码，交互输入新密码，不通过命令行参数泄露
docker compose exec web python -m console.manage reset-password --username admin

# 一致性备份（每次使用一个新的目录名）
docker compose exec web python -m console.manage backup --output /app/data/backup-2026-10-24
docker compose cp web:/app/data/backup-2026-10-24 ./backup-2026-10-24

# 更新代码后重建
docker compose up -d --build --wait
```

恢复到新的空 MySQL 数据库时，使用以下命令。恢复工具通过标准输入传递备份，不需要修改私有文件权限，也不需要以 root 容器访问宿主文件。工具拒绝覆盖已有用户的数据库，并恢复加密密钥。

```bash
docker compose stop web
python3 scripts/restore_console_backup.py ./backup-2026-10-24
docker compose up -d --wait
```
网关令牌可保留原卷或由网关重新生成，两端必须使用同一个令牌卷。备份文件是包含全部表的 `mysql-backup.json`，由 MySQL 一致性快照读取。

不要使用 `docker compose down -v` 作为普通重启命令，它会删除数据卷。不要只备份 MySQL 数据而丢失加密密钥。

## 本地开发与验证

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose -f compose.test.yaml up -d --wait
pytest -q
cd gateway
go test -race ./...
go build -o /tmp/xapis-gateway .
cd ..
```

本地 Go 网关：

```bash
X_GATEWAY_TOKEN_FILE=./data/gateway.token /tmp/xapis-gateway
```

另一个终端，从仓库根目录启动 Web：

```bash
CONSOLE_DATA_DIR=./data \
CONSOLE_DB_HOST=127.0.0.1 CONSOLE_DB_PORT=3306 \
CONSOLE_DB_NAME=xapis CONSOLE_DB_USER=xapis \
CONSOLE_DB_PASSWORD_FILE=/安全路径/mysql-password \
X_GATEWAY_URL=http://127.0.0.1:8090 \
X_GATEWAY_TOKEN_FILE=./data/gateway.token \
uvicorn console.app:create_app --factory --host 127.0.0.1 --port 8000 --workers 1
```

需要 Node.js 22+ 执行原 SDK 的 Castle runner，Go 网关使用 Go 1.27。前端无需 Node 构建或 CDN，修改静态资源后刷新页面即可。

测试使用单独的 MySQL 8.4 数据库（`xapis_test`，3307 端口）、模拟 X/AI 响应，以及本地受信任测试证书和 CONNECT 代理，验证鉴权、代理路由、TLS 握手、Cookie 传递、来源去重、自动化、发布状态机和失败恢复；不会向真实 X 账号发布测试内容。真实账号登录、X 权限与代理出口可用性需使用部署者自己的凭据验证。

### 旧 SQLite 数据迁移

保留旧 `console-data` 目录中的 `encryption.key`，在新 MySQL 空库配置下执行：

```bash
python -m console.manage migrate-sqlite --source /旧数据目录/console.sqlite3
```

工具只读旧文件，不删除旧数据，目标库已有用户时拒绝覆盖。旧版已连接账号在迁移时开始新的四天保护期；原会话和草稿会保留。完成后重启 Web。

### 保留本次预览地址

需要同时保留本地 `8765` 入口时：

```bash
docker compose -f compose.yaml -f compose.local.yaml up -d --build --wait
```

此时 `http://localhost:8000` 和 `http://localhost:8765` 访问同一个 Docker 工作台。已有预览数据可通过上文的 MySQL 备份/恢复命令迁移，账号养护起点、发布台账和登录会话会保留。新部署仍通过初始化页面创建管理员，不包含任何预置账号密码。

## X Chat 私信

私信页可保存已经在 X Chat 设置的聊天密码，密码与 Cookie 一样使用部署密钥加密后存入 MySQL。状态接口只返回是否已保存；点击解锁时，受登录和 CSRF 保护的接口把密码交给当前页面的独立 Worker，用于恢复聊天密钥。控制台不创建或重置 X 的聊天密码。保存或清除操作仅修改本地保存值。

恢复请求经 Go 网关和账号绑定代理访问 X 的密钥服务器；后端校验服务器地址、会话版本、时效和请求大小，并使用 X 签发的对应服务器授权。密码错误会显示剩余机会，不自动重试。浏览器 CSP 禁止直接请求外网。私钥仅留在 Worker 内存，离开私信页、切换账号、退出登录后销毁；普通接口和日志不返回密码、令牌或私钥。

解锁后可读取收件箱、加载更多会话、查看历史消息，输入 X 用户名打开会话。页面可见、已解锁且未编辑消息时，每 30 秒刷新。发送文字在浏览器内加密并签名，后端只接收密文，使用 `SendMessageCreateMutation` 网页接口发送。新的一对一会话使用 `AddEncryptedConversationKeysMutation` 提交加密会话密钥；已有会话禁止覆盖密钥。发送结果需通过返回事件的解密和签名验证，才能显示确认。

养护期禁止发送私信和建立新会话密钥，但允许读取。发送请求 ID 和结果状态持久化到 MySQL，用于阻止重复提交；不保存消息明文、密文或恢复私钥。超时和结果不明时不自动重发，先在 X 核对。审计日志仅记录保存密码、密钥提交和发送阶段的结果，不记录消息内容。媒体附件暂显示为占位提示，当前发送界面仅支持文字；消息请求审批及群成员管理仍需在 X 完成。

浏览器加密组件固定在 `frontend/vendor/README.md` 记录的官方源码版本。开发环境先运行 `npm ci --prefix frontend --ignore-scripts` 和 `npm run build --prefix frontend`；Docker 构建自动完成。测试：`node --test tests/test_chat_crypto.mjs`，以及测试 MySQL 环境中的 `pytest tests/test_chat.py`。
