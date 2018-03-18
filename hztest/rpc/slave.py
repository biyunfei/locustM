# -*- coding: UTF-8 -*-
r"""
slave接收来自master的消息指令，在gevent协程worker中进行处理，包括：状态，资源，脚本文件，locust客户端启停，完成后反馈结果给master；
"""
import zmq.green as zmq
from protocol import Message
import os
import codecs
from time import time, sleep
import gevent
from gevent.pool import Group
import random
import socket
from hashlib import md5
import events
import logging
import signal
import sys
from subprocess import Popen
import psutil as ps
import shutil


STATE_INIT, STATE_RUNNING, STATE_STOPPED = ["ready", "running", "stopped"]
sh = logging.StreamHandler()
sh.setFormatter(logging.Formatter('[%(asctime)s] - %(message)s'))
logger = logging.getLogger()
logger.addHandler(sh)
logger.setLevel(logging.INFO)


class BaseSocket(object):
    def send(self, msg):
        self.sender.send(msg.serialize())

    def recv(self):
        data = self.receiver.recv()
        return Message.unserialize(data)

    def noop(self, *args, **kwargs):
        """ Used to link() greenlets to in order to be compatible with gevent 1.0 """
        pass


class Client(BaseSocket):
    def __init__(self, host, port):
        self.host = host
        context = zmq.Context()
        self.receiver = context.socket(zmq.PULL)
        try:
            self.receiver.connect("tcp://%s:%i" % (host, port + 1))
        except:
            sys.exit(0)
        self.sender = context.socket(zmq.PUSH)
        try:
            self.sender.connect("tcp://%s:%i" % (host, port))
        except:
            sys.exit(0)


