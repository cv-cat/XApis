"""Isolated UI fixture, never imported by production. No real X/AI requests."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import time
import tempfile

if os.getenv("CONSOLE_DB_NAME") != "xapis_ui_fixture":
    raise SystemExit(
        "UI fixture requires an isolated MySQL database named xapis_ui_fixture"
    )
from console.app import create_app
from console.store import uid, encode
from console.security import password_hash
from console.content import Content
from console import xbridge as X
from x_apis.x_api import XAPI
from x_apis.x_write_api import XWriteAPI
from x_apis.x_article_api import XArticleAPI

app = create_app(tempfile.mkdtemp(prefix="xapis-browser-fixture-"))
store = app.state.store
owner, account, source, entry = uid(), uid(), uid(), uid()
store.run(
    "INSERT INTO users(id,username,password,role,created) VALUES(?,?,?,?,?)",
    (owner, "ui-review", password_hash("Only-UI-test-2026!"), "admin", time.time()),
)
store.run(
    "INSERT INTO accounts(id,owner,x_id,handle,name,secret,status,created) VALUES(?,?,?,?,?,?,?,?)",
    (
        account,
        owner,
        "123",
        "fixture",
        "界面测试账号",
        store.encrypt(
            {
                "proxy": "http://fixture-proxy:8080",
                "cookies": "auth_token=fixture; ct0=fixture; twid=u%3D123",
            }
        ),
        "connected",
        time.time(),
    ),
)
policy_id = uid()
store.run(
    "INSERT INTO account_policies VALUES(?,?,?,?,?,?)",
    (
        policy_id,
        owner,
        "123",
        time.time() - 8 * 86400,
        time.time() - 4 * 86400,
        time.time() - 86400,
    ),
)
store.run("UPDATE accounts SET policy_id=? WHERE id=?", (policy_id, account))
store.run(
    "INSERT INTO ai_settings VALUES(?,?,?,?,?)",
    (
        owner,
        "https://ai.example/v1",
        "fixture-model",
        store.encrypt({"api_key": "fixture"}),
        "中文",
    ),
)
store.run(
    "INSERT INTO sources(id,owner,name,url,kind,created) VALUES(?,?,?,?,?,?)",
    (source, owner, "测试资讯源", "https://news.example/feed", "rss", time.time()),
)
store.run(
    "INSERT INTO entries(id,source_id,title,url,summary,published,fetched) VALUES(?,?,?,?,?,?,?)",
    (
        entry,
        source,
        "[测试] AI 产品发布动态",
        "https://news.example/item",
        "此内容仅用于界面验证。",
        time.time(),
        time.time(),
    ),
)


def user():
    return {
        "__typename": "User",
        "rest_id": "123",
        "core": {"name": "界面测试账号", "screen_name": "fixture"},
        "legacy": {
            "description": "仅用于界面验收，不是真实 X 数据",
            "followers_count": 0,
            "friends_count": 0,
        },
    }


def timeline(*args, **kwargs):
    items = []
    for i, text in enumerate(
        [
            "[测试] 这是一条用于检查时间线排版的示例，包含中文、英文 AI 和换行。\n所有数据来自隔离测试环境。",
            "[测试] 从资讯来源到 AI 草稿，再到定时发布。测试账户不会向真实 X 发出请求。",
        ]
    ):
        items.append(
            {
                "content": {
                    "itemContent": {
                        "tweet_results": {
                            "result": {
                                "__typename": "Tweet",
                                "rest_id": str(101 + i),
                                "core": {"user_results": {"result": user()}},
                                "legacy": {
                                    "full_text": text,
                                    "created_at": "Fri Oct 23 12:00:00 +0000 2026",
                                    "favorite_count": 0,
                                    "reply_count": 0,
                                    "retweet_count": 0,
                                },
                                "views": {"count": "0"},
                            }
                        }
                    }
                }
            }
        )
    return {"data": {"entries": items}}


for name in ["get_home_timeline", "get_user_post_note", "search_work", "get_work_info"]:
    setattr(XAPI, name, staticmethod(timeline))
XAPI.get_user_info = staticmethod(
    lambda *a, **k: {"data": {"user": {"result": user()}}}
)
XAPI.get_viewer = staticmethod(
    lambda *a, **k: {"data": {"viewer": {"user_results": {"result": user()}}}}
)
for k in X.ACTIONS:
    X.ACTIONS[k] = lambda *a, **kw: {"ok": True}
counter = 1000


def publish(*a, **kw):
    global counter
    counter += 1
    return {
        "data": {
            "create_tweet": {"tweet_results": {"result": {"rest_id": str(counter)}}}
        }
    }


XWriteAPI.create_tweet = staticmethod(publish)
XWriteAPI.create_note_tweet = staticmethod(publish)
Content.generate = lambda self, *a, **kw: {
    "text": "[测试 AI 草稿] 把最新动态整理成观点，让有价值的信息更容易被理解。 https://news.example/item",
    "weight": 110,
    "sources": [{"title": "测试资料", "url": "https://news.example/item"}],
}
Content.collect = lambda *a, **kw: 1
XArticleAPI.list_articles = staticmethod(
    lambda *a, **kw: {"articles": [{"rest_id": "789", "title": "[测试] 文章草稿"}]}
)
fn, fields, label = X.READS["articles"]
X.READS["articles"] = (XArticleAPI.list_articles, fields, label)
for name in [
    "chat_inbox",
    "chat_settings",
    "chat_conversation",
    "chat_members",
    "chat_public_keys",
]:
    fn, fields, label = X.READS[name]
    X.READS[name] = (
        lambda *a, **kw: {"fixture": True, "conversations": []},
        fields,
        label,
    )
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8766, access_log=False)
