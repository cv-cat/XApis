# -*- coding: utf-8 -*-
"""XWriteAPI：写接口（发推 / 长推 / thread / 删除 / 点赞 / 转推 / 关注）。

写接口全是 GraphQL mutation：POST JSON body，body 里带 queryId，
且**必须**携带 XCTID —— 这也是重构前项目做不了写操作的根因。

编排型方法（`post_tweet`）返回 `(success, msg, res_json)`，
与旧 `Twitter_Apis` 和 ../Spider_XHS 创作者接口的风格一致；
单步方法直接返回 `res_json`，与 ../DouYin_Spider 的 `DouyinAPI` 一致。
"""

import time

from builder import client
from builder.header import HeaderBuilder, HeaderType
from builder.params import GraphQLOperation, Params
from utils.x_util import TWEET_WEIGHT_LIMIT, parse_tweet_id, tweet_weight
from x_apis.errors import GraphQLError

X_HOST = 'https://x.com'
API_11 = 'https://x.com/i/api/1.1'


def graphql_post(auth, operation_name: str, variables: dict,
                 referer: str = f'{X_HOST}/home', feature_overrides: dict = None,
                 toggle_overrides: dict = None) -> dict:
    """所有 mutation 型 GraphQL 写接口的统一发送路径。"""
    operation = GraphQLOperation(operation_name)
    headers = (HeaderBuilder.build(HeaderType.POST)
               .with_bearer(auth)
               .with_csrf(auth)
               .with_auth_type(auth)
               .with_client_language(auth)
               .with_xctid(auth, 'POST', operation.path())
               .set_referer(referer)
               .get())
    resp = client.post(operation.url(), headers=headers, cookies=auth.cookie,
                       json=operation.json_body(variables, feature_overrides,
                                                toggle_overrides),
                       proxies=auth.proxies, timeout=30)
    resp.raise_for_status()
    res_json = resp.json()
    if res_json.get('errors'):
        raise GraphQLError(operation_name, res_json['errors'], res_json)
    return res_json


