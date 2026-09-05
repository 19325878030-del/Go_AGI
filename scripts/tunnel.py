# scripts/tunnel.py
"""
内网穿透隧道启动脚本（Pinggy 免费版）。

作用：把本机 5001 端口（Flask 服务）映射成一个公网 HTTPS 地址，
其他电脑/手机（不在同一局域网）就能直接调你的接口调试。

用法（在项目根目录、激活 .venv 后运行）：
    python scripts/tunnel.py

运行后会打印两个 URL，前端 API_BASE 用 .run.pinggy-free.link 结尾那个。

⚠️ 免费版限制：隧道 60 分钟过期；断线/过期后重新运行本脚本即可，
   会分配新地址，前端 API_BASE 要跟着换。
"""
import subprocess
import sys

# Windows 控制台默认 GBK，print emoji 会抛 UnicodeEncodeError 直接崩，
# 强制标准输出为 UTF-8（和 simple_app.py 里的处理一致）
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# keepalive：每30秒发一次心跳，3次无响应判定断线（防止关代理等网络
# 抖动产生"僵尸连接"——进程还在但数据不转发，浏览器 ERR_EMPTY_RESPONSE）
# ExitOnForwardFailure：端口转发失败就直接退出，方便发现问题
COMMAND = [
    "ssh",
    "-o", "ServerAliveInterval=30",
    "-o", "ServerAliveCountMax=3",
    "-o", "ExitOnForwardFailure=yes",
    "-p", "443",
    "-R", "0:localhost:5001",   # 0 = 让服务器自动分配公网入口端口
    "a.pinggy.io",
]

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 启动 Pinggy 隧道（映射本机 5001 → 公网）")
    print("⏳ 免费版 60 分钟过期，过期后 Ctrl+C 再重跑本脚本")
    print("=" * 60)
    # 前台阻塞运行：URL 直接打在控制台，窗口关闭 = 隧道断开
    subprocess.run(COMMAND)
