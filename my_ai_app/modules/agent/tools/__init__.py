# my_ai_app/modules/agent/tools/__init__.py
from .weather_tool import get_current_weather, get_weather_forecast
from .calculator_tool import calculator, convert_units
from .search_tool import web_search, has_real_results

__all__ = [
    'get_current_weather',
    'get_weather_forecast',
    'calculator',
    'convert_units',
    'web_search',
    'has_real_results'
]