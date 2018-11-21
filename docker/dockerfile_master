# 使用Python官方镜像作为镜像的基础
FROM locust
MAINTAINER biyunfei
# 把当前目录下的文件拷贝到 容器里的/app里
ADD ../hztest /app/hztest
# 设置工作空间为/app
WORKDIR /app/hztest
# 设置时区
RUN echo "Asia/Shanghai" > /etc/timezone
RUN dpkg-reconfigure -f noninteractive tzdata
# 开放8000端口
EXPOSE 6666 6667 5557 5558 8089 8000
# 设置 HOST 这个环境变量
ENV HOST 0
# 当容器启动时，运行app.py
ENTRYPOINT python manage.py runserver ${HOST}:8000