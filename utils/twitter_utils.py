import requests

def get_common_headers(authorization, x_csrf_token):
    return {
        "accept": "*/*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
        "authorization": authorization,
        "content-type": "application/json",
        "priority": "u=1, i",
        "referer": "https://x.com/search?q=%E4%BD%A0%E5%A5%BD&src=typed_query&f=top",
        "sec-ch-ua": "\"Chromium\";v=\"124\", \"Microsoft Edge\";v=\"124\", \"Not-A.Brand\";v=\"99\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
        "x-csrf-token": x_csrf_token,
        "x-twitter-active-user": "yes",
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-client-language": "en"
    }

# product
# Top
# Latest
def get_search_params(query, cursor=None, product="Top"):
    if cursor is None:
        variables = "{\"rawQuery\":\"" + query + "\",\"count\":20,\"querySource\":\"typed_query\",\"product\":\"" + product + "\"}"
    else:
        variables = "{\"rawQuery\":\"" + query + "\",\"count\":20,\"cursor\":\"" + cursor + "\",\"querySource\":\"typed_query\",\"product\":\"" + product + "\"}"
    return {
        "variables": variables,
        "features": "{\"rweb_tipjar_consumption_enabled\":true,\"responsive_web_graphql_exclude_directive_enabled\":true,\"verified_phone_label_enabled\":false,\"creator_subscriptions_tweet_preview_api_enabled\":true,\"responsive_web_graphql_timeline_navigation_enabled\":true,\"responsive_web_graphql_skip_user_profile_image_extensions_enabled\":false,\"communities_web_enable_tweet_community_results_fetch\":true,\"c9s_tweet_anatomy_moderator_badge_enabled\":true,\"articles_preview_enabled\":true,\"tweetypie_unmention_optimization_enabled\":true,\"responsive_web_edit_tweet_api_enabled\":true,\"graphql_is_translatable_rweb_tweet_is_translatable_enabled\":true,\"view_counts_everywhere_api_enabled\":true,\"longform_notetweets_consumption_enabled\":true,\"responsive_web_twitter_article_tweet_consumption_enabled\":true,\"tweet_awards_web_tipping_enabled\":false,\"creator_subscriptions_quote_tweet_preview_enabled\":false,\"freedom_of_speech_not_reach_fetch_enabled\":true,\"standardized_nudges_misinfo\":true,\"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled\":true,\"tweet_with_visibility_results_prefer_gql_media_interstitial_enabled\":true,\"rweb_video_timestamps_enabled\":true,\"longform_notetweets_rich_text_read_enabled\":true,\"longform_notetweets_inline_media_enabled\":true,\"responsive_web_enhance_cards_enabled\":false}"
    }


def get_user_profile_params(screen_name):
    return {
        "variables": "{\"screen_name\":\"" + screen_name + "\",\"withSafetyModeUserFields\":true}",
        "features": "{\"hidden_profile_likes_enabled\":true,\"hidden_profile_subscriptions_enabled\":true,\"rweb_tipjar_consumption_enabled\":true,\"responsive_web_graphql_exclude_directive_enabled\":true,\"verified_phone_label_enabled\":false,\"subscriptions_verification_info_is_identity_verified_enabled\":true,\"subscriptions_verification_info_verified_since_enabled\":true,\"highlights_tweets_tab_ui_enabled\":true,\"responsive_web_twitter_article_notes_tab_enabled\":true,\"creator_subscriptions_tweet_preview_api_enabled\":true,\"responsive_web_graphql_skip_user_profile_image_extensions_enabled\":false,\"responsive_web_graphql_timeline_navigation_enabled\":true}",
        "fieldToggles": "{\"withAuxiliaryUserLabels\":false}"
    }

def get_user_posted_works(user_id, cursor=None):
    if cursor is None:
        variables = "{\"userId\":\"" + user_id + "\",\"count\":20,\"includePromotedContent\":true,\"withQuickPromoteEligibilityTweetFields\":true,\"withVoice\":true,\"withV2Timeline\":true}",
    else:
        variables = "{\"userId\":\"" + user_id + "\",\"count\":20,\"cursor\":\"" + cursor + "\",\"includePromotedContent\":true,\"withQuickPromoteEligibilityTweetFields\":true,\"withVoice\":true,\"withV2Timeline\":true}"
    return {
        "variables": variables,
        "features": "{\"rweb_tipjar_consumption_enabled\":true,\"responsive_web_graphql_exclude_directive_enabled\":true,\"verified_phone_label_enabled\":false,\"creator_subscriptions_tweet_preview_api_enabled\":true,\"responsive_web_graphql_timeline_navigation_enabled\":true,\"responsive_web_graphql_skip_user_profile_image_extensions_enabled\":false,\"communities_web_enable_tweet_community_results_fetch\":true,\"c9s_tweet_anatomy_moderator_badge_enabled\":true,\"articles_preview_enabled\":true,\"tweetypie_unmention_optimization_enabled\":true,\"responsive_web_edit_tweet_api_enabled\":true,\"graphql_is_translatable_rweb_tweet_is_translatable_enabled\":true,\"view_counts_everywhere_api_enabled\":true,\"longform_notetweets_consumption_enabled\":true,\"responsive_web_twitter_article_tweet_consumption_enabled\":true,\"tweet_awards_web_tipping_enabled\":false,\"creator_subscriptions_quote_tweet_preview_enabled\":false,\"freedom_of_speech_not_reach_fetch_enabled\":true,\"standardized_nudges_misinfo\":true,\"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled\":true,\"tweet_with_visibility_results_prefer_gql_media_interstitial_enabled\":true,\"rweb_video_timestamps_enabled\":true,\"longform_notetweets_rich_text_read_enabled\":true,\"longform_notetweets_inline_media_enabled\":true,\"responsive_web_enhance_cards_enabled\":false}",
        "fieldToggles": "{\"withArticlePlainText\":false}"
    }

