# 使用官方Python运行时作为父镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 复制项目文件到工作目录
COPY . /app

# 安装项目依赖
RUN pip install --no-cache-dir -r requirements.txt

# 暴露端口5000供外部访问
EXPOSE 5000

# 运行应用
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "5000"]