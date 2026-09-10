# 验证：工具元数据注册表 + 按需动态加载（不依赖 Ollama/网络）
# 运行: python tests/verify_tool_system.py
#
# 验证五件事：
#   1. 注册表扫出 5 个工具 Schema（weather/calculator/web_search 三包）
#   2. 惰性加载：拿到 Schema 后、调用前，实现模块尚未导入
#   3. 动态加载后工具执行正确（calculator 单元换算/表达式、判空辅助函数）
#   4. 二次调用命中缓存（加载器 loaded_packages 不再增长、同一函数对象）
#   5. 工具包概览与按包过滤（前端勾选：display_name 展示、get_schemas 只含启用包）
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, r'D:\Go_AGI')

from my_ai_app.modules.agent.tool_registry import ToolRegistry
from my_ai_app.modules.agent.tool_loader import ToolLoader


def main():
    # ---- 1) 注册表扫描：5个工具，且全程未导入任何实现 ----
    registry = ToolRegistry()
    expected = {'get_weather', 'get_forecast', 'calculator', 'convert_units', 'web_search'}
    assert set(registry.tool_names) == expected, f"工具集不符: {registry.tool_names}"
    schemas = registry.get_schemas()
    assert schemas['calculator']['description'] == '计算数学表达式'
    assert schemas['get_weather']['parameters']['required'] == ['city']
    info = registry.get_tool_info('calculator')
    assert info['package'] == 'calculator' and info['entry_function'] == 'calculator'
    assert registry.get_tool_info('no_such_tool') is None
    print(f'✅ 1) 注册表扫出 {len(registry.tool_names)} 个工具Schema，元数据字段正确')

    loader = ToolLoader(registry)

    # ---- 2) 惰性加载：此刻实现模块还没进内存 ----
    assert not any(m.startswith('agent_tool_') for m in sys.modules), \
        '实现模块在调用前就被导入了'
    print('✅ 2) 调用前实现模块未被导入（惰性加载生效）')

    # ---- 3) 动态加载后执行正确 ----
    calculator = loader.get_function('calculator')
    assert calculator is not None
    assert calculator('2+3*4') == 14.0, calculator('2+3*4')
    assert calculator('sqrt(16)') == 4.0

    convert = loader.get_function('convert_units')  # 同包第二个工具，应命中模块级缓存
    assert convert(1, 'km', 'm') == 1000.0
    assert abs(convert(100, 'c', 'f') - 212.0) < 1e-9

    helper_info = registry.get_fallback_helper()
    assert helper_info and helper_info['entry_function'] == 'has_real_results'
    has_real = loader.get_helper_function(helper_info)
    assert has_real is not None
    assert has_real([{'title': 'Google搜索', 'link': 'x'}]) is False   # 只剩兜底链接
    assert has_real([{'title': '摘要', 'link': 'x'}]) is True          # 有真实命中

    weather = loader.get_function('get_weather')
    assert weather('北京')['city'] == '北京'

    assert loader.get_function('no_such_tool') is None
    print('✅ 3) 动态加载后 calculator/convert_units/weather/判空函数 全部执行正确')

    # ---- 4) 二次调用命中缓存：函数对象不变，包不重复加载 ----
    n_before = len(loader.loaded_packages)
    calculator_again = loader.get_function('calculator')
    assert calculator_again is calculator, '二次调用返回了不同对象，缓存未命中'
    assert len(loader.loaded_packages) == n_before, '包被重复加载'
    print(f'✅ 4) 二次调用命中缓存（已加载包: {loader.loaded_packages}）')

    # ---- 5) 工具包概览与按包过滤（前端勾选） ----
    overview = registry.get_package_overview()
    assert {p['package'] for p in overview} == {'weather', 'calculator', 'web_search'}
    by_pkg = {p['package']: p for p in overview}
    assert by_pkg['weather']['display_name'] == '天气查询'      # manifest 的 display_name
    assert by_pkg['calculator']['display_name'] == '计算器与单位转换'
    assert {t['name'] for t in by_pkg['weather']['tools']} == {'get_weather', 'get_forecast'}

    # get_schemas 按包过滤：只勾 weather 时只剩天气两个工具
    assert set(registry.get_schemas(['weather']).keys()) == {'get_weather', 'get_forecast'}
    # 不传/空 = 全部（None 语义）
    assert set(registry.get_schemas(None).keys()) == expected
    # display_name 也能解析到包名；未知名字被丢弃
    assert registry.resolve_package_names(['天气查询', '不存在的包']) == ['weather']
    assert registry.resolve_package_names(None) is None
    print(f'✅ 5) 包概览/按包过滤/display_name 解析正确（{len(overview)} 个包）')

    print('\n全部验证通过 ✅')


if __name__ == '__main__':
    main()
