# my_ai_app/modules/agent/tools/calculator_tool.py
import math
from typing import Union


def calculator(expression: str) -> Union[float, str]:
    """
    计算数学表达式

    Args:
        expression: 数学表达式，如 "2+3*4" 或 "sqrt(16)"

    Returns:
        计算结果或错误信息
    """
    # 安全计算，只允许数学函数和基本运算
    allowed_names = {
        k: v for k, v in math.__dict__.items() if not k.startswith("__")
    }
    allowed_names.update({"abs": abs, "round": round})

    # 移除可能导致安全问题的字符
    expression = expression.replace("^", "**")

    try:
        # 使用eval但限制命名空间
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        return float(result) if isinstance(result, (int, float)) else result
    except Exception as e:
        return f"计算错误: {str(e)}"


def convert_units(value: float, from_unit: str, to_unit: str) -> float:
    """
    单位转换

    Args:
        value: 数值
        from_unit: 源单位
        to_unit: 目标单位

    Returns:
        转换后的数值
    """
    # 长度单位转换（米为基础）
    length_units = {
        "m": 1, "meter": 1, "meters": 1,
        "km": 1000, "kilometer": 1000, "kilometers": 1000,
        "cm": 0.01, "centimeter": 0.01,
        "mm": 0.001, "millimeter": 0.001,
        "inch": 0.0254, "inches": 0.0254,
        "ft": 0.3048, "foot": 0.3048, "feet": 0.3048,
        "yd": 0.9144, "yard": 0.9144, "yards": 0.9144,
        "mile": 1609.344, "miles": 1609.344
    }

    # 温度转换
    if from_unit in ["c", "celsius"] and to_unit in ["f", "fahrenheit"]:
        return value * 9 / 5 + 32
    elif from_unit in ["f", "fahrenheit"] and to_unit in ["c", "celsius"]:
        return (value - 32) * 5 / 9
    elif from_unit in ["c", "celsius"] and to_unit in ["k", "kelvin"]:
        return value + 273.15
    elif from_unit in ["k", "kelvin"] and to_unit in ["c", "celsius"]:
        return value - 273.15

    # 长度转换
    if from_unit in length_units and to_unit in length_units:
        meters = value * length_units[from_unit]
        return meters / length_units[to_unit]

    raise ValueError(f"不支持的转换: {from_unit} -> {to_unit}")