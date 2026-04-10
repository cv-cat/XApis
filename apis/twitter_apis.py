import requests
from utils.twitter_utils import get_common_headers, trans_cookies, get_search_params, get_user_profile_params, \
    get_user_posted_works, get_work_detail_params, get_work_comment_params


class Twitter_Apis():

    """
        搜索一些作品
        :json query: 搜索关键字
        :json product: 排序方式 Top Latest
        :json authorization: authorization
        :json x_csrf_token: x_csrf_token
        :json cookies_str: cookies
    """
    def search_work(self, query: str, cursor, product: str, authorization: str, x_csrf_token: str, cookies_str: str, proxies: dict = None):
        url = "https://x.com/i/api/graphql/5yhbMCF0-WQ6M8UOAs1mAg/SearchTimeline"
        success = True
        res_json = None
        msg = '成功'
        try:
            headers = get_common_headers(authorization, x_csrf_token)
            params = get_search_params(query, cursor, product)
            cookies = trans_cookies(cookies_str)
            response = requests.get(url, headers=headers, cookies=cookies, params=params, proxies=proxies)
            res_json = response.json()
        except Exception as e:
            success = False
            msg = str(e)
        return success, msg, res_json

    """
        获取作品的详细信息
        :json work_id: 作品id
        :json authorization: authorization
        :json x_csrf_token: x_csrf_token
        :json cookies_str: cookies
    """
    def get_work_info(self, work_id: str, authorization: str, x_csrf_token: str, cookies_str: str, proxies: dict = None):
        url = "https://x.com/i/api/graphql/zJvfJs3gSbrVhC0MKjt_OQ/TweetDetail"
        success = True
        res_json = None
        msg = '成功'
        try:
            headers = get_common_headers(authorization, x_csrf_token)
            params = get_work_detail_params(work_id)
            cookies = trans_cookies(cookies_str)
            response = requests.get(url, headers=headers, cookies=cookies, params=params, proxies=proxies)
            res_json = response.json()
        except Exception as e:
            success = False
            msg = str(e)
        return success, msg, res_json
    """
        获取用户的信息
        :json user_name: 用户名
        :json authorization: authorization
        :json x_csrf_token: x_csrf_token
        :json cookies_str: cookies
    """
    def get_user_info(self, user_name: str, authorization: str, x_csrf_token: str, cookies_str: str, proxies: dict = None):
        url = "https://x.com/i/api/graphql/qW5u-DAuXpMEG0zA1F7UGQ/UserByScreenName"
        success = True
        res_json = None
        msg = '成功'
        try:
            screen_name = user_name.lower()
            headers = get_common_headers(authorization, x_csrf_token)
            params = get_user_profile_params(screen_name)
            cookies = trans_cookies(cookies_str)
            response = requests.get(url, headers=headers, cookies=cookies, params=params, proxies=proxies)
            res_json = response.json()
        except Exception as e:
            success = False
            msg = str(e)
        return success, msg, res_json

    """
        获取用户的发表的作品
        :json user_id: 用户id
        :json cursor: 游标
        :json authorization: authorization
        :json x_csrf_token: x_csrf_token
        :json cookies_str: cookies
    """
    def get_user_post_note(self, user_id: str, cursor, authorization: str, x_csrf_token: str, cookies_str: str, proxies: dict = None):
        url = "https://x.com/i/api/graphql/9zyyd1hebl7oNWIPdA8HRw/UserTweets"
        success = True
        res_json = None
        msg = '成功'
        try:
            headers = get_common_headers(authorization, x_csrf_token)
            params = get_user_posted_works(user_id, cursor)
            cookies = trans_cookies(cookies_str)
            response = requests.get(url, headers=headers, cookies=cookies, params=params, proxies=proxies)
            res_json = response.json()
        except Exception as e:
            success = False
            msg = str(e)
        return success, msg, res_json

    """
        获取作品的评论
        :json work_id: 作品id
        :json cursor: 游标
        :json authorization: authorization
        :json x_csrf_token: x_csrf_token
        :json cookies_str: cookies
    """
    def get_work_comments(self, work_id: str, cursor, authorization: str, x_csrf_token: str, cookies_str: str, proxies: dict = None):
        url = "https://x.com/i/api/graphql/zJvfJs3gSbrVhC0MKjt_OQ/TweetDetail"
        success = True
        res_json = None
        msg = '成功'
        try:
            headers = get_common_headers(authorization, x_csrf_token)
            params = get_work_comment_params(work_id, cursor)
            cookies = trans_cookies(cookies_str)
            response = requests.get(url, headers=headers, cookies=cookies, params=params, proxies=proxies)
            res_json = response.json()
        except Exception as e:
            success = False
            msg = str(e)
        return success, msg, res_json


if __name__ == '__main__':
    twitter_apis = Twitter_Apis()
    cookie_str = r''
    authorization = r''
    x_csrf_token = r''
    cookie_str = r''
    authorization = r''
    x_csrf_token = r''
    # print('搜索作品')
    # success, msg, res_json = twitter_apis.search_work("你好", None, "Top", authorization, x_csrf_token, cookie_str)
    # print(success, msg, res_json)
    # cursor = res_json['data']['search_by_raw_query']['search_timeline']['timeline']['instructions'][0]['entries'][-1]['content']['value']
    # success, msg, res_json = twitter_apis.search_work("你好", cursor, "Top", authorization, x_csrf_token, cookie_str)
    # print(success, msg, res_json)
    #
    # print('获取用户信息')
    # success, msg, res_json = twitter_apis.get_user_info("picturesfoider", authorization, x_csrf_token, cookie_str)
    # print(success, msg, res_json)

    # print('获取作品信息')
    # success, msg, res_json = twitter_apis.get_work_info("1790036086909010409", authorization, x_csrf_token, cookie_str)
    # print(success, msg, res_json)

    # print('获取用户的发表的作品')
    # success, msg, res_json = twitter_apis.get_user_post_note("1718802931036622848", None, authorization, x_csrf_token, cookie_str)
    # print(success, msg, res_json)
    # cursor = res_json['data']['user']['result']['timeline_v2']['timeline']['instructions'][1]['entries'][-1]['content']['value']
    # success, msg, res_json = twitter_apis.get_user_post_note("1718802931036622848", cursor, authorization, x_csrf_token, cookie_str)
    # print(success, msg, res_json)
    # print('获取用户的发表的作品OK')

    # print('获取作品的评论')
    # success, msg, res_json = twitter_apis.get_work_comments("1791153728818643334", None, authorization, x_csrf_token, cookie_str)
    # print(success, msg, res_json)
    # cursor = res_json['data']['threaded_conversation_with_injections_v2']['instructions'][0]['entries'][-1]['content']['itemContent']['value']
    # success, msg, res_json = twitter_apis.get_work_comments("1791153728818643334", cursor, authorization, x_csrf_token, cookie_str)
    # print(success, msg, res_json)

