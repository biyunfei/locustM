# 使用Python官方镜像作为镜像的基础
FROM python:2.7-slim
MAINTAINER biyunfei
# 添加vim和gcc依赖
RUN apt-get update && apt-get install -y vim gcc \
# 用完包管理器后安排打扫卫生可以显著的减少镜像大小
    && apt-get clean \
    && apt-get autoclean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
# 设置工作空间为/app
WORKDIR /app
# 安装requirements.txt中指定的依赖
ADD requirements.txt /app
RUN pip install -r requirements.txt