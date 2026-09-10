# my_ai_app/data/agent_tools/web_search/implementation.py
# 网络搜索工具包实现（纯链接生成版）。
#
# 设计取舍：不做真实检索（DuckDuckGo Instant Answer 对中文/语句型查询零命中，
# 博查等搜索API又需要key），只按查询词生成各引擎的搜索结果页链接——
# 用户点击即在浏览器打开对应引擎对原问题的搜索页，自行查阅。
# 零网络请求、零依赖、响应毫秒级。
#
# 元数据（工具Schema/入口函数/版本）见同目录 manifest.json，
# 由 tool_registry 扫描、tool_loader 首次调用时按需导入，勿在其他位置直接 import。
from typing import List, Dict
from urllib.parse import quote_plus

# 兜底链接固定标题：has_real_results 用它识别"没有真实检索结果"的情况
FALLBACK_LINK_TITLES = {'Google搜索', '百度搜索', '必应搜索'}


def build_search_links(query: str) -> List[Dict[str, str]]:
    """按查询词生成各搜索引擎的结果页链接"""
    encoded = quote_plus(query)
    return [
        {
            'title': 'Google搜索',
            'snippet': f'在Google上搜索"{query}"的解决方法',
            'link': f'https://www.google.com/search?q={encoded}'
        },
        {
            'title': '百度搜索',
            'snippet': f'在百度上搜索"{query}"的解决方法',
            'link': f'https://www.baidu.com/s?wd={encoded}'
        },
        {
            'title': '必应搜索',
            'snippet': f'在必应上搜索"{query}"的解决方法',
            'link': f'https://www.bing.com/search?q={encoded}'
        },
    ]


def has_real_results(results) -> bool:
    """判断搜索结果里是否有真实命中（本实现只生成兜底链接，恒为 False）。

    保留该函数：Agent 的兜底流程靠它决定"结果是否喂回模型"——恒 False 意味着
    永远走兜底路径（模型已有知识回答 + 链接列表），这正是本实现的预期行为。
    """
    if not isinstance(results, list):
        return False
    for item in results:
        if isinstance(item, dict) and item.get('title') not in FALLBACK_LINK_TITLES:
            return True
    return False


def web_search(query: str, max_results: int = 3) -> List[Dict[str, str]]:
    """
    生成网络搜索链接（Google/百度/必应）

    Args:
        query: 搜索关键词
        max_results: 兼容旧签名的占位参数（旧Schema里有），本实现不使用

    Returns:
        搜索链接列表：[{title, snippet, link}]
    """
    return build_search_links(query)
