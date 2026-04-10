<div align="center">
    <a href="https://www.python.org/">
        <img src="https://img.shields.io/badge/python-3.12%2B-blue" alt="Python 3.12+">
    </a>
    <a href="https://fastapi.tiangolo.com/">
        <img src="https://img.shields.io/badge/FastAPI-0.115%2B-009688" alt="FastAPI">
    </a>
</div>

# 🐦 Twitter / X Platform

**✨ 专业的 Twitter(X) 数据采集解决方案，支持推文搜索、用户信息、作品列表与评论抓取**

当你需要让 AI Agent 感知 Twitter(X) 内容生态——自动采集评论舆论、分析用户推文、驱动内容运营策略——第一道墙往往不是模型能力，而是**平台数据获取能力的缺失**。

本项目做的事很简单：把这道墙拆掉。

**⚠️ 严禁用于爬取用户隐私、违规商业用途！本项目仅供学习与技术研究使用，后果自负。**

## 🌟 功能特性

- 🔍 **推文搜索**
  - 支持关键字搜索推文
  - 支持 `Top`（热门）/ `Latest`（最新）排序方式
  - 支持游标翻页，获取更多结果
- 👤 **用户信息采集**
  - 通过用户名获取用户详细 Profile 数据
- 📝 **用户作品列表**
  - 获取指定用户发布的推文列表
  - 支持游标翻页，获取全部推文
- 📄 **推文详情获取**
  - 通过推文 ID 获取推文完整详情数据
- 💬 **评论采集**
  - 获取指定推文的评论列表
  - 支持游标翻页，获取更多评论
- 🚀 **高性能服务**
  - 基于 FastAPI + Uvicorn 异步服务
  - 支持 Docker 一键部署

## 🛠️ 快速开始

### ⛳ 运行环境

- Python 3.10+

### 🎯 本地安装

```bash
pip install -r requirements.txt
```

### 🚀 运行项目

```bash
python App.py
```

服务启动后访问 http://localhost:5006/docs 查看交互式 API 文档。

### 🎨 Cookie & Token 配置

