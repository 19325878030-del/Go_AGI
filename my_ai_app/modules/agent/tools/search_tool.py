# my_ai_app/modules/agent/tools/search_tool.py
import requests
from typing import List, Dict, Optional
import json
from urllib.parse import quote_plus


class WebSearchTool:
    """网络搜索工具（使用DuckDuckGo）"""

    def __init__(self):
        self.base_url = "https://api.duckduckgo.com/"

    def search(self, query: str, max_results: int = 3) -> List[Dict[str, str]]:
        """
        搜索网络信息

        Args:
            query: 搜索关键词
            max_results: 最大结果数

        Returns:
            搜索结果列表
        """
        try:
            params = {
                'q': query,
                'format': 'json',
                'no_html': 1,
                'skip_disambig': 1
            }

            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            results = []

            # 获取摘要信息
            if data.get('Abstract'):
                results.append({
                    'title': '摘要',
                    'snippet': data['Abstract'][:500],
                    'link': data.get('AbstractURL', '')
                })

            # 获取相关主题
            for topic in data.get('RelatedTopics', [])[:max_results]:
                if 'Text' in topic and 'FirstURL' in topic:
                    results.append({
                        'title': topic.get('Text', '').split('-')[0].strip(),
                        'snippet': topic.get('Text', ''),
                        'link': topic.get('FirstURL', '')
                    })

            # 无论DuckDuckGo是否返回内容，都附上Google/百度搜索链接，
            # 供用户在无法直接回答时自行查阅解决方法
            encoded_q = quote_plus(query)
            results.append({
                'title': 'Google搜索',
                'snippet': f'在Google上搜索"{query}"的解决方法',
                'link': f'https://www.google.com/search?q={encoded_q}'
            })
            results.append({
                'title': '百度搜索',
                'snippet': f'在百度上搜索"{query}"的解决方法',
                'link': f'https://www.baidu.com/s?wd={encoded_q}'
            })

            return results

        except Exception as e:
            return [{'title': '搜索失败', 'snippet': f'错误: {str(e)}', 'link': ''}]


# 固定追加的兜底链接标题，用于识别"搜索没有命中真实结果"的情况
FALLBACK_LINK_TITLES = {'Google搜索', '百度搜索'}


def has_real_results(results) -> bool:
    """判断搜索结果里是否有真实命中（排除兜底链接和失败提示）"""
    if not isinstance(results, list):
        return False
    for item in results:
        if isinstance(item, dict) and item.get('title') not in FALLBACK_LINK_TITLES \
                and item.get('title') != '搜索失败':
            return True
    return False


# 创建全局实例
search_tool = WebSearchTool()


def web_search(query: str, max_results: int = 3) -> List[Dict[str, str]]:
    """
    搜索网页信息

    Args:
        query: 搜索关键词
        max_results: 最大结果数

    Returns:
        搜索结果
    """
    return search_tool.search(query, max_results)