def get_work_detail_params(focalTweetId):
    return  {
        "variables": "{\"focalTweetId\":\"" + focalTweetId + "\",\"with_rux_injections\":false,\"includePromotedContent\":true,\"withCommunity\":true,\"withQuickPromoteEligibilityTweetFields\":true,\"withBirdwatchNotes\":true,\"withVoice\":true,\"withV2Timeline\":true}",
        "features": "{\"rweb_tipjar_consumption_enabled\":true,\"responsive_web_graphql_exclude_directive_enabled\":true,\"verified_phone_label_enabled\":false,\"creator_subscriptions_tweet_preview_api_enabled\":true,\"responsive_web_graphql_timeline_navigation_enabled\":true,\"responsive_web_graphql_skip_user_profile_image_extensions_enabled\":false,\"communities_web_enable_tweet_community_results_fetch\":true,\"c9s_tweet_anatomy_moderator_badge_enabled\":true,\"articles_preview_enabled\":true,\"tweetypie_unmention_optimization_enabled\":true,\"responsive_web_edit_tweet_api_enabled\":true,\"graphql_is_translatable_rweb_tweet_is_translatable_enabled\":true,\"view_counts_everywhere_api_enabled\":true,\"longform_notetweets_consumption_enabled\":true,\"responsive_web_twitter_article_tweet_consumption_enabled\":true,\"tweet_awards_web_tipping_enabled\":false,\"creator_subscriptions_quote_tweet_preview_enabled\":false,\"freedom_of_speech_not_reach_fetch_enabled\":true,\"standardized_nudges_misinfo\":true,\"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled\":true,\"tweet_with_visibility_results_prefer_gql_media_interstitial_enabled\":true,\"rweb_video_timestamps_enabled\":true,\"longform_notetweets_rich_text_read_enabled\":true,\"longform_notetweets_inline_media_enabled\":true,\"responsive_web_enhance_cards_enabled\":false}",
        "fieldToggles": "{\"withArticleRichContentState\":true,\"withArticlePlainText\":false}"
    }

def get_work_comment_params(focalTweetId, cursor=None):
    if cursor is None:
        variables = "{\"focalTweetId\":\"" + focalTweetId + "\",\"with_rux_injections\":false,\"includePromotedContent\":true,\"withCommunity\":true,\"withQuickPromoteEligibilityTweetFields\":true,\"withBirdwatchNotes\":true,\"withVoice\":true,\"withV2Timeline\":true}",
    else:
        variables = "{\"focalTweetId\":\"" + focalTweetId + "\",\"cursor\":\"" + cursor + "\",\"with_rux_injections\":false,\"includePromotedContent\":true,\"withCommunity\":true,\"withQuickPromoteEligibilityTweetFields\":true,\"withBirdwatchNotes\":true,\"withVoice\":true,\"withV2Timeline\":true}"
    return {
        "variables": variables,
        "features": "{\"rweb_tipjar_consumption_enabled\":true,\"responsive_web_graphql_exclude_directive_enabled\":true,\"verified_phone_label_enabled\":false,\"creator_subscriptions_tweet_preview_api_enabled\":true,\"responsive_web_graphql_timeline_navigation_enabled\":true,\"responsive_web_graphql_skip_user_profile_image_extensions_enabled\":false,\"communities_web_enable_tweet_community_results_fetch\":true,\"c9s_tweet_anatomy_moderator_badge_enabled\":true,\"articles_preview_enabled\":true,\"tweetypie_unmention_optimization_enabled\":true,\"responsive_web_edit_tweet_api_enabled\":true,\"graphql_is_translatable_rweb_tweet_is_translatable_enabled\":true,\"view_counts_everywhere_api_enabled\":true,\"longform_notetweets_consumption_enabled\":true,\"responsive_web_twitter_article_tweet_consumption_enabled\":true,\"tweet_awards_web_tipping_enabled\":false,\"creator_subscriptions_quote_tweet_preview_enabled\":false,\"freedom_of_speech_not_reach_fetch_enabled\":true,\"standardized_nudges_misinfo\":true,\"tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled\":true,\"tweet_with_visibility_results_prefer_gql_media_interstitial_enabled\":true,\"rweb_video_timestamps_enabled\":true,\"longform_notetweets_rich_text_read_enabled\":true,\"longform_notetweets_inline_media_enabled\":true,\"responsive_web_enhance_cards_enabled\":false}",
        "fieldToggles": "{\"withArticleRichContentState\":true,\"withArticlePlainText\":false}"
    }
def trans_cookies(cookies_str):
    return {i.split('=')[0]: '='.join(i.split('=')[1:]) for i in cookies_str.split('; ')}
