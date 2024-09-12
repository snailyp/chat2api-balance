import random
from flask import Flask, Response, jsonify, make_response, request, stream_with_context
import requests
import logging
import os
from dotenv import load_dotenv
import urllib.parse

# 加载.env文件
load_dotenv()

# 设置日志级别
logging.basicConfig(level=logging.INFO)

# 从.env文件中获取API_KEYS和API_URLS
API_KEYS = os.getenv('API_KEYS', '').split(',')
API_URLS = os.getenv('API_URLS', '').split(',')
CLAUDE_API_URLS = os.getenv('CLAUDE_API_URLS', '').split(',')

SECRET_TOKEN = os.getenv('SECRET_TOKEN')
BARK_URL = os.getenv('BARK_URL')
ALLOWED_PATHS = ["/v1/completions", "/v1/chat/completions", "/v1/models"]

app = Flask(__name__)

@app.route("/<path:path>", methods=["POST", "GET", "OPTIONS"])
def proxy(path):
    # 处理OPTIONS请求
    if request.method == "OPTIONS":
        response = make_response()
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Headers", "*")
        response.headers.add("Access-Control-Allow-Methods", "*")
        return response

    # 检查请求方法
    if request.method not in ["POST", "GET"]:
        return Response("Method Not Allowed", status=405)

    # 检查请求路径
    if f"/{path}" not in ALLOWED_PATHS:
        return Response("Not Found", status=404)
    
    if path == "v1/models":
        # 处理 /v1/models 请求
        models_data = {
            "data": [
                {"id": "gpt-4o"},
                {"id": "gpt-4o-mini"},
                {"id": "claude-3-5-sonnet-20240620"},
                {"id": "claude-3-opus-20240229"},
                {"id": "claude-3-sonnet-20240229"},
                {"id": "claude-3-haiku-20240307"},
            ]
        }
        return jsonify(models_data), 200

    # 验证incoming请求
    auth_header = request.headers.get("Authorization")
    if (
        not auth_header
        or not auth_header.startswith("Bearer ")
        or auth_header.split(" ")[1] != SECRET_TOKEN
    ):
        return Response("Unauthorized", status=401)
    
    # 获取请求体
    request_data = request.json

    # 获取model_name
    model_name = request_data.get('model')
    
    # 随机选择API密钥和URL
    random_key = random.choice(API_KEYS) if "gpt" in model_name else ""
    random_url = random.choice(API_URLS) if "gpt" in model_name else random.choice(CLAUDE_API_URLS)

    # 创建新的请求头
    headers = dict(request.headers)
    if "gpt" in model_name:
        headers["Authorization"] = f"Bearer {random_key}"
    headers["Host"] = f"{random_url.split('//')[1]}"
    # 构建目标URL
    target_url = f"{random_url}/{path}"

    # 打印必要的URL
    logging.info(f"请求方法: {request.method}")
    logging.info(f"目标URL: {target_url}")
    logging.info(f"mode_name: {model_name}")
    logging.info(f"random_key: {random_key}")
    
    # 检查是否为流式请求
    is_stream = request_data.get('stream', False)
    
    if is_stream:
        # 流式请求
        response = requests.post(target_url, headers=headers, json=request_data, stream=True)
        
        def generate():
            for chunk in response.iter_lines():
                if chunk:
                    yield f"{chunk.decode('utf-8')}\n\n"
        if response.status_code != 200:
            logging.warning(f"响应状态码: {response.status_code}")
            logging.warning(f"响应内容: {response.text}")
            message = f"响应状态码: {response.status_code}\n响应内容: {response.text}\n请求方法: {request.method}\n目标URL: {random_url[7:]}\nmodel_name: {model_name}\nrandom_key: {random_key}"
            encoded_message = urllib.parse.quote(message)
            request_url = f"{BARK_URL}chat2api-balance/{encoded_message}"
            requests.get(request_url, timeout=5)
        return Response(stream_with_context(generate()), content_type='text/event-stream')
    else:
        # 非流式请求
        response = requests.post(target_url, headers=headers, json=request_data)
        # 打印响应状态码
        logging.info(f"响应状态码: {response.status_code}")
        response = Response(
            response.content, status=response.status_code, headers=dict(response.headers)
        )
    
    # 添加CORS头
    response.headers.add("Access-Control-Allow-Origin", "*")
    response.headers.add("Access-Control-Allow-Headers", "*")
    response.headers.add("Access-Control-Allow-Methods", "*")
    return response

if __name__ == "__main__":
    app.run(port=5000)

