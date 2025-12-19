=======================================
Fairness Algorithms for 
Serverless Function “Pod” Placement
=======================================

Purpose:
This project implements a custom scheduler for a kubernetes environment and plots 
the fairness metrics pod scaling episodes.


=======
Setup
=======

First, setup a cluster of any number of nodes (our solution was tested on 4 nodes,
each running Ubuntu 22.04). Our nodes were deployed using CloudLab.

Next, set up the Kubernetes environment, run online boutique, and install 
dependencies for the custom scheduler using the following steps:

*This setup uses the Lab4 and Lab5 guides from:
https://github.com/ShixiongQi/uky-cs687/blob/main/ *

1. From Lab4, do README.md steps 2-7 to set up kubernetes cluster
2. From Lab5, do README.md steps 0-1 to deploy Online Boutique
3. From Lab5, do README.md step 3.d (with the following edit) to install Graphana
	-Replace the last line of first code block with:
		"kubectl -n monitoring rollout status statefulset/prometheus-kps-kube-prometheus-stack-prometheus"
	*You may need to wait a little bit before pods start being requested
4. Open another session in the master node, and run
	kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090
	...to expose Prometheus for the custom scheduler
5. scp all script files from the code submission to the master node.
	-Once the files are copied, make a subdirectory called "outputs" for graphs
		to be saved to
	-You may need to apply execution permissions to bash scripts using
		chmod u+x [script file]
6. install screen using:
	sudo apt update
	sudo apt install -y screen
7. Install the following dependecies using pip:
	pip install kubernetes
	pip install pulp
	pip install numpy
	pip install requests
	pip install pandas
	pip install matplotlib


=================
Included Files
=================

custom_scheduler.py - main scheduler script
helper_monitor.py - contains helper functions used by custom_scheduler.py
kubernetes-manifests-frontend.yaml - the kubernetes manifest for only scheduling the frontend
kubernetes-manifests-multiple.yaml - the kubernetes manifest for scheduling multiple pod types
RunOneTest.sh - bash script to perform one automated run of the custom scheduler

=======
Usage
=======

**When running the custom scheduler, make sure the script runs on the master node 
	of the cluster**

custom_scheduler.py   **Not Recommended**
python custom_scheduler.py [algorithm] [num]
	algorithm - algorithm to run, represented as a number
		1 = LP Relaxation
		2 = Fairness Relaxation
		3 = Least Allocated
		4 = Requested-to-Capacity Ratio
		5 = Dot Product Scoring
		
	num - number of pod replicas to scale to
	
	*If running the Python script standalone, make sure to follow these steps:
		- apply the desired custom kubernetes manifest
			kubectl apply -f [.yaml file]
		- scale all tested pod types to 1
			kubectl scale deployment [pod type] --replicas=1 -n boutique
		- start the custom scheduler script
		- scale all tested pod types to the desired amount 		
		
		*Note: When scheduling multiple pod types, the affected pod types are:
			recommendationservice
			frontend
			paymentservice
			productcatalogservice
			cartservice
			redis-cart
			loadgenerator
			currencyservice
			shippingservice
			adservice

RunOneTest.sh
./RunOneTest.sh [algorithm] [# of replicas] [pods to scale]
	algorithm - algorithm to run
		Accepted inputs:
			least_allocated
			requested_to_capacity_ratio
			dot_product_scoring
			lp_relaxation
			fairness_relaxation
	
	# of replicas - number of pod replicas to scale to
	
	pods to scale - whether to scale multiple pod types or just the frontend
		Accepted inputs:
			frontend
			multiple