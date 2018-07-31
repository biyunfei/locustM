# -*- coding: UTF-8 -*-
r"""
本Locust压测调试系统分三块：web，master, slave;
web(views.py): 用于对WEB交互的调试指令进行处理响应，把WEB操作通过命令队列(cmd_queue)发送给master去分发给相应的slave客户端执行，然后通过结果队列(result_queue)接收结果；
master.py: 负责从web接收队列请求，并通过相应的slave处理；
slave.py: 接收master的请求进行处理，包括：状态，资源，脚本文件，locust客户端启停, 并反馈结果;
"""

from django.shortcuts import render
from .rpc.master import cmd_queue, result_queue, lock, logger
import time
import os.path
import os
from subprocess import Popen
import psutil

locust_script = './hztest/rpc/script/internal-test.py'  # Locust master script file
script_filename = 'internal-test.py'  # default script file name of client if don't select file from web
locust_status = 'stop'
p = None


# 等待结果消息队列返回数据
def wait_result():
    retry = 0
    result = None
    while result_queue.empty():
        time.sleep(1)
        retry = retry + 1
        if retry > 10:
            logger.info('Web server: retry max times, no clients response;')
            break
        logger.info('Web server: command response is none, get in next 1s...')
    while not result_queue.empty():
        result = result_queue.get()
    return result


# 刷新客户端列表
def refresh_clients():
    logger.info('Web server: send new command - [get_clients]')
    cmd_queue.put({'type': 'get_clients'})
    clients = []
    q = wait_result()
    if q:
        if q != '0':
            logger.info('Web server: command - [get_clients] - Got response!')
            print(q)
            clients = q
    return {'num': len(clients), 'clients': clients}


# 发送压测脚本到客户端
def send_script(client_id, filename, script):
    logger.info('Web server: send new command - [send_script(%s)]' % client_id)
    cmd_queue.put({'type': 'sent_script', 'client_id': client_id, 'filename': filename, 'script': script})
    q = wait_result()
    if q:
        if q == 'OK':
            logger.info('Web server: command - [send_script(%s)] - Got response!' % client_id)
            return 'Script send to %s successful!' % client_id
    return 'Script send to %s failed!' % client_id


# 启动客户端压测进程
def run(client_id, num, filename):
    logger.info('Web server: send new command - [run locust slave(%s)]' % client_id)
    cmd_queue.put({'type': 'run', 'client_id': client_id, 'filename': filename, 'num': num})
    q = wait_result()
    if q:
        if q == 'OK':
            logger.info('Web server: command - [run locust slave(%s)] - Got response!' % client_id)
            return 'Client %s run successful!' % client_id
    return 'Client %s run failed!' % client_id


# 停止客户端压测进程
def stop(client_id):
    logger.info('Web server: send new command - [stop locust slave(%s)]' % client_id)
    cmd_queue.put({'type': 'stop', 'client_id': client_id})
    q = wait_result()
    if q:
        if q == 'None':
            logger.info('Web server: command - [stop locust slave(%s)] - Got response!' % client_id)
            return 'Client %s stop successful!' % client_id
    return 'Client %s stop failed!' % client_id


# 获取客户端压测脚本文件列表
def get_filelist(client_id):
    logger.info('Web server: send new command - [get file list(%s)]' % client_id)
    cmd_queue.put({'type': 'get_filelist', 'client_id': client_id})
    q = wait_result()
    if q:
        if q['client_id'] == client_id:
            if q['file_list']:
                logger.info('Web server: command - [get file list(%s)] - Got response!' % client_id)
                return {'id': client_id, 'file_list': q['file_list']}
    return {'id': client_id, 'file_list': ''}


# 获取客户端系统资源状态
def get_psinfo(client_id):
    logger.info('Web server: send new command - [get ps info(%s)]' % client_id)
    cmd_queue.put({'type': 'get_psinfo', 'client_id': client_id})
    q = wait_result()
    if q:
        if q['client_id'] == client_id:
            logger.info('Web server: command - [get ps info(%s)] - Got response!' % client_id)
            return {'id': client_id, 'psinfo': q['psinfo']}
    return {'id': client_id, 'psinfo': ''}


# 清除客户端压测脚本文件夹
def clear_folder(client_id):
    logger.info('Web server: send new command - [clear folder(%s)]' % client_id)
    cmd_queue.put({'type': 'clear_folder', 'client_id': client_id})
    q = wait_result()
    if q:
        if q['client_id'] == client_id:
            if q['clear_folder'] == 'OK':
                logger.info('Web server: command - [clear folder(%s)] - Got response!' % client_id)
                return 'Client %s script folder cleared!' % client_id
    return 'Failed to clear client %s script folder!' % client_id


# 参考停止子进程代码，暂时不用
def reap_children(timeout=3):
    global p
    "Tries hard to terminate and ultimately kill all the children of this process."
    def on_terminate(proc):
        print("process {} terminated with exit code {}".format(proc, proc.returncode))

    procs = p.children()
    # send SIGTERM
    for proc in procs:
        proc.terminate()
    gone, alive = psutil.wait_procs(procs, timeout=timeout, callback=on_terminate)
    if alive:
        # send SIGKILL
        for proc in alive:
            print("process {} survived SIGTERM; trying SIGKILL" % p)
            proc.kill()
        gone, alive = psutil.wait_procs(alive, timeout=timeout, callback=on_terminate)
        if alive:
            # give up
            for proc in alive:
                print("process {} survived SIGKILL; giving up" % proc)


