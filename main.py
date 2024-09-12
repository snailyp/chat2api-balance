# 设置日志级别from flask import Flask, request, Response, stream_with_context, make_response
import random
from flask import Flask, Response, make_response, request, stream_with_context
import requests
import logging
import os
from dotenv import load_dotenv

# 加载.env文件
load_dotenv()

# 设置日志级别
logging.basicConfig(level=logging.INFO)

# 从.env文件中获取API_KEYS和API_URLS
API_KEYS = os.getenv('API_KEYS', '').split(',')
API_URLS = os.getenv('API_URLS', '').split(',')

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

    # 验证incoming请求
    auth_header = request.headers.get("Authorization")
    if (
        not auth_header
        or not auth_header.startswith("Bearer ")
        or auth_header.split(" ")[1] != SECRET_TOKEN
    ):
        return Response("Unauthorized", status=401)

    # 随机选择API密钥和URL
    random_key = random.choice(API_KEYS)
    random_url = random.choice(API_URLS)

    # 创建新的请求头
    headers = dict(request.headers)
    headers["Authorization"] = f"Bearer {random_key}"
    headers["Host"] = f"{random_url.split('//')[1]}"
    # 构建目标URL
    target_url = f"{random_url}/{path}"

    # 打印必要的URL
    logging.info(f"请求方法: {request.method}")
    logging.info(f"目标URL: {target_url}")
    logging.info(f"random_key: {random_key}")

    # 发送请求到目标API
    if request.method == "POST":
        # 获取请求体
        request_data = request.json
        
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
                requests.get(f"{BARK_URL}chat2api-balance/响应状态码:{response.status_code}\n响应内容:{response.text}\n请求方法: {request.method}\n目标URL: {target_url}\nrandom_key: {random_key}",timeout=5)
            return Response(stream_with_context(generate()), content_type='text/event-stream')
        else:
            # 非流式请求
            response = requests.post(target_url, headers=headers, json=request_data)
            
            # 打印响应状态码
            logging.info(f"响应状态码: {response.status_code}")
            
            response = Response(
                response.content, status=response.status_code, headers=dict(response.headers)
            )
    else:  # GET
        response = requests.get(target_url, headers=headers)
        
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

