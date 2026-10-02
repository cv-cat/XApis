# -*- coding: utf-8 -*-
"""X 文章（Article）正文装配：Markdown -> Draft.js content_state。

文章编辑器是 Draft.js，保存时把 `content_state` 原样提交给
`ArticleEntityUpdateContent`。结构逐字段对齐 2026-09-27 Chrome 实抓::

    {
      "blocks": [{"data": {}, "text": "...", "key": "9u7ts", "type": "unstyled",
                  "entity_ranges": [{"key": 0, "offset": 43, "length": 4}],
                  "inline_style_ranges": [{"length": 4, "offset": 16, "style": "Bold"}]}],
      "entity_map": [{"key": "0", "value": {"data": {"url": "..."},
                                            "type": "LINK", "mutability": "Mutable"}}]
    }

注意三处和 Draft.js 默认 `convertToRaw` 不一样：键名是 snake_case
（`entity_ranges` / `inline_style_ranges` / `entity_map`）、`entity_map` 是
`[{key, value}]` 数组而不是对象、样式名是 `Bold` / `Italic` / `Strikethrough`。

offset / length 按 **Unicode 码点**计，不是 JS 字符串的 UTF-16 下标：
编辑器保存时会做转换（实抓 `一、行内样式E👍👨‍👩‍👧BOLD` 里 BOLD 的 offset 是 13，
JS 下标是 17）。按 UTF-16 算的话 emoji 之后的样式会整体错位。
Python 的 `len()` 正好就是码点数。

支持的 Markdown 子集（每个非空行是一个块，空行只做分隔）：

=====================  ==========================================
``# 标题``              header-one（编辑器里的「标题」）
``## 小标题`` / ``###``  header-two（「副标题」）
``- 项`` / ``* 项``      unordered-list-item
``1. 项``               ordered-list-item
``> 引用``              blockquote
``---``                 DIVIDER 分割线
``![](a.png)``          MEDIA 图片（独占一行）
``https://x.com/u/status/1``  TWEET 嵌入帖子（链接独占一行）
```` ```lang ... ``` ```` MARKDOWN 代码块
``**粗**`` ``*斜*`` ``~~删~~`` ``[文字](链接)``  行内样式 / 链接
=====================  ==========================================
"""

import os
import random
import re
import string
import uuid

MEDIA_CATEGORY = 'DraftTweetImage'

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*)$')
_UL_RE = re.compile(r'^[-*+]\s+(.*)$')
_OL_RE = re.compile(r'^\d+[.)]\s+(.*)$')
_QUOTE_RE = re.compile(r'^>\s?(.*)$')
_DIVIDER_RE = re.compile(r'^(?:-{3,}|\*{3,}|_{3,})$')
_IMAGE_RE = re.compile(r'^!\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)$')
_TWEET_RE = re.compile(r'^<?https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/[^/\s]+/status/(\d+)[^\s>]*>?$')
_FENCE_RE = re.compile(r'^(`{3,}|~{3,})(.*)$')

# 行内记号：顺序即优先级。** 必须排在 * 前面。
# 粗体内部允许出现完整的 *斜体* 和转义字符，这样 `**粗 *斜***` 能正确闭合。
_ESC = r'\\[\\`*_~\[\]()!#>-]'
_ITALIC_BODY = r'[^*\s](?:(?:' + _ESC + r'|[^*\\])*?[^*\s\\])?'
_INLINE_RE = re.compile(
    r'\\(?P<esc>[\\`*_~\[\]()!#>-])'
    r'|\*\*(?P<bold>(?:' + _ESC + r'|\*' + _ITALIC_BODY + r'\*|[^*\\])+?)\*\*'
    r'|~~(?P<strike>.+?)~~'
    r'|\*(?P<italic>' + _ITALIC_BODY + r')\*'
    r'|\[(?P<ltext>[^\]]+)\]\((?P<lurl>[^)\s]+)\)'
)
_STYLE_BY_GROUP = {'bold': 'Bold', 'italic': 'Italic', 'strike': 'Strikethrough'}


