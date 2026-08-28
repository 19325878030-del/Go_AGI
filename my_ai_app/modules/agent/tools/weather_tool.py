# my_ai_app/modules/agent/tools/weather_tool.py
import random
from datetime import datetime
from typing import Dict, Any


def get_current_weather(city: str, unit: str = "celsius") -> Dict[str, Any]:
    """
    获取指定城市的当前天气信息

    Args:
        city: 城市名称
        unit: 温度单位，celsius（摄氏度）或 fahrenheit（华氏度）

    Returns:
        包含天气信息的字典
    """
    # 模拟天气数据（实际应用中可调用真实API）
    weather_data = {
        "city": city,
        "temperature": random.randint(-10, 35),
        "condition": random.choice(["晴天", "多云", "阴天", "小雨", "大雪", "大风"]),
        "humidity": random.randint(30, 90),
        "unit": unit,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    # 如果是华氏度，转换温度
    if unit == "fahrenheit":
        weather_data["temperature"] = weather_data["temperature"] * 9 / 5 + 32

    return weather_data


def get_weather_forecast(city: str, days: int = 3) -> Dict[str, Any]:
    """
    获取指定城市的天气预报

    Args:
        city: 城市名称
        days: 预报天数（1-7天）

    Returns:
        包含天气预报的字典
    """
    conditions = ["晴天", "多云", "阴天", "小雨", "大雪", "大风", "雷阵雨"]
    forecast = []

    for i in range(min(days, 7)):
        forecast.append({
            "day": (datetime.now().replace(hour=0, minute=0, second=0)
                    .replace(day=datetime.now().day + i)
                    .strftime("%Y-%m-%d")),
            "condition": random.choice(conditions),
            "high_temp": random.randint(15, 35),
            "low_temp": random.randint(-5, 20),
            "rain_probability": random.randint(0, 100)
        })

    return {
        "city": city,
        "forecast": forecast,
        "total_days": len(forecast)
    }