在浏览器中打开 [x.com](https://x.com)，**登录账号**后按 `F12` 打开开发者工具，点击「网络」→ 找任意一个 API 请求（如搜索请求）→ 复制请求头中以下字段：

| 字段            | 说明                              |
|---------------|-----------------------------------|
| `cookie`      | 登录态 Cookie 字符串               |
| `authorization` | Bearer Token（`Bearer AAAAAAAAAAAAAAAAAAAAANRILg...`）|
| `x-csrf-token` | CSRF Token（即 Cookie 中的 `ct0` 值）|

> ⚠️ 注意：必须登录后获取的凭证才有效，缺失将导致请求失败。

## 📡 接口说明

### POST `/search_work`

搜索推文，支持关键字搜索和排序方式选择。

**请求参数**

| 字段            | 类型  | 必填 | 说明                          |
|---------------|-----|----|-------------------------------|
| query         | str | 是  | 搜索关键字                     |
| product       | str | 是  | 排序方式：`Top`（热门）或 `Latest`（最新）|
| authorization | str | 是  | Bearer Token                  |
| x_csrf_token  | str | 是  | CSRF Token                    |
| cookies_str   | str | 是  | 登录 Cookie 字符串             |

**请求示例**

```bash
curl -X POST http://localhost:5006/search_work \
  -H "Content-Type: application/json" \
  -d '{
    "query": "你好",
    "product": "Top",
    "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILg...",
    "x_csrf_token": "your_csrf_token",
    "cookies_str": "ct0=xxx; auth_token=xxx; ..."
  }'
```

**响应示例**

```json
{
  "code": 200,
  "message": "成功",
  "data": {
    "data": {
      "search_by_raw_query": {
        "search_timeline": {
          "timeline": {
            "instructions": [...]
          }
        }
      }
    }
  }
}
```

> **翻页说明**：从响应中提取游标：
> `data['data']['search_by_raw_query']['search_timeline']['timeline']['instructions'][0]['entries'][-1]['content']['value']`
> 将其作为 `cursor` 字段传入下次请求（当前接口暂未暴露 cursor 参数，可直接调用 SDK 层翻页）。

---

### POST `/get_work_info`

通过推文 ID 获取推文的完整详情数据。

**请求参数**

| 字段            | 类型  | 必填 | 说明              |
|---------------|-----|----|-------------------|
| work_id       | str | 是  | 推文 ID            |
| authorization | str | 是  | Bearer Token       |
| x_csrf_token  | str | 是  | CSRF Token         |
| cookies_str   | str | 是  | 登录 Cookie 字符串  |

**请求示例**

```bash
curl -X POST http://localhost:5006/get_work_info \
  -H "Content-Type: application/json" \
  -d '{
    "work_id": "1790036086909010409",
    "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILg...",
    "x_csrf_token": "your_csrf_token",
    "cookies_str": "ct0=xxx; auth_token=xxx; ..."
  }'
```

**响应示例**

```json
{
  "code": 200,
  "message": "成功",
  "data": {
    "data": {
      "threaded_conversation_with_injections_v2": {
        "instructions": [...]
      }
    }
  }
}
```

---

### POST `/get_user_info`

通过用户名获取用户详细 Profile 信息。

**请求参数**

| 字段            | 类型  | 必填 | 说明              |
|---------------|-----|----|-------------------|
| user_name     | str | 是  | Twitter 用户名（不含 @）|
| authorization | str | 是  | Bearer Token       |
| x_csrf_token  | str | 是  | CSRF Token         |
| cookies_str   | str | 是  | 登录 Cookie 字符串  |

**请求示例**

```bash
curl -X POST http://localhost:5006/get_user_info \
  -H "Content-Type: application/json" \
  -d '{
    "user_name": "picturesfoider",
    "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILg...",
    "x_csrf_token": "your_csrf_token",
    "cookies_str": "ct0=xxx; auth_token=xxx; ..."
  }'
```

**响应示例**

```json
{
  "code": 200,
  "message": "成功",
  "data": {
    "data": {
      "user": {
        "result": {
          "id": "VXNlcjoxNzE4ODAyOTMxMDM2NjIyODQ4",
          "rest_id": "1718802931036622848",
          "legacy": {
            "name": "用户昵称",
            "screen_name": "picturesfoider",
            "followers_count": 12345,
            "friends_count": 678
          }
        }
      }
    }
  }
}
```

---

### POST `/get_user_post_note`

获取指定用户发布的推文列表，支持翻页。

**请求参数**

| 字段            | 类型        | 必填 | 说明                        |
|---------------|-----------|----|-----------------------------|
| user_id       | str       | 是  | 用户 rest_id（由 `/get_user_info` 获取）|
| cursor        | str\|null | 否  | 翻页游标，首次请求传 `null`    |
| authorization | str       | 是  | Bearer Token                 |
| x_csrf_token  | str       | 是  | CSRF Token                   |
| cookies_str   | str       | 是  | 登录 Cookie 字符串            |

**请求示例**

```bash
curl -X POST http://localhost:5006/get_user_post_note \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "1718802931036622848",
    "cursor": null,
    "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILg...",
    "x_csrf_token": "your_csrf_token",
    "cookies_str": "ct0=xxx; auth_token=xxx; ..."
  }'
```

> **翻页说明**：从响应中提取游标：
> `data['data']['user']['result']['timeline_v2']['timeline']['instructions'][1]['entries'][-1]['content']['value']`

---

### POST `/get_work_comments`

获取指定推文的评论列表，支持翻页。

**请求参数**

| 字段            | 类型        | 必填 | 说明                         |
|---------------|-----------|----|-----------------------------|
| work_id       | str       | 是  | 推文 ID                      |
| cursor        | str\|null | 否  | 翻页游标，首次请求传 `null`    |
| authorization | str       | 是  | Bearer Token                 |
| x_csrf_token  | str       | 是  | CSRF Token                   |
| cookies_str   | str       | 是  | 登录 Cookie 字符串            |

**请求示例**

```bash
curl -X POST http://localhost:5006/get_work_comments \
  -H "Content-Type: application/json" \
  -d '{
    "work_id": "1791153728818643334",
    "cursor": null,
    "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILg...",
    "x_csrf_token": "your_csrf_token",
    "cookies_str": "ct0=xxx; auth_token=xxx; ..."
  }'
```

**响应示例**

```json
{
  "code": 200,
  "message": "成功",
  "data": {
    "data": {
      "threaded_conversation_with_injections_v2": {
        "instructions": [
          {
            "entries": [
              {
                "content": {
                  "itemContent": {
                    "tweet_results": {
                      "result": {
                        "legacy": {
                          "full_text": "评论内容",
                          "user_id_str": "用户ID"
                        }
                      }
                    }
                  }
                }
              }
            ]
          }
        ]
      }
    }
  }
}
```

> **翻页说明**：从响应中提取游标：
> `data['data']['threaded_conversation_with_injections_v2']['instructions'][0]['entries'][-1]['content']['itemContent']['value']`

## 🔗 典型调用流程

### 搜索推文并翻页

```
1. POST /search_work  (cursor=null) → 获取第一页结果及翻页游标
2. POST /search_work  (cursor=上一步游标) → 获取下一页结果
```

### 获取用户全部推文

```
1. POST /get_user_info      → 获取 user_id (rest_id)
2. POST /get_user_post_note (cursor=null) → 获取第一页推文
3. POST /get_user_post_note (cursor=上一步游标) → 继续翻页
```

### 获取推文全部评论

```
1. POST /get_work_comments (cursor=null) → 获取第一页评论
2. POST /get_work_comments (cursor=上一步游标) → 继续翻页
```

## 🐳 Docker 部署

```bash
docker build -t twitter-platform .
docker run -d -p 5006:5006 twitter-platform
```

## 🍥 日志

| 日期       | 说明                                                          |
|----------|---------------------------------------------------------------|
| 26/04/10 | 项目初始化，完成推文搜索、用户信息、作品列表、评论采集 API 封装 |

## 🤝 欢迎贡献 PR

本项目欢迎任何形式的贡献！如果你有新功能想法、Bug 修复或文档改进，欢迎提交 PR。

- Fork 本仓库并在新分支上开发
- 保持代码风格与现有代码一致
- PR 描述中请简要说明改动内容和目的
- 也欢迎通过 Issue 提出建议或报告问题

## 🧸 额外说明
1. 感谢 star⭐ 和 follow📰！不时更新
2. 作者的联系方式在主页里，有问题可以随时联系我
3. 可以关注下作者的其他项目，欢迎 PR 和 issue
4. 感谢赞助！如果此项目对您有帮助，请作者喝一杯奶茶~~ （开心一整天😊😊）
5. thank you~~~
