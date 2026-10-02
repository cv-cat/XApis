<div align="center">
  <a href="https://github.com/cv-cat/XApis">
    <img width="180" src="./assets/xapis-logo.png" alt="XApis logo">
  </a>

  <h1>🐦 XApis</h1>
  <p>纯 Python 的 X (Twitter) 登录、搜索、读写与媒体接口库</p>

  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://github.com/lexiforest/curl_cffi"><img src="https://img.shields.io/badge/curl__cffi-browser--like-0F172A" alt="curl_cffi"></a>
</div>

> 仅供学习、研究和经过授权的自动化使用。请遵守 X 服务条款与当地法律，勿用于隐私抓取、批量骚扰或违规发布。

## ✨ 能力

- 纯 Python 账密登录，Castle / XCTID 本地计算，不依赖浏览器自动化。
- 登录成功后自动持久化 cookie；默认复用有效 cookie，`--force` 可强制重登。
- 搜索、作品详情、评论、用户信息、时间线、发帖、回复、删除、点赞、转推、关注。
- Premium 长推（CreateNoteTweet，按权重自动切换）、Thread、文章（Markdown 一键建草稿 / 发布）。
- 图片、多图片和视频上传；X Chat 私信读取链路已封装。
- 直接调用 Python SDK，也可以使用 `main.py` CLI。

## 🚀 快速开始

```bash
git clone https://github.com/cv-cat/XApis.git
cd XApis
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env       # macOS / Linux 使用 cp .env.example .env
```

在 `.env` 中填写：

```dotenv
X_USERNAME=''
X_PASSWORD=''
X_PROXY=''
CASTLE_PURE_RL_FILE='castle_profile.json'
```

`castle_profile.json` 是同一登录页采集的完整 Castle Rl/profile。然后直接运行：

```bash
python quickstart.py
```

脚本会纯 Python 登录、把 cookie 写回 `.env`，再搜索“美国”并打印结果。修改
`quickstart.py` 顶部的 `SEARCH_QUERY` / `SEARCH_PRODUCT` 可切换搜索内容。

已有本地 cookie 时，也可以使用 CLI：

```bash
python main.py login                         # 有效 cookie 直接复用
python main.py login --force --pure-only \
  --pure-rl castle_profile.json               # 强制纯算重登
python main.py search "美国" --product Latest
```

### ✍️ 长推 / Thread / 文章（Premium）

```bash
python main.py post --file long.txt           # 超过 280 权重自动走长推 CreateNoteTweet
python main.py thread --file thread.md        # 单独一行 --- 分隔每条，逐条回复上一条
python main.py article article.md --cover banner.png            # 只存草稿，网页上预览
python main.py article article.md --cover banner.png --publish \
  --caption "发布时附带的推文" --reply-mode Verified              # 直接发布
python main.py article-list [--published]
python main.py article-delete <文章id>
```

文章正文用 Markdown 写，第一行 `# 标题` 会被拆成文章标题；支持 `#` / `##` 标题、
`**粗体**` `*斜体*` `~~删除线~~` `[链接](url)`、有序 / 无序列表、`>` 引用、
`---` 分割线、独占一行的 `![](图片路径)`、```` ``` ```` 代码块，
以及独占一行的帖子链接（`https://x.com/用户/status/ID`，会变成嵌入帖子卡片）。
封面建议 5:2。

## 🐍 SDK

```python
from utils.common_util import load_env
from x_apis.x_api import XAPI
from x_apis.x_write_api import XWriteAPI

auth = load_env()
result = XAPI.search_work(auth, "python", product="Latest")

ok, message, raw = XWriteAPI.post_tweet(auth, "hello from XApis")
print(ok, message)

# 长推：超过 280 权重自动走 CreateNoteTweet（也可 note=True 强制）
ok, message, raw = XWriteAPI.post_tweet(auth, long_text)
ok, message, tweet_ids = XWriteAPI.post_thread(auth, ["第一条", "第二条", "第三条"])

# 文章：Markdown -> 草稿（publish=True 直接发布）
from x_apis.x_article_api import XArticleAPI
ok, message, info = XArticleAPI.post_article(
    auth, open("article.md", encoding="utf-8").read(),
    cover="banner.png", base_dir=".", publish=False)
print(info["edit_url"])
```

## 📁 结构

```text
quickstart.py            纯 Python 账密登录并搜索
main.py                  CLI 入口
builder/                 请求、鉴权和 GraphQL 参数
x_apis/                  登录、读写、媒体与 X Chat 接口
utils/                   XCTID/Castle 纯算与数据处理
static/                  GraphQL 注册表和运行时素材
assets/xapis-logo.png    项目 logo
```

## 📈 Star History

<a href="https://github.com/cv-cat/XApis">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://cvcat.site/star-history/svg?repos=cv-cat/XApis&type=Date&theme=dark">
    <source media="(prefers-color-scheme: light)" srcset="https://cvcat.site/star-history/svg?repos=cv-cat/XApis&type=Date">
    <img alt="Star History Chart" src="https://cvcat.site/star-history/svg?repos=cv-cat/XApis&type=Date">
  </picture>
</a>

## 🍔 交流群

如果你对爬虫和 AI Agent 感兴趣，可以加入群聊一起讨论~

二维码可能会过期或满员，失效时请通过 Issue、微信或 QQ 提醒。第 4 个二维码为 2000 人 QQ 群。

<div align="center">
  <img width="220" src="https://cvcat.site/assets/group1.jpg" alt="交流群二维码 1">
  <img width="220" src="https://cvcat.site/assets/group2.jpg" alt="交流群二维码 2">
  <img width="220" src="https://cvcat.site/assets/group3.jpg" alt="交流群二维码 3">
  <img width="220" src="https://cvcat.site/assets/group4.jpg" alt="交流群二维码 4">
</div>

## 🤝 贡献

欢迎提交 Issue 或 PR。涉及请求字段、签名和加密链路的改动，请附上可复现的验证说明。

⭐ 如果项目对你有帮助，欢迎 Star。
