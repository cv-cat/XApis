# 登录流程对照与故障排查

本文记录登录接口结构与排查方法。原始抓包可能包含凭据和会话数据，不能提交到仓库或打入 Docker 镜像；HAR、环境文件、数据库和运行密钥均有独立的忽略规则。

## 已观察到的接口流程

| 步骤 | 请求 | 状态 | 观察 |
| --- | --- | --- | --- |
| 1 | GET `x.com/i/jf/onboarding/web?redirect_after_login=…&mode=login` | 200 | 登录入口，下发 ct0 |
| 2 | GET `jf.x.com/onboarding/web?redirect_after_login=…&mode=login` | 200 | 登录视图，响应提供 begin_login 等下一步操作 |
| 3 | GET `jf.x.com/onboarding/web/remotes/passkey_one_fa` | 200 | 无 form_id 查询参数 |
| 4 | POST `jf.x.com/onboarding/web/actions/begin_login` | 200 | 表单字段为 username_or_email、空 password、$castle_token |
| 5 | POST `…/finish_verification` | 200 | 该次流程进入验证码验证，下一步为年龄验证/注册 |
| 6 | POST `…/verify_age` | 200 | 注册分支，非现有账号密码验证 |
| 7 | POST `…/verify_signup` | 200 | 注册资料验证 |
| 8 | POST `…/signup` | 200 | 下发 auth_token 和 twid |
| 9 | GET `…/post_signup` | 200 | 注册后引导 |

HAR 中还有 follow_topic 等注册后操作。它们不应被登录功能自动重放，账号养护也禁止这些写操作。

## 与原 SDK 的差异和处理

- 原 SDK 的登录视图为 `/onboarding/web/landing`，已对齐为 `/onboarding/web?…&mode=login`。
- 初始 HTML 入口对齐为 `/i/jf/onboarding/web`，以接收该页面的会话 Cookie。
- `passkey_one_fa` 去掉抓包中不存在的 `form_id=landing` 参数。
- `begin_login` 显式发送空 `password` 字段；真正的密码仍只在服务器要求的密码验证步骤提交。
- JP-5、form-urlencoded、Origin、Referer 根路径及 same-site fetch 语义与抓包一致。
- 抓包浏览器是 macOS Chrome 156，原 SDK 的 Castle/UA 画像是 Windows Chrome 153，传输 profile 是 Chrome 150。没有仅凭这一个注册分支抓包就改写全部设备签名素材，也不宣称三者完全一致。
- 抓包没有覆盖完整的“现有账号 → login_enter_password → 登录成功”分支，因此该分支需要结合实际响应日志验证。验证码、2FA、设备证明仍由用户在 X 完成，或使用合法的现有 Cookie 导入。

## 排查日志

账号页面提供“测试代理”和“登录日志”。日志记录：阶段、请求方法、去除查询值的路径、HTTP 状态、耗时、请求字段名、选定响应头、脱敏后的真实响应文本，以及本地异常类型与调用位置。

密码、代理认证、Cookie 值、验证码、登录令牌和长随机凭据会脱敏；不记录请求字段值。HTTP 200 也会保留脱敏响应，以排查 X 将错误放在成功状态码响应体中的情况。

## 代理协议不匹配的排查

如果代理端口实际提供 SOCKS5，却配置成 HTTP，HTTP CONNECT 可能一直超时。使用账号页的“测试代理”检查所选协议和认证信息。代理测试成功只证明通路可用，不代表账号身份验证已成功。

## CSRF Cookie 与请求头不匹配

Viewer 验证可能返回 HTTP 403 / X code 353：`This request requires a matching csrf cookie and header.`

原因是 SDK 初始化公开签名素材时，匿名访问 `/i/flow/login`。该响应会下发过期的空 `ct0`；此前账号 Cookie 同步回调也被传入了这个匿名请求，清除了导入会话的 ct0，但 CSRF 请求头仍保留原值。

修复：公开签名素材请求不继承账号 Cookie 写回回调；签名生成后再次从最终会话状态装配 CSRF 头。相应回归测试模拟了匿名页面清除 ct0 的响应，并校验账号 Cookie 与请求头保持一致。控制台还将公开素材的尝试次数限制为两次，之后使用原 SDK 已有的缓存回退，以避免重复加载旧版登录素材。

成功登录必须由 Viewer 返回有效且与绑定账号一致的身份，再将账号标记为 connected 并创建保护策略。自己的贴文为空时显示空状态；响应中的推荐关注卡片不会当作用户贴文展示。