def gen_block_key() -> str:
    """Draft.js genKey：5 位 base36 随机串。"""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=5))


class ContentStateBuilder:
    """逐块拼 content_state；Markdown 转换和手工拼装共用。"""

    def __init__(self):
        self.blocks = []
        self.entity_map = []
        self._media_seq = 0

    # ---- 实体 ----------------------------------------------------------- #

    def add_entity(self, entity_type: str, data: dict,
                   mutability: str = 'Immutable') -> int:
        key = len(self.entity_map)
        self.entity_map.append({'key': str(key), 'value': {
            'data': data, 'type': entity_type, 'mutability': mutability}})
        return key

    # ---- 块 ------------------------------------------------------------- #

    def add_text(self, text: str, block_type: str = 'unstyled',
                 inline_style_ranges=None, entity_ranges=None):
        self.blocks.append({
            'data': {},
            'text': text,
            'key': gen_block_key(),
            'type': block_type,
            'entity_ranges': entity_ranges or [],
            'inline_style_ranges': inline_style_ranges or [],
        })
        return self

    def add_markdown_text(self, source: str, block_type: str = 'unstyled'):
        """带行内 Markdown 记号的一段文字。"""
        text, styles, links = parse_inline(source)
        entity_ranges = [{'key': self.add_entity('LINK', {'url': url}, 'Mutable'),
                          'offset': offset, 'length': length}
                         for offset, length, url in links]
        return self.add_text(text, block_type, styles, entity_ranges)

    def _add_atomic(self, entity_key: int):
        # atomic 块的文本固定是一个空格，实体挂在这个空格上
        return self.add_text(' ', 'atomic', entity_ranges=[
            {'key': entity_key, 'offset': 0, 'length': 1}])

    def add_divider(self):
        return self._add_atomic(self.add_entity('DIVIDER', {}))

    def add_media(self, media_ids):
        """插图 / 图集。一个 MEDIA 块最多 4 张图（编辑器限制）。"""
        if isinstance(media_ids, (str, int)):
            media_ids = [media_ids]
        items = []
        for media_id in media_ids:
            self._media_seq += 1
            items.append({'local_media_id': self._media_seq,
                          'media_category': MEDIA_CATEGORY,
                          'media_id': str(media_id)})
        return self._add_atomic(self.add_entity('MEDIA', {
            'entity_key': str(uuid.uuid4()), 'media_items': items}))

    def add_tweet(self, tweet_id):
        """嵌入帖子：编辑器「插入 → 帖子」存成 TWEET 实体，只带 tweet_id（读接口返回的是驼峰 tweetId）。"""
        return self._add_atomic(self.add_entity(
            'TWEET', {'tweet_id': str(tweet_id)}, 'Immutable'))

    def add_code(self, code: str, language: str = ''):
        """代码块：编辑器「插入 → 代码」存成 MARKDOWN 实体，内容是整段围栏。"""
        fence = f'```{language}\n{code}\n```'
        return self._add_atomic(self.add_entity(
            'MARKDOWN', {'markdown': fence}, 'Mutable'))

    def build(self) -> dict:
        return {'blocks': self.blocks, 'entity_map': self.entity_map}


def parse_inline(source: str, base_styles: tuple = ()):
    """解析行内记号，返回 (纯文本, inline_style_ranges, [(offset, length, url)])。

    支持嵌套（`**粗体里的 [链接](u)**`），offset 按码点计。
    """
    out, styles, links = [], [], []
    cursor = 0

    def emit(text, active):
        if not text:
            return
        offset = len(''.join(out))
        length = len(text)
        out.append(text)
        for style in active:
            styles.append({'length': length, 'offset': offset, 'style': style})

    for match in _INLINE_RE.finditer(source):
        emit(source[cursor:match.start()], base_styles)
        cursor = match.end()
        group = match.lastgroup
        if group == 'esc':
            emit(match.group('esc'), base_styles)
        elif group in _STYLE_BY_GROUP:
            inner_text, inner_styles, inner_links = parse_inline(
                match.group(group), base_styles + (_STYLE_BY_GROUP[group],))
            _merge(out, styles, links, inner_text, inner_styles, inner_links)
        elif group in ('ltext', 'lurl'):
            inner_text, inner_styles, inner_links = parse_inline(
                match.group('ltext'), base_styles)
            offset = len(''.join(out))
            _merge(out, styles, links, inner_text, inner_styles, inner_links)
            links.append((offset, len(inner_text), match.group('lurl')))
    emit(source[cursor:], base_styles)
    return ''.join(out), _merge_adjacent(styles), links


