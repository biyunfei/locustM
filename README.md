# locustM
It is a web tool for schedule locust test of distributed locust clients;

To run it on you computer, you should be install locustio, Django==1.11.10, psutil==5.4.3 by PIP as first, now it support in python 2.x; or you can use the docker images which in the next;

There are two parts of this tools: Master and Slave;

Master:
		In CMD line, at . folder run: 

		python manage.py runserver 0:8000

		Open http://localhost:8000 to get in the web tool for control you locust clients; http://localhost:8089 to locust web spawn mode;

		Detail information can see in the source code;

Slave:
		For each locust client, in CMD line: at ./hztest/rpc folder run:
		
		python slave.py MASTER_IP

# Make docker images:
    docker build -t locust -f dockerfile_locust .
    docker build -t locust:master -f dockerfile_master .
    docker build -t locust:slave -f dockerfile_slave .

# Run docker images:
**Master:**
	docker run -p 8000:8000 -p 6666:6666 -p 6667:6667 -p 5557:5557 -p 5558:5558 -p 8089:8089 -it --rm locust:master
**Slave:**
	docker run -e HOST={MASTER_IP} -it --rm locust:slave
