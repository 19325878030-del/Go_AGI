# my_ai_app/simple_app.py
"""
兼容层：用于保持向后兼容。
主入口现已统一收敛至 app.py 的 create_app()。

以后无论运行 `python app.py` 还是 `python simple_app.py`，跑的都是同一套工厂逻辑；
团队与自动化脚本统一使用 `python app.py`。
"""
import os

from app import app  # noqa: F401  （从 app.py 拿同一个已创建好的 Flask 实例）

if __name__ == '__main__':
    port = int(os.getenv("PORT", "5001"))  # 5000 被本机其他项目占用，默认 5001
    app.run(debug=app.config.get("DEBUG", True), host='0.0.0.0', port=port)