def _merge_adjacent(styles: list) -> list:
    """同一样式首尾相接的区间合并成一段（编辑器也是这样保存的）。"""
    merged = []
    for item in sorted(styles, key=lambda s: (s['style'], s['offset'])):
        last = merged[-1] if merged else None
        if last and last['style'] == item['style'] \
                and last['offset'] + last['length'] >= item['offset']:
            end = max(last['offset'] + last['length'], item['offset'] + item['length'])
            last['length'] = end - last['offset']
        else:
            merged.append(dict(item))
    return sorted(merged, key=lambda s: (s['offset'], s['style']))


def _merge(out, styles, links, text, inner_styles, inner_links):
    base = len(''.join(out))
    out.append(text)
    styles.extend({**s, 'offset': s['offset'] + base} for s in inner_styles)
    links.extend((o + base, n, u) for o, n, u in inner_links)


def markdown_to_content_state(markdown: str, upload_image=None,
                              base_dir: str = None) -> dict:
    """Markdown -> content_state。

    :param upload_image: 回调 `(path) -> media_id`，遇到 `![](path)` 时调用。
        不给时遇到图片直接报错，避免静默丢图。
    :param base_dir: 图片相对路径的基准目录（一般是 md 文件所在目录）。
    """
    builder = ContentStateBuilder()
    lines = (markdown or '').replace('\r\n', '\n').split('\n')
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        index += 1
        stripped = line.strip()
        if not stripped:
            continue

        fence = _FENCE_RE.match(stripped)
        if fence:
            marker, language = fence.group(1), fence.group(2).strip()
            code = []
            while index < len(lines) and not lines[index].strip().startswith(marker):
                code.append(lines[index])
                index += 1
            index += 1  # 跳过收尾围栏
            builder.add_code('\n'.join(code), language)
            continue

        if _DIVIDER_RE.match(stripped):
            builder.add_divider()
            continue

        tweet = _TWEET_RE.match(stripped)
        if tweet:
            builder.add_tweet(tweet.group(1))
            continue

        image = _IMAGE_RE.match(stripped)
        if image:
            if upload_image is None:
                raise ValueError(f'正文里有图片 {image.group(2)}，但没有提供 upload_image')
            path = image.group(2)
            if base_dir and not os.path.isabs(path):
                path = os.path.join(base_dir, path)
            builder.add_media(upload_image(path))
            continue

        heading = _HEADING_RE.match(stripped)
        if heading:
            block_type = 'header-one' if len(heading.group(1)) == 1 else 'header-two'
            builder.add_markdown_text(heading.group(2).strip(), block_type)
            continue

        for regex, block_type in ((_UL_RE, 'unordered-list-item'),
                                  (_OL_RE, 'ordered-list-item'),
                                  (_QUOTE_RE, 'blockquote')):
            item = regex.match(stripped)
            if item:
                builder.add_markdown_text(item.group(1).strip(), block_type)
                break
        else:
            builder.add_markdown_text(stripped)
    return builder.build()


def split_title(markdown: str):
    """若正文第一行是 `# 标题`，拆出来当文章标题，返回 (title, 剩余正文)。

    文章标题在编辑器里是单独字段，正文里再放一个一级标题会重复显示。
    """
    lines = (markdown or '').lstrip('\n').split('\n')
    if lines:
        match = re.match(r'^#\s+(.*)$', lines[0].strip())
        if match:
            return match.group(1).strip(), '\n'.join(lines[1:])
    return None, markdown