def _rest_post(auth, api: str, data: dict) -> dict:
    """老 REST 接口（`/i/api/1.1/*`），关注之类还在用。"""
    headers = (HeaderBuilder.build(HeaderType.FORM)
               .with_bearer(auth)
               .with_csrf(auth)
               .with_auth_type(auth)
               .with_client_language(auth)
               .with_xctid(auth, 'POST', f'/i/api/1.1{api}')
               .set_referer(f'{X_HOST}/home')
               .get())
    resp = client.post(f'{API_11}{api}', headers=headers, cookies=auth.cookie,
                       data=Params().update_params(data).get(),
                       proxies=auth.proxies, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    if result.get('errors'):
        raise GraphQLError(api, result['errors'], result)
    return result


class XWriteAPI:

    # ---- 发布 ------------------------------------------------------------ #

    @staticmethod
    def _tweet_variables(text: str, media_ids=None, reply_to: str = None,
                         quote_url: str = None,
                         exclude_reply_user_ids=None) -> dict:
        """CreateTweet / CreateNoteTweet 共用的 variables。

        两个操作的 variables 逐字段相同（2026-09-27 实抓），
        区别只在操作名、queryId 和 features。
        """
        variables = {
            'tweet_text': text,
            'media': {
                'media_entities': [{'media_id': str(mid), 'tagged_users': []}
                                   for mid in (media_ids or [])],
                'possibly_sensitive': False,
            },
            'semantic_annotation_ids': [],
            'disallowed_reply_options': None,
            'semantic_annotation_options': {'source': 'UniversalLink'},
        }
        if reply_to:
            variables['reply'] = {
                'in_reply_to_tweet_id': parse_tweet_id(reply_to),
                'exclude_reply_user_ids': exclude_reply_user_ids or [],
            }
        if quote_url:
            variables['attachment_url'] = quote_url
        return variables

    @staticmethod
    def create_tweet(auth, text: str, media_ids=None, reply_to: str = None,
                     quote_url: str = None, exclude_reply_user_ids=None,
                     **kwargs) -> dict:
        """发一条推文。

        variables 逐字段对齐浏览器实抓：
        `semantic_annotation_options.source = UniversalLink` 是前端固定带的。

        :param text: 正文。
        :param media_ids: `XMediaAPI.upload` 返回的 media_id 列表。
        :param reply_to: 被回复推文 id，给出即变成回复。
        :param quote_url: 引用推文的完整链接。
        """
        variables = XWriteAPI._tweet_variables(
            text, media_ids, reply_to, quote_url, exclude_reply_user_ids)
        # 浏览器打开 compose/post 后，真正提交请求的来源仍是 /home。
        # 保持 referer 与 Chrome 实抓一致。
        return graphql_post(auth, 'CreateTweet', variables,
                            referer=f'{X_HOST}/home')

    @staticmethod
    def create_note_tweet(auth, text: str, media_ids=None, reply_to: str = None,
                          quote_url: str = None, exclude_reply_user_ids=None,
                          **kwargs) -> dict:
        """发一条长推（Premium 专属，权重 > 280）。

        网页端正文超过 280 权重时，发帖按钮提交的就不再是 CreateTweet，
        而是 CreateNoteTweet；variables 与 CreateTweet 完全一致。
        非 Premium 账号调用会被服务端拒绝。
        响应里新推文挂在 `data.notetweet_create.tweet_results`，
        `extract_tweet_id` 已兼容。
        """
        variables = XWriteAPI._tweet_variables(
            text, media_ids, reply_to, quote_url, exclude_reply_user_ids)
        return graphql_post(auth, 'CreateNoteTweet', variables,
                            referer=f'{X_HOST}/home')

    @staticmethod
    def post_tweet(auth, text: str, images=None, reply_to: str = None,
                   quote_url: str = None, note: bool = None, **kwargs):
        """发作品的编排入口：先传图，再发推。

        :param note: 是否按长推发。默认 `None` 按权重自动选：
            `tweet_weight(text) > 280` 走 CreateNoteTweet，否则 CreateTweet。
        :return: (success, msg, res_json)
        """
        try:
            from x_apis.x_media_api import XMediaAPI
            if note is None:
                note = tweet_weight(text) > TWEET_WEIGHT_LIMIT
            media_ids = XMediaAPI.upload_many(auth, images) if images else []
            create = XWriteAPI.create_note_tweet if note else XWriteAPI.create_tweet
            return True, '成功', create(
                auth, text, media_ids=media_ids, reply_to=reply_to,
                quote_url=quote_url)
        except GraphQLError as exc:
            return False, str(exc), exc.res_json
        except Exception as exc:
            return False, f'{type(exc).__name__}: {exc}', None

    @staticmethod
    def post_thread(auth, texts, images=None, reply_to: str = None,
                    interval: float = 2.0, **kwargs):
        """发一串 thread：第一条之后每条都回复上一条。

        :param texts: 每条正文。单条超过 280 权重时自动按长推发。
        :param images: 与 texts 等长的列表，每项是该条的图片路径（或路径列表 / None）。
        :param reply_to: 给出时第一条也作为回复挂在这条推文下面。
        :param interval: 两条之间的间隔秒数，太快容易触发风控。
        :return: (success, msg, tweet_ids)。中途失败时 tweet_ids 是已发出的那些。
        """
        images = list(images or [])
        tweet_ids, parent = [], reply_to
        for index, text in enumerate(texts):
            if index and interval:
                time.sleep(interval)
            success, msg, res_json = XWriteAPI.post_tweet(
                auth, text,
                images=images[index] if index < len(images) else None,
                reply_to=parent)
            if not success:
                return False, f'第 {index + 1} 条失败：{msg}', tweet_ids
            parent = XWriteAPI.extract_tweet_id(res_json)
            tweet_ids.append(parent)
        return True, '成功', tweet_ids

    @staticmethod
    def extract_tweet_id(res_json: dict) -> str:
        """从 CreateTweet 响应里取出新推文的 rest_id。"""
        data = (res_json or {}).get('data') or {}
        for key in ('create_tweet', 'notetweet_create'):
            result = ((data.get(key) or {}).get('tweet_results') or {}).get('result')
            if result:
                return result.get('rest_id') or result['legacy']['id_str']
        raise KeyError(f'响应里没有 rest_id：{res_json}')

    @staticmethod
    def delete_tweet(auth, work_id: str, **kwargs) -> dict:
        return graphql_post(auth, 'DeleteTweet',
                            # 当前网页端只提交 tweet_id；旧版的
                            # dark_request=false 会造成请求体与浏览器不一致。
                            {'tweet_id': parse_tweet_id(work_id)})

    # ---- 互动 ------------------------------------------------------------ #

    @staticmethod
    def favorite_tweet(auth, work_id: str, **kwargs) -> dict:
        return graphql_post(auth, 'FavoriteTweet',
                            {'tweet_id': parse_tweet_id(work_id)})

    @staticmethod
    def unfavorite_tweet(auth, work_id: str, **kwargs) -> dict:
        return graphql_post(auth, 'UnfavoriteTweet',
                            {'tweet_id': parse_tweet_id(work_id)})

    @staticmethod
    def create_retweet(auth, work_id: str, **kwargs) -> dict:
        return graphql_post(auth, 'CreateRetweet',
                            {'tweet_id': parse_tweet_id(work_id),
                             'dark_request': False})

    @staticmethod
    def delete_retweet(auth, work_id: str, **kwargs) -> dict:
        return graphql_post(auth, 'DeleteRetweet',
                            {'source_tweet_id': parse_tweet_id(work_id),
                             'dark_request': False})

    @staticmethod
    def create_bookmark(auth, work_id: str, **kwargs) -> dict:
        return graphql_post(auth, 'CreateBookmark',
                            {'tweet_id': parse_tweet_id(work_id)})

    @staticmethod
    def delete_bookmark(auth, work_id: str, **kwargs) -> dict:
        return graphql_post(auth, 'DeleteBookmark',
                            {'tweet_id': parse_tweet_id(work_id)})

    # ---- 关系 ------------------------------------------------------------ #

    @staticmethod
    def follow_user(auth, user_id: str, **kwargs) -> dict:
        return _rest_post(auth, '/friendships/create.json', {
            'include_profile_interstitial_type': '1',
            'include_blocking': '1',
            'include_blocked_by': '1',
            'include_followed_by': '1',
            'include_want_retweets': '1',
            'include_mute_edge': '1',
            'include_can_dm': '1',
            'include_can_media_tag': '1',
            'skip_status': '1',
            'user_id': user_id,
        })

    @staticmethod
    def unfollow_user(auth, user_id: str, **kwargs) -> dict:
        return _rest_post(auth, '/friendships/destroy.json', {
            'include_profile_interstitial_type': '1',
            'include_blocking': '1',
            'include_blocked_by': '1',
            'include_followed_by': '1',
            'include_want_retweets': '1',
            'include_mute_edge': '1',
            'include_can_dm': '1',
            'include_can_media_tag': '1',
            'skip_status': '1',
            'user_id': user_id,
        })
