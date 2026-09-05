# my_ai_app/controllers/api/response.py
"""
统一响应信封（接口契约规范化）。

所有 JSON 接口统一返回 { code, msg, data }：
    * 成功：HTTP 200，{ "code": 0, "msg": "success", "data": <载荷> }
    * 错误：保留 HTTP 状态码，{ "code": <同数值>, "msg": <具体错误>, "data": null }

注意：本模块只 import flask（叶子模块，避免循环依赖）；
返回必须是 (flask.Response, int) 元组 —— @log_api 依赖 resp.get_json() 记录出参，
不要改成返回裸 dict。
"""
from flask import jsonify


def ok(data=None, msg="success"):
    """成功响应。msg 固定为 "success"；空载荷请传 ok({})。"""
    return jsonify({"code": 0, "msg": msg, "data": data}), 200


def err(msg, code):
    """错误响应。code 同时作为 HTTP 状态码与业务码，data 固定 null。"""
    return jsonify({"code": code, "msg": msg, "data": None}), code
