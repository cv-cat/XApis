import uvicorn
from apis.twitter_apis import Twitter_Apis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

apis = Twitter_Apis()
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


"""
    搜索一些作品
    :json query: 搜索关键字
    :json product: 排序方式 Top Latest
    :json authorization: authorization
    :json x_csrf_token: x_csrf_token
    :json cookies_str: cookies
"""
@app.post("/search_work")
def search_work(data: dict):
    try:
        query = data["query"]
        token = data["product"]
        authorization = data["authorization"]
        x_csrf_token = data["x_csrf_token"]
        cookies_str = data["cookies_str"]
        success, msg, res_json = apis.search_work(query, token, authorization, x_csrf_token, cookies_str)
        if success:
            return {"code": 200, "message": msg, "data": res_json}
        else:
            return {"code": 400, "message": msg, "data": None}
    except Exception as e:
        return {"code": 400, "message": str(e), "data": None}

"""
    获取作品的详细信息
    :json work_id: 作品id
    :json authorization: authorization
    :json x_csrf_token: x_csrf_token
    :json cookies_str: cookies
"""
@app.post("/get_work_info")
def get_work_info(data: dict):
    try:
        work_id = data["work_id"]
        authorization = data["authorization"]
        x_csrf_token = data["x_csrf_token"]
        cookies_str = data["cookies_str"]
        success, msg, res_json = apis.get_work_info(work_id, authorization, x_csrf_token, cookies_str)
        if success:
            return {"code": 200, "message": msg, "data": res_json}
        else:
            return {"code": 400, "message": msg, "data": None}
    except Exception as e:
        return {"code": 400, "message": str(e), "data": None}

"""
    获取用户的信息
    :json user_name: 用户名
    :json authorization: authorization
    :json x_csrf_token: x_csrf_token
    :json cookies_str: cookies
"""
@app.post("/get_user_info")
def get_user_info(data: dict):
    try:
        url = data["user_name"]
        authorization = data["authorization"]
        x_csrf_token = data["x_csrf_token"]
        cookies_str = data["cookies_str"]
        success, msg, res = apis.get_user_info(url, authorization, x_csrf_token, cookies_str)
        if success:
            return {"code": 200, "message": msg, "data": res}
        else:
            return {"code": 400, "message": msg, "data": None}
    except Exception as e:
        return {"code": 400, "message": str(e), "data": None}

"""
    获取用户的发表的作品
    :json user_id: 用户id
    :json cursor: 游标
    :json authorization: authorization
    :json x_csrf_token: x_csrf_token
    :json cookies_str: cookies
"""
@app.post("/get_user_post_note")
def get_user_post_note(data: dict):
    try:
        user_id = data["user_id"]
        cursor = data["cursor"]
        authorization = data["authorization"]
        x_csrf_token = data["x_csrf_token"]
        cookies_str = data["cookies_str"]
        success, msg, res = apis.get_user_post_note(user_id, cursor, authorization, x_csrf_token, cookies_str)
        if success:
            return {"code": 200, "message": msg, "data": res}
        else:
            return {"code": 400, "message": msg, "data": None}
    except Exception as e:
        return {"code": 400, "message": str(e), "data": None}


"""
    获取作品的评论
    :json work_id: 作品id
    :json cursor: 游标
    :json authorization: authorization
    :json x_csrf_token: x_csrf_token
    :json cookies_str: cookies
"""
@app.post("/get_work_comments")
def get_work_comments(data: dict):
    try:
        work_id = data["work_id"]
        cursor = data["cursor"]
        authorization = data["authorization"]
        x_csrf_token = data["x_csrf_token"]
        cookies_str = data["cookies_str"]
        success, msg, res = apis.get_work_comments(work_id, cursor, authorization, x_csrf_token, cookies_str)
        if success:
            return {"code": 200, "message": msg, "data": res}
        else:
            return {"code": 400, "message": msg, "data": None}
    except Exception as e:
        return {"code": 400, "message": str(e), "data": None}
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5006, forwarded_allow_ips='*')
