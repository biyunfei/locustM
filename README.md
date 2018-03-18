# locustM
It is a web tool for schedule test of distributed locust clients;
To run it on you computer, you should be install locustio==v0.8.1, Django==1.11.10, psutil==5.4.3 as first, now it support in python 2.x; or you can use the docker images which I maked in the docker hub: https://hub.docker.com/r/biyunfei/locust/
There are two parts of this tools: Master and Slave;
Master:
       In CMD line, at . folder run: 
       python manage.py runserver 0:8000
       Open http://localhost:8000 to get in the web tool for control you locust clients; http://localhost:8089 to locust web spawn mode;
       Detail information can see in the source code;
Slave:
      For each locust client, in CMD line: at ./hztest/rpc folder run:
      python slave.py MASTER_IP