# 定义slave类
class Slave(Client):
    def __init__(self, *args, **kwargs):
        super(Slave, self).__init__(*args, **kwargs)
        self.client_id = socket.gethostname() + "_" + md5(
            str(time() + random.randint(0, 10000)).encode('utf-8')).hexdigest()
        logger.info("Client id:%r" % self.client_id)
        self.state = STATE_INIT
        self.slave_num = 0
        self.file_name = ''
        self.cpu_num = ps.cpu_count()
        self.processes = []
        self.greenlet = Group()
        # 加载gevent协程
        self.greenlet.spawn(self.worker).link_exception(callback=self.noop)
        self.greenlet.spawn(self.ready_loop).link_exception(callback=self.noop)
        def on_quitting():
            self.send(Message("quit", None, self.client_id))
            self.greenlet.kill(block=True)

        events.quitting += on_quitting

    # 消息收发循环，通过gevent协程加载
    def worker(self):
        while True:
            msg = self.recv()
            if msg.node_id == self.client_id:
                logger.info('Slave: Get new msg from master - [%s]' % msg.type)
                # 接收压测脚本保存到./script文件夹中
                if msg.type == "send_script":
                    logger.info("Save script to file...")
                    if not os.path.exists("./script/"):
                        os.mkdir("./script/")
                    self.file_name = os.path.join("./script/", msg.data["filename"])
                    with codecs.open(self.file_name, 'w', encoding='utf-8') as f:
                        f.write(msg.data["script"])
                    logger.info("Script saved into file:%s" % self.file_name)
                # 运行locust压测进程，完成后返回成功启动的进程数给master
                elif msg.type == "run":
                    if self.state != STATE_RUNNING:
                        self.run_locusts(master_host=self.host, nums=msg.data["num"], file_name=msg.data["filename"])
                    if self.slave_num > 0:
                        self.state = STATE_RUNNING
                        logger.info("Client %s run OK!" % self.client_id)
                    else:
                        self.state = STATE_INIT
                    self.send(Message("slave_num", self.slave_num, self.client_id))
                # 停止locust压测进程并更新状态给master
                elif msg.type == "stop":
                    logger.info("Client %s stopped!" % self.client_id)
                    self.stop()
                    #self.send(Message("client_ready", self.slave_num, self.client_id))
                    self.send(Message("slave_num", self.slave_num, self.client_id))
                # 退出slave，当master退出时收到此消息
                elif msg.type == "quit":
                    logger.info("Got quit message from master, shutting down...")
                    self.stop()
                    self.greenlet.kill(block=True)
                # 获取当前客户端的压测文件列表
                elif msg.type == "get_filelist":
                    if os.path.exists("./script/"):
                        file_list = []
                        for root, dirs, files in os.walk("./script/"):
                            for f in files:
                                if os.path.splitext(f)[1] == '.py':
                                    file_list.append(f)
                            self.send(Message("file_list", file_list, self.client_id))
                    else:
                        self.send(Message("file_list", None, self.client_id))
                # 获取当前客户端的资源状态：包括IP, CPU，内存，网络
                elif msg.type == "get_psinfo":
                    ip = socket.gethostbyname(socket.gethostname())
                    nets = ps.net_io_counters()
                    sleep(1)
                    nets1 = ps.net_io_counters()
                    net = {'sent': nets1.bytes_sent / 1024, 'recv': nets1.bytes_recv / 1024,
                           'per_sec_sent': (nets1.bytes_sent - nets.bytes_sent) / 1024,
                           'per_sec_recv': (nets1.bytes_recv - nets.bytes_recv) / 1024}
                    cpu_times = ps.cpu_percent(interval=0.1)
                    cpu_logical_nums = ps.cpu_count()
                    cpu_nums = ps.cpu_count(logical=False)
                    cpu_freq = ps.cpu_freq()
                    if cpu_freq is not None:
                        cpu = {'num': cpu_nums, 'logical_num': cpu_logical_nums, 'percent': cpu_times,
                               'freq': {'current': cpu_freq.current, 'min': cpu_freq.min, 'max': cpu_freq.max}}
                    else:
                        cpu = {'num': cpu_nums, 'logical_num': cpu_logical_nums, 'percent': cpu_times,
                               'freq': {'current': 0, 'min': 0, 'max': 0}}
                    mems = ps.virtual_memory()
                    mem = {'total': mems.total / 1024 / 1024, 'available': mems.available / 1024 / 1024,
                           'percent': mems.percent}
                    psinfo = {"cpu": cpu, "mem": mem, "net": net, "IP": ip}
                    self.send(Message("psinfo", psinfo, self.client_id))
                # 清除压测脚本文件夹
                elif msg.type == "clear_folder":
                    if os.path.exists("./script/"):
                        shutil.rmtree("./script")
                    self.send(Message("clear_folder", None, self.client_id))

    # 每分钟向master上报状态
    def ready_loop(self):
        while True:
            # 发送ready状态至master
            logger.info('Send ready to server!')
            self.send(Message("slave_ready", self.slave_num, self.client_id))
            gevent.sleep(60)

    # 退出locust压测进程
    def stop(self):
        self.state = STATE_STOPPED
        self.slave_num = 0
        for p in self.processes:
            procs = p.children()
            for proc in procs:
                proc.terminate()
            p.terminate()
            logger.info("Quit a locust client process!")
        self.processes = []

    # 运行locust压测进程
    def run_locusts(self, master_host, nums, file_name):
        # 设置压测进程数，不大于CPU逻辑核心数
        if int(nums) > self.cpu_num or int(nums) < 1:
            slave_num = self.cpu_num
        else:
            slave_num = int(nums)
        # 设置各压测进程的压测脚本，如果web端选择的小于进程数，则循环选择
        script_file = []
        for i in range(slave_num):
            script_file.append(os.path.join('./script/', file_name[i % len(file_name)]))
        # 启动压测进程
        for i in range(slave_num):
            cmd = 'locust -f %s --slave --no-reset-stats --master-host=%s' % (script_file[i], master_host)
            print cmd
            p = ps.Popen(cmd, shell=True, stdout=None, stderr=None)
            self.processes.append(p)
        sleep(1)
        # 更新启动成功的压测进程列表
        proc = []
        for p in self.processes:
            if p.poll() is None:
                proc.append(p)
        self.processes = proc
        self.slave_num = len(proc)


def shutdown(code=0):
    logger.info("Shutting down (exit code %s), bye." % code)
    events.quitting.fire()
    sys.exit(code)


# install SIGTERM handler
def sig_term_handler():
    logger.info("Got SIGTERM signal")
    shutdown(0)


def slave(host=''):
    if host == '':
        host = socket.gethostbyname(socket.gethostname())
    port = 6666
    client = Slave(host, port)
    logger.info('Slave is starting at %s:%i' % (host, port))
    gevent.signal(signal.SIGTERM, sig_term_handler)
    try:
        client.greenlet.join()
        # gevent.joinall(client.greenlet.greenlets)
        code = 0
        shutdown(code=code)
    except KeyboardInterrupt as e:
        shutdown(1)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        slave(sys.argv[1])
    else:
        slave(socket.gethostbyname(socket.gethostname()))