# Web交互处理
def hello(request):
    # 使用进程锁每个WEB请求独占，规避多用户在WEB下操作时冲突
    with lock:
        global locust_status, p, locust_script, script_filename
        context = dict()
        context['filelist'] = []
        context['hello'] = 'Clients list OK!'
        context['script'] = ''
        context['text'] = ''
        context['clients'] = refresh_clients()
        if request.method == 'POST':
            print(request.POST)
            if context['clients']['num'] > 0:
                for client in context['clients']['clients']:
                    # 启动/停止压测Slave
                    name = 'run%s' % client['id']
                    if name in request.POST:
                        if request.POST.get(name, None) == 'ready':
                            # 启动客户端压测进程
                            file_select = 'fileselect%s' % client['id']
                            num = request.POST.get('num%s' % client['id'], None)
                            if file_select in request.POST:
                                file_name = request.POST.getlist(file_select)
                            else:
                                # 如果未选择压测脚本，则使用默认脚本名
                                file_name = [script_filename]
                            context['hello'] = run(client['id'], num, file_name)
                            context['clients'] = refresh_clients()
                            for c in context['clients']['clients']:
                                if c['id'] == client['id']:
                                    if c['slave_num'] == 0:
                                        context['hello'] = 'Client %s run error, please check you script file %s is valid!' % (client['id'], file_name)
                                    else:
                                        context['hello'] = 'Client %s run OK, script file is %s!' % (client['id'], file_name)
                        else:
                            # 停止客户端压测进程
                            context['hello'] = stop(client['id'])
                            context['clients'] = refresh_clients()
                        break
                    # 获取客户端的脚本文件列表
                    name = 'filelist%s' % client['id']
                    if name in request.POST:
                        file_list = get_filelist(client['id'])
                        if file_list['id'] == client['id']:
                            context['filelist'].append(file_list)
                        break
                    # 清除客户端脚本文件夹
                    name = 'clear%s' % client['id']
                    if name in request.POST:
                        context['hello'] = clear_folder(client['id'])
                        break
                    # 发送压测脚本到客户端
                    name = 'send%s' % client['id']
                    if name in request.POST:
                        if request.FILES.get(client['id'], None):
                            # 将所选脚本文件内容发给客户端，文件控件可以多选
                            script_files = request.FILES.getlist(client['id'], None)
                            for script_file in script_files:
                                if os.path.splitext(script_file.name)[1] != '.py':
                                    context['hello'] = "File name should be end with .py!"
                                else:
                                    script = script_file.read()
                                    context['hello'] = send_script(client['id'], script_file.name, script)
                        elif 'text%s' % client['id'] in request.POST:
                            # 将页面上编辑后的脚本内容发送给客户端，前提为未选择文件
                            context['hello'] = send_script(client['id'], request.POST.get('filename', None), request.POST.get('text%s' % client['id'], None))
                        break
                    # 编辑压测脚本(如果多选，则只编辑列表中最后一个文件)
                    name = 'edit%s' % client['id']
                    if name in request.POST:
                        if request.FILES.get(client['id'], None):
                            script_file = request.FILES.get(client['id'], None)
                            context['script'] = script_file.read()
                            context['text'] = client['id']
                            context['filename'] = script_file.name
                        break

                # 获取客户端系统资源利用率
                if request.POST.get('mon_clients', False):
                    psinfo = []
                    for c in context['clients']['clients']:
                        psinfo.append(get_psinfo(c['id']))
                    context['psinfos'] = psinfo
                    context['mon_flag'] = "Checked"
                    context['hello'] = "Clients's monitor data refresh OK！"
                else:
                    context['mon_flag'] = ""

            # 启动/停止Locust Master
            if 'start_locust' in request.POST or 'stop_locust' in request.POST:
                if locust_status == 'run':
                    # 停止Locust Master
                    if p is not None:
                        logger.info("Server: try to stop the locust master!")
                        if p.poll() is None:
                            try:
                                # 先停止子进程再停止自身进程，Popen在容器中启动会有两个进程，一个是shell进程，另一个是应用进程
                                procs = p.children()
                                for proc in procs:
                                    proc.terminate()
                                p.terminate()
                                p.wait()
                                p = None
                                logger.info("Server: locust master stopped!")
                            except:
                                pass
                    if p is None:
                        context['hello'] = 'Locust master has been stopped!'
                        logger.info("Server: locust master is stopped!")
                        locust_status = 'stop'
                        # 通知各客户端停止压测
                        for client in context['clients']['clients']:
                            stop(client['id'])
                        context['clients'] = refresh_clients()
                else:
                    # 启动Locust的Master模式
                    p = psutil.Popen('locust -f %s --master --no-reset-stats' % locust_script, shell=True, stdout=None, stderr=None)
                    time.sleep(1)
                    if p.poll() is not None:
                        # 判断Locust进程是否启动失败并给出提示
                        if p.poll() != 0:
                            logger.info("Server: failed to start locus master...")
                            context['hello'] = 'Failed to start locust master! Please check script file: %s' % locust_script
                            p = None
                    else:
                        # 成功启动Locust的Master模式进程
                        print("Locust Master process PID:{}".format(p.pid))
                        logger.info("Server: locust master is running...")
                        context['hello'] = 'Locust master has been running!'
                        locust_status = 'run'
        context['locust'] = locust_status
        host = request.get_host()
        context['host'] = host.split(':')[0]
        return render(request, 'hello.html', context)


