# my_ai_app/core/ollama_api_server.py
import sys
import json
from pathlib import Path
from typing import List, Dict, Optional, AsyncGenerator
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn
import httpx
import logging

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))


# ==================== 数据模型 ====================
class GenerateRequest(BaseModel):
    """生成请求"""
    prompt: str = Field(..., description="输入提示词")
    model: str = Field("qwen2.5:3b", description="模型名称")
    max_tokens: int = Field(512, description="最大生成token数", ge=1, le=4096)
    temperature: float = Field(0.7, description="温度参数", ge=0.0, le=2.0)
    top_p: float = Field(0.9, description="Top-p采样", ge=0.0, le=1.0)
    stream: bool = Field(False, description="是否流式输出")


class ChatMessage(BaseModel):
    """聊天消息"""
    role: str = Field(..., description="角色: system/user/assistant")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    """聊天请求"""
    messages: List[ChatMessage] = Field(..., description="对话历史")
    model: str = Field("qwen2.5:3b", description="模型名称")
    temperature: float = Field(0.7, description="温度参数")
    max_tokens: int = Field(512, description="最大生成token数")
    stream: bool = Field(False, description="是否流式输出")


# ==================== Ollama服务封装 ====================
class OllamaAPIService:
    """Ollama API服务封装"""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        # trust_env=False：绕开系统代理，否则httpx会把localhost请求发给代理导致连接被拒
        self.client = httpx.Client(timeout=120.0, trust_env=False)
        logger.info(f"✅ Ollama服务初始化，连接到: {base_url}")

    def health_check(self) -> bool:
        """健康检查 - 同步版本"""
        try:
            response = self.client.get(f"{self.base_url}/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"健康检查失败: {e}")
            return False

    def list_models(self) -> List[Dict]:
        """列出可用模型"""
        try:
            response = self.client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return data.get("models", [])
        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return []

    def generate(self, request: GenerateRequest) -> Dict:
        """生成文本"""
        payload = {
            "model": request.model,
            "prompt": request.prompt,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "top_p": request.top_p,
                "num_predict": request.max_tokens,
            }
        }

        try:
            response = self.client.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Ollama生成错误: {e}")
            raise HTTPException(status_code=503, detail=f"Ollama服务错误: {str(e)}")

    def generate_stream(self, request: GenerateRequest):
        """流式生成 - 生成器"""
        payload = {
            "model": request.model,
            "prompt": request.prompt,
            "stream": True,
            "options": {
                "temperature": request.temperature,
                "top_p": request.top_p,
                "num_predict": request.max_tokens,
            }
        }

        try:
            with self.client.stream("POST", f"{self.base_url}/api/generate", json=payload, timeout=120.0) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if line:
                        data = json.loads(line)
                        yield data
        except Exception as e:
            logger.error(f"流式生成错误: {e}")
            yield {"error": str(e)}

    def chat(self, request: ChatRequest) -> Dict:
        """对话模式"""
        messages = [msg.dict() for msg in request.messages]

        payload = {
            "model": request.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            }
        }

        try:
            response = self.client.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=60.0
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.error(f"Ollama聊天错误: {e}")
            raise HTTPException(status_code=503, detail=f"Ollama服务错误: {str(e)}")


# ==================== 应用生命周期 ====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global service

    # 启动时执行
    print("\n" + "=" * 60)
    print("🚀 启动本地LLM API服务 (Ollama后端)")
    print("=" * 60)

    service = OllamaAPIService()

    # 检查Ollama是否运行
    if service.health_check():
        print("✅ Ollama服务连接成功")
        models = service.list_models()
        if models:
            print(f"📦 可用模型:")
            for m in models:
                print(f"   - {m.get('name', 'unknown')} ({m.get('size', 0) // 1024 ** 3:.1f} GB)")
        else:
            print("⚠️ 没有找到可用模型")
    else:
        print("❌ 无法连接到Ollama服务")
        print("   请确保Ollama正在运行:")
        print("   - 运行: ollama serve")
        print("   - 或检查: http://localhost:11434")

    print("=" * 60)

    yield  # 应用运行期间

    # 关闭时执行
    if service and service.client:
        service.client.close()
        print("🔄 Ollama客户端已关闭")


