# my_ai_app/modules/agent/tools/search_tool.py
import requests
from typing import List, Dict, Optional
import json


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

            return results

        except Exception as e:
            return [{'title': '搜索失败', 'snippet': f'错误: {str(e)}', 'link': ''}]


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