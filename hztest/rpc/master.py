# -*- coding: UTF-8 -*-
r"""
master负责与slave端进行通信，发送来自web的请求给slave，接收slave的结果；
主要有1个全局master监听服务，2个全局队列用于消息和结果传递，两个gevent协程，分别为master_cmd：接收cmd_queue进行派发给slave，master_listener：接收slave的消息反馈并返回给web端；
"""
import zmq.green as zmq
import multiprocessing
from protocol import Message
import six
import gevent
from gevent.pool import Group
import socket
import events
import sys, time
import logging
import signal
from multiprocessing import Queue, Lock

# 定义全局变量：指令队列，结果队列，进程锁，日志
cmd_queue = Queue()
result_queue = Queue()
lock = Lock()
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


class Server(BaseSocket):
    def __init__(self, host, port):
        context = zmq.Context()
        self.receiver = context.socket(zmq.PULL)
        try:
            self.receiver.bind("tcp://%s:%i" % (host, port))
        except:
            sys.exit(0)
        self.sender = context.socket(zmq.PUSH)
        try:
            self.sender.bind("tcp://%s:%i" % (host, port+1))
        except:
            sys.exit(0)


class Master(Server):
    def __init__(self, *args, **kwargs):
        super(Master, self).__init__(*args)

        class SlaveNodesDict(dict):
            def get_by_state(self, state):
                return [c for c in six.itervalues(self) if c.state == state]

            @property
            def ready(self):
                return self.get_by_state(STATE_INIT)

            @property
            def running(self):
                return self.get_by_state(STATE_RUNNING)

        self.cmd_queue = kwargs['cmd_queue']
        self.result_queue = kwargs['result_queue']
        self.clients = SlaveNodesDict()
        self.greenlet = Group()
        # 加载gevent协程，一个用于接收web端发来的指令消息，另一个用于接收slave反馈的消息
        self.greenlet.spawn(self.master_listener).link_exception(callback=self.noop)
        self.greenlet.spawn(self.master_cmd).link_exception(callback=self.noop)

        def on_quitting():
            self.quit()
        events.quitting += on_quitting

    # 接收web端的cmd_queue队列指令消息并派发给相应的slave
    def master_cmd(self):
        while True:
            if not self.cmd_queue.empty():
                while not self.cmd_queue.empty():
                    cmd = self.cmd_queue.get()
                logger.info('Master: Get new command - [%s]' % cmd['type'])
                if cmd['type'] == 'get_clients':
                    del_clients = []
                    client_list = []
                    for client in six.itervalues(self.clients):
                        if client.last_time + 61 > time.time():
                            client_list.append({"id": client.id, "state": client.state, "slave_num": client.slave_num})
                        else:
                            del_clients.append(client.id)
                    for i in del_clients:
                        print(i)
                        del self.clients[i]
                    if client_list:
                        self.result_queue.put(client_list)
                    else:
                        self.result_queue.put('0')
                elif cmd['type'] == 'sent_script':
                    script_data = {"filename": cmd['filename'], "script": cmd['script']}
                    for client in six.itervalues(self.clients):
                        self.send(Message("send_script", script_data, cmd['client_id']))
                    self.result_queue.put("OK")
                elif cmd['type'] == 'run':
                    data = {"filename": cmd['filename'], "num": cmd['num']}
                    for client in six.itervalues(self.clients):
                        self.send(Message("run", data, cmd['client_id']))
                        # if client.id == cmd['client_id']:
                        #     client.state = STATE_RUNNING
                elif cmd['type'] == 'stop':
                    for client in six.itervalues(self.clients):
                        self.send(Message("stop", None, cmd['client_id']))
                        # if client.id == cmd['client_id']:
                        #     client.state = STATE_INIT
                elif cmd['type'] == 'get_filelist':
                    for client in six.itervalues(self.clients):
                        self.send(Message("get_filelist", None, cmd['client_id']))
                elif cmd['type'] == 'get_psinfo':
                    for client in six.itervalues(self.clients):
                        self.send(Message("get_psinfo", None, cmd['client_id']))
                elif cmd['type'] == 'clear_folder':
                    for client in six.itervalues(self.clients):
                        self.send(Message("clear_folder", None, cmd['client_id']))
            gevent.sleep(1)

    # 接收slave上报的消息并反馈到result_queue
    def master_listener(self):
        while True:
            msg = self.recv()
            logger.info('Master: Get new msg from slave - [%s]' % msg.type)
            if msg.type == "slave_ready":
                id = msg.node_id
                self.clients[id] = SlaveNode(id)
                self.clients[id].slave_num = msg.data
                self.clients[id].last_time = time.time()
                if msg.data == 0:
                    self.clients[id].state = STATE_INIT
                else:
                    self.clients[id].state = STATE_RUNNING
                logger.info(
                    "Client %r reported as ready. Currently %i clients is running; %i clients ready to swarm." % (id, len(self.clients.running), len(self.clients.ready)))
            elif msg.type == "quit":
                if msg.node_id in self.clients:
                    del self.clients[msg.node_id]
                    logger.info("Client %r is exit. Currently %i clients connected." % (msg.node_id, len(self.clients.ready)))
            elif msg.type == "file_list":
                self.result_queue.put({"client_id": msg.node_id, "file_list": msg.data})
            elif msg.type == "slave_num":
                self.clients[msg.node_id].slave_num = msg.data
                if msg.data == 0:
                    self.clients[msg.node_id].state = STATE_INIT
                    self.result_queue.put("None")
                else:
                    self.clients[msg.node_id].state = STATE_RUNNING
                    self.result_queue.put("OK")
            elif msg.type == "psinfo":
                self.result_queue.put({"client_id": msg.node_id, "psinfo": msg.data})
            elif msg.type == "clear_folder":
                self.result_queue.put({"client_id": msg.node_id, "clear_folder": "OK"})

    def quit(self):
        for client in six.itervalues(self.clients):
            logger.info("Master: send quit message to client - %s" % client.id)
            self.send(Message("quit", None, client.id))
        self.greenlet.kill(block=True)


class SlaveNode(object):
    def __init__(self, id, state=STATE_INIT, slave_num=0):
        self.id = id
        self.state = state
        self.slave_num = slave_num
        self.last_time = time.time()


def shutdown(code=0):
    logger.info("Shutting down (exit code %s), bye." % code)
    events.quitting.fire()
    sys.exit(code)


# install SIGTERM handler
def sig_term_handler():
    logger.info("Got SIGTERM signal")
    shutdown(0)


def start(cmd_queue, result_queue):
    master_host = "0"  # socket.gethostbyname(socket.gethostname())
    port = 6666
    server = Master(master_host, port, cmd_queue=cmd_queue, result_queue=result_queue)
    logger.info('Master is listening at %s:%i' % (master_host, port))
    gevent.signal(signal.SIGTERM, sig_term_handler)

    try:
        server.greenlet.join()
        # gevent.joinall(server.greenlet.greenlets)
        code = 0
        shutdown(code=code)
    except KeyboardInterrupt as e:
        shutdown(1)


def start_master():
    p_master = multiprocessing.Process(target=start, args=(cmd_queue, result_queue, ))
    p_master.daemon = True
    p_master.start()
    return p_master


master_server = start_master()


if __name__ == '__main__':
    print "Please use python slave.py to load client!"