# ==================== 创建FastAPI应用 ====================
app = FastAPI(
    title="本地LLM API服务 (Ollama后端)",
    description="高性能本地LLM API服务，基于Ollama",
    version="1.0.0",
    lifespan=lifespan
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局服务实例
service = None


# ==================== API端点 ====================
@app.get("/")
async def root():
    """根路径"""
    return {
        "service": "Local LLM API",
        "status": "running",
        "backend": "Ollama",
        "version": "1.0.0",
        "endpoints": {
            "generate": "/generate",
            "generate_stream": "/generate/stream",
            "chat": "/chat",
            "health": "/health",
            "models": "/models"
        }
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    global service
    if not service:
        return {"status": "unavailable", "message": "服务未初始化"}

    is_healthy = service.health_check()
    return {
        "status": "healthy" if is_healthy else "unhealthy",
        "backend": "Ollama",
        "message": "Ollama服务运行正常" if is_healthy else "Ollama服务未响应"
    }


@app.get("/models")
async def list_models():
    """列出所有可用模型"""
    global service
    if not service:
        raise HTTPException(status_code=503, detail="服务未就绪")

    models = service.list_models()
    return {
        "models": models,
        "count": len(models)
    }


@app.post("/generate")
async def generate(request: GenerateRequest):
    """文本生成接口"""
    global service
    if not service:
        raise HTTPException(status_code=503, detail="服务未就绪")

    try:
        result = service.generate(request)
        return {
            "text": result.get("response", ""),
            "model": result.get("model", request.model),
            "created_at": result.get("created_at", ""),
            "usage": {
                "prompt_tokens": result.get("prompt_eval_count", 0),
                "completion_tokens": result.get("eval_count", 0)
            }
        }
    except Exception as e:
        logger.error(f"生成失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/generate/stream")
async def generate_stream(request: GenerateRequest):
    """流式文本生成"""
    global service
    if not service:
        raise HTTPException(status_code=503, detail="服务未就绪")

    def stream_generator():
        """生成流式响应"""
        for chunk in service.generate_stream(request):
            if "error" in chunk:
                yield f"data: {json.dumps({'error': chunk['error']})}\n\n"
            else:
                data = {
                    "text": chunk.get("response", ""),
                    "done": chunk.get("done", False)
                }
                yield f"data: {json.dumps(data)}\n\n"

            if chunk.get("done", False):
                yield "data: [DONE]\n\n"

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/chat")
async def chat(request: ChatRequest):
    """对话接口"""
    global service
    if not service:
        raise HTTPException(status_code=503, detail="服务未就绪")

    try:
        result = service.chat(request)
        message = result.get("message", {})
        return {
            "message": message.get("content", ""),
            "model": result.get("model", request.model),
            "created_at": result.get("created_at", ""),
            "usage": {
                "prompt_tokens": result.get("prompt_eval_count", 0),
                "completion_tokens": result.get("eval_count", 0)
            }
        }
    except Exception as e:
        logger.error(f"聊天失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 启动函数 ====================
def run_server(host: str = "0.0.0.0", port: int = 8000):
    """运行服务器"""
    print("\n" + "=" * 60)
    print("🚀 启动本地LLM API服务")
    print("=" * 60)
    print(f"📍 服务地址: http://{host}:{port}")
    print(f"📚 API文档: http://{host}:{port}/docs")
    print(f"🔍 健康检查: http://{host}:{port}/health")
    print("=" * 60)
    print("\n按 Ctrl+C 停止服务\n")

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )


if __name__ == "__main__":
    run_server()