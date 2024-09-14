import json
import logging
import os
import random
import urllib.parse
from functools import lru_cache
from typing import Dict, List, Union

import httpx
from httpx import AsyncClient
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from dotenv import load_dotenv
import asyncio

# 加载.env文件
load_dotenv()

# 设置日志格式和级别
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# 从.env文件中获取API_KEYS和API_URLS，并进行验证
API_KEYS = os.getenv("API_KEYS", "")
API_URLS = os.getenv("API_URLS", "")
CLAUDE_API_URLS = os.getenv("CLAUDE_API_URLS", "")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
BARK_URL = os.getenv("BARK_URL")

if not all([API_KEYS, API_URLS, CLAUDE_API_URLS, SECRET_TOKEN, BARK_URL]):
    logging.error("必要的环境变量未设置")
    raise ValueError("Missing required environment variables.")

API_KEYS = API_KEYS.split(",")
API_URLS = API_URLS.split(",")
CLAUDE_API_URLS = CLAUDE_API_URLS.split(",")
ALLOWED_PATHS = {"/v1/completions", "/v1/chat/completions", "/v1/models"}


@lru_cache(maxsize=1)
def get_models_data() -> Dict[str, List[Dict[str, str]]]:
    return {
        "data": [
            {"id": "gpt-4o"},
            {"id": "gpt-4o-mini"},
            {"id": "claude-3-5-sonnet-20240620"},
            {"id": "claude-3-opus-20240229"},
            {"id": "claude-3-sonnet-20240229"},
            {"id": "claude-3-haiku-20240307"},
        ]
    }


def add_cors_headers(response: Response) -> Response:
    response.headers.update({
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "*"
    })
    return response


async def handle_options(request):
    return add_cors_headers(Response())


async def handle_models(request):
    return add_cors_headers(JSONResponse(get_models_data()))


async def validate_request(request) -> Union[Response, None]:
    if request.method not in ["POST", "GET", "OPTIONS"]:
        return add_cors_headers(Response("Method Not Allowed", status_code=405))

    if request.url.path not in ALLOWED_PATHS:
        return add_cors_headers(Response("Not Found", status_code=404))

    auth_header = request.headers.get("Authorization")
    if not (
        auth_header
        and auth_header.startswith("Bearer ")
        and auth_header.split(" ")[1] == SECRET_TOKEN
    ):
        return add_cors_headers(Response("Unauthorized", status_code=401))

    return None


async def forward_request(
    target_url: str, headers: Dict[str, str], data: Dict
) -> Response:
    try:
        # 删除原有的 Host 和 Authorization 头
        headers.pop("host", None)
        headers.pop("authorization", None)
        # 添加新的 Host 头
        headers["Host"] = urllib.parse.urlparse(target_url).netloc

        # 处理 Content-Length 头部
        if not data:
            headers.pop("content-length", None)
        else:
            headers["content-length"] = str(len(json.dumps(data)))

        if data.get("stream", False):
            async def stream_response():
                try:
                    async with AsyncClient(timeout=60, verify=False) as client:
                        async with client.stream(
                            "POST", target_url, headers=headers, json=data
                        ) as response:
                            async for chunk in response.aiter_bytes():
                                yield chunk
                                await asyncio.sleep(0)  # 让出控制权
                except httpx.StreamClosed:
                    logging.warning("客户端断开连接")
                except Exception as e:
                    logging.error(f"流式传输时发生错误: {str(e)}")

            return StreamingResponse(
                stream_response(),
                status_code=200,
                media_type="text/event-stream",
            )
        else:
            async with AsyncClient(timeout=60, verify=False) as client:
                response = await client.post(target_url, headers=headers, json=data)
                return Response(
                    content=response.content,
                    status_code=response.status_code,
                    headers={
                        k: v
                        for k, v in response.headers.items()
                        if k.lower() != "content-length"
                    },
                )
    except httpx.TimeoutException:
        logging.error("请求超时")
        return Response("Request Timeout", status_code=504)
    except httpx.RequestError as e:
        logging.error(f"请求失败: {str(e)}")
        return Response("Internal Server Error", status_code=500)


async def notify_error(message: str) -> None:
    encoded_message = urllib.parse.quote(message)
    request_url = f"{BARK_URL}chat2api-balance/{encoded_message}"
    try:
        async with AsyncClient(timeout=5) as client:
            response = await client.get(request_url)
            if response.status_code != 200:
                logging.warning(f"通知失败: {response.status_code}")
    except httpx.TimeoutException:
        logging.warning("通知超时")
    except httpx.RequestError as e:
        logging.warning(f"通知失败: {str(e)}")


async def proxy(request):
    try:
        validation_result = await validate_request(request)
        if validation_result:
            return validation_result

        if request.url.path == "/v1/models":
            return await handle_models(request)

        data = await request.json()
        model_name = data.get("model", "")

        if "gpt" in model_name:
            random_key = random.choice(API_KEYS)
            random_url = random.choice(API_URLS)
        elif "claude" in model_name:
            random_key = ""
            random_url = random.choice(CLAUDE_API_URLS)
        else:
            return add_cors_headers(Response("Unsupported model", status_code=400))

        headers = dict(request.headers)
        if "gpt" in model_name:
            headers["Authorization"] = f"Bearer {random_key}"
        target_url = f"{random_url}{request.url.path}"

        logging.info(
            f"请求方法: {request.method}, 目标URL: {target_url}, model_name: {model_name}"
        )

        response = await forward_request(target_url, headers, data)

        if response.status_code != 200:
            message = (
                f"响应状态码: {response.status_code}\n"
                f"请求方法: {request.method}\n"
                f"目标URL: {random_url[7:]}\n"
                f"model_name: {model_name}\n"
                f"random_key: {random_key}"
            )
            await notify_error(message)

        return add_cors_headers(response)
    except json.JSONDecodeError:
        logging.error("无效的JSON格式")
        return add_cors_headers(Response("Bad Request: Invalid JSON", status_code=400))
    except Exception as e:
        logging.error(f"处理请求时发生错误: {str(e)}")
        return add_cors_headers(Response("Internal Server Error", status_code=500))


routes = [Route("/{path:path}", proxy, methods=["GET", "POST", "OPTIONS"])]

app = Starlette(routes=routes)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=5000)
