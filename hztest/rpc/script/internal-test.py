# -*- coding: UTF-8 -*-

from locust import HttpLocust, TaskSet, task, events
import logging
import datetime
import os
from gevent._semaphore import Semaphore
all_locusts_spawned = Semaphore()
all_locusts_spawned.acquire()


def on_hatch_complete(**kwargs):
    all_locusts_spawned.release()

events.hatch_complete += on_hatch_complete


class YJKTask(TaskSet):
    _headers = {"Content-Type": "application/json; charset=UTF-8"}

    # 并发用户初始化
    def on_start(self):
        """ on_start is called when a Locust start before any task is scheduled """
        # self.login()
        all_locusts_spawned.wait()

    @task(1)
    def get(self):
        with self.client.get('/', catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure('Request failure!HTTP Response Status Code: %s, HTTP Response content: %s!' % (resp.status_code, resp.content))
                self.locust.logger.error('index.json Request failure!HTTP Response Status Code: %s, HTTP Response content: %s!' % (resp.status_code, resp.content))


class YJKUser(HttpLocust):
    # 设置Locust压力测试主机地址，用户任务类
    host = "https://www.baidu.com"
    task_set = YJKTask

    # 设置日志文件及格式
    if not os.path.exists('./log'):
        os.mkdir('./log')
    logging.basicConfig(level=logging.INFO)
    fh = logging.FileHandler('./log/log_%s.txt' % datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S'), mode='w')
    formatter = logging.Formatter('[%(asctime)s] - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger = logging.getLogger()    #__name__)
    logger.addHandler(fh)


    # 用户测试场景的等待时间ms，随机时间在min和max之间
    min_wait = 0
    max_wait = 0
    # 压测时间s，到时自动停止
    # stop_timeout = 600
