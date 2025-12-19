#!/usr/bin/env python

import random
import json
import argparse
import sys
from time import localtime, strftime
from kubernetes import client, config, watch
from kubernetes.client.exceptions import ApiException
import pulp
import numpy as np
import subprocess

from helper_monitor import SchedulerMonitor, get_node_usage_metrics

timestamp_format = "%Y-%m-%d %H:%M:%S"
scheduler_name = "custom-scheduler"

# Use load_incluster_config when deploying scheduler from within the cluster. Otherwise use load_kube_config
config.load_kube_config()
v1 = client.CoreV1Api()

monitor = SchedulerMonitor(namespace="boutique")

#Global History
history = []
event_counter = 0
scheduled_counter = 0

def get_node_resources():
    resources = {}
    for node in v1.list_node().items:
        name = node.metadata.name
        allocatable = node.status.allocatable
        resources[name] = {
            "cpu": float(allocatable["cpu"].rstrip("m")) / 1000 if "m" in allocatable["cpu"] else float(allocatable["cpu"]),
            "mem": float(allocatable["memory"].rstrip("Ki")) / (1024*1024),
        }
    return resources

def get_timestamp():
    return strftime(timestamp_format, localtime())

def get_node_available_resources():
    config.load_kube_config()
    v1 = client.CoreV1Api()

    # Get allocatable
    allocs = {}
    for node in v1.list_node().items:
        name = node.metadata.name
        alloc = node.status.allocatable
        cpu = float(alloc["cpu"].rstrip("m")) / 1000 if "m" in alloc["cpu"] else float(alloc["cpu"])
        mem = float(alloc["memory"].rstrip("Ki")) / (1024*1024)
        allocs[name] = {"cpu": cpu, "mem": mem}

    # Get usage from metrics-server
    result = subprocess.run(["kubectl", "top", "nodes"], capture_output=True, text=True)
    lines = result.stdout.splitlines()[1:]  # skip header
    usage = {}
    for line in lines:
        parts = line.split()
        name = parts[0]
        cpu_used = float(parts[1].rstrip("m")) / 1000
        mem_used = float(parts[3].rstrip("Mi")) / 1024
        usage[name] = {"cpu": cpu_used, "mem": mem_used}

    # Subtract usage from allocatable
    available = {}
    for name in allocs:
        if name in usage:
            available[name] = {
                "cpu": allocs[name]["cpu"] - usage[name]["cpu"],
                "mem": allocs[name]["mem"] - usage[name]["mem"],
            }
    return available

def nodes_available():
    ready_nodes = []
    for n in v1.list_node().items:
        # This loops over the nodes available. n is the node. We are trying to schedule the pod on one of those nodes.
        for status in n.status.conditions:
            if status.status == "True" and status.type == "Ready":
                ready_nodes.append(n.metadata.name)
    return ready_nodes

def extract_pod_requests(pod):
    """
    Extract CPU (cores), memory (MiB), and storage (GiB) requests from a pod spec.
    Returns a dict: {"cpu": float, "mem": float, "storage": float}
    """
    cpu_req = 0.0
    mem_req = 0.0
    storage_req = 0.0

    # Each container may have requests
    for container in pod.spec.containers:
        if container.resources and container.resources.requests:
            reqs = container.resources.requests
            if "cpu" in reqs:
                cpu_val = reqs["cpu"]
                # CPU can be in millicores ("500m") or cores ("1")
                if cpu_val.endswith("m"):
                    cpu_req += float(cpu_val.rstrip("m")) / 1000.0
                else:
                    cpu_req += float(cpu_val)

            if "memory" in reqs:
                mem_val = reqs["memory"]
                # Memory can be in Ki, Mi, Gi
                if mem_val.endswith("Ki"):
                    mem_req += float(mem_val.rstrip("Ki")) / 1024.0
                elif mem_val.endswith("Mi"):
                    mem_req += float(mem_val.rstrip("Mi"))
                elif mem_val.endswith("Gi"):
                    mem_req += float(mem_val.rstrip("Gi")) * 1024.0
                else:
                    mem_req += float(mem_val)  # assume MiB

    # Storage requests come from PVCs
    if pod.spec.volumes:
        for vol in pod.spec.volumes:
            if vol.persistent_volume_claim:
                # You’d need to query the PVC object to get its request
                pvc_name = vol.persistent_volume_claim.claim_name
                # Example: fetch PVC and read storage request
                try:
                    pvc = v1.read_namespaced_persistent_volume_claim(
                        pvc_name, pod.metadata.namespace
                    )
                    if pvc.spec.resources.requests and "storage" in pvc.spec.resources.requests:
                        storage_val = pvc.spec.resources.requests["storage"]
                        if storage_val.endswith("Gi"):
                            storage_req += float(storage_val.rstrip("Gi"))
                        elif storage_val.endswith("Mi"):
                            storage_req += float(storage_val.rstrip("Mi")) / 1024.0
                except Exception:
                    pass

    return {"cpu": cpu_req, "mem": mem_req, "storage": storage_req}

# You can use "default" as a namespace.
def scheduler(pod_name, node, namespace="boutique"):
    target = client.V1ObjectReference()
    target.kind = "Node"
    target.apiVersion = "v1"
    target.name = node
    meta = client.V1ObjectMeta()
    meta.name = pod_name
    body = client.V1Binding(target=target)
    body.metadata = meta
    return v1.create_namespaced_binding(namespace, body, _preload_content=False)

#History Management
def update_history(event_type, service_name, node):
    global event_counter, history
    event_counter += 1
    history.append({
        "event_id": event_counter,
        "timestamp": get_timestamp(),
        "event_type": event_type,   # "scheduled" or "terminated"
        "service_name": service_name,
        "node": node
    })

def current_node_load():
    """Return dict of node -> number of active pods from history."""
    load = {}
    for entry in history:
        if entry["event_type"] == "scheduled":
            load[entry["node"]] = load.get(entry["node"], 0) + 1
        elif entry["event_type"] == "terminated":
            load[entry["node"]] = max(load.get(entry["node"], 0) - 1, 0)
    return load

#Begin definitions of pod placement algorithms:
#LP Relaxation
def lp_relaxation(nodes, pod_request):
    # nodes: dict {node: {"cpu": value, "mem": value}}
    # pod_request: {"cpu": value, "mem": value}
    #print(nodes)
    prob = pulp.LpProblem("PodPlacement", pulp.LpMaximize)
    x = {n: pulp.LpVariable(f"x_{n}", lowBound=0, upBound=1) for n in nodes}

    # Objective: maximize weighted fit
    prob += pulp.lpSum([x[n] * (nodes[n]["cpu"] + nodes[n]["mem"]) for n in nodes])

    # Constraints: pod must be placed somewhere
    prob += pulp.lpSum([x[n] for n in nodes]) == 1

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    # Pick node with highest fractional assignment
    best_node = max(nodes, key=lambda n: x[n].value())
    return best_node

#History-Based Fairness-Aware Relaxation
def fairness_relaxation(nodes, pod_request, history):
    """
    nodes: dict {node: {"cpu": value, "mem": value}}
    pod_request: {"cpu": value, "mem": value}
    history: list of event dicts (scheduled/terminated events)
    """
    # Build current load from history
    #print(history)
    load = {}
    for entry in history:
        if entry["event_type"] == "scheduled":
            load[entry["node"]] = load.get(entry["node"], 0) + 0.01
        #elif entry["event_type"] == "terminated":
        #    load[entry["node"]] = max(load.get(entry["node"], 0) - 1, 0)

    scores = {}
    for n in nodes:
        penalty = load.get(n, 0)  # fairness penalty based on active pods
        remaining_cpu = nodes[n]["cpu"] # - pod_request["cpu"]
        remaining_mem = nodes[n]["mem"] # - pod_request["mem"]

        if remaining_cpu < 0 or remaining_mem < 0:
            scores[n] = float("-inf")  # cannot fit
        else:
            # Score = remaining capacity minus fairness penalty
            scores[n] = (remaining_cpu + remaining_mem) - penalty
    #print(scores)

    return max(scores, key=scores.get)

#Least Allocated (CPU and Memory are currently summed. This can be changed to
#                       Improve Accuracy)
def least_allocated(nodes):
    return max(nodes, key=lambda n: nodes[n]["cpu"] + nodes[n]["mem"])

#Requested To Capacity Ratio
def requested_to_capacity_ratio(nodes, pod_request):
    scores = {}
    for n in nodes:
        cpu_ratio = pod_request["cpu"] / nodes[n]["cpu"] if nodes[n]["cpu"] > 0 else float("inf")
        mem_ratio = pod_request["mem"] / nodes[n]["mem"] if nodes[n]["mem"] > 0 else float("inf")
        scores[n] = cpu_ratio + mem_ratio
    return max(scores, key=scores.get)  # lower ratio = better fit

def dot_product_scoring(nodes, pod_request):
    pod_vec = np.array([pod_request["cpu"], pod_request["mem"]])
    scores = {}
    for n in nodes:
        node_vec = np.array([nodes[n]["cpu"], nodes[n]["mem"]])
        scores[n] = np.dot(pod_vec, node_vec)
    return max(scores, key=scores.get)


def main():
    if len(sys.argv) != 3:
        print("Usage: python custom_scheduler.py <algorithm> <output_dir>")
        sys.exit(1)

    output_dir = sys.argv[2]   # take the first argument
    print(f"Saving reports to: {output_dir}")

    try:
        algorithm = int(sys.argv[1])   # convert to int
    except ValueError:
        print("Error: algorithm must be an integer")
        sys.exit(1)

    if (algorithm < 1) or (algorithm > 5):
        print("Usage: Algorithm must be within 1-5")
        sys.exit(2)

    print("Custom-Scheduler: {}: Starting custom scheduler...".format(get_timestamp()))
    w = watch.Watch()
    idle_timeout_sec = 30

    while True:
        try:
            for event in w.stream(v1.list_namespaced_pod, "boutique"):
                # We get an "event" whenever a pod needs to be scheduled
                # and event['object'].spec.scheduler_name == scheduler_name:
                pod = event['object']
                pod_name = pod.metadata.name
                service_name = pod.metadata.labels.get("app") if pod.metadata.labels else pod.metadata.name

                # Update allocatable (example)
                nodes = get_node_available_resources()
                #print(nodes)
                # Augment with storage allocatable if available
                monitor.update_node_allocatable(nodes)

                usage = get_node_usage_metrics()
                monitor.update_node_usage(usage)


                if pod.status.phase == "Pending" and pod.spec.scheduler_name == scheduler_name:
                    try:
                        

                        pod_name = pod.metadata.name
                        pod_request = extract_pod_requests(pod)
                        pod_req_cpu = pod_request["cpu"]
                        pod_req_mem = pod_request["mem"]
                        pod_req_storage = pod_request["storage"]

                        #nodes = get_node_resources()
                        # Simple heuristic: pick node with most free CPU
                        #print("Node Resources:\n", nodes)
                        #best_node = max(nodes, key=lambda n: nodes[n]["cpu"])

                        #Random Choice for Testing
                        #nodes_list = list(set(nodes_available()))
                        #random_node = random.choice(nodes_list)

                        if algorithm == 1:
                            best_node = lp_relaxation(nodes, pod_request)
                        elif algorithm == 2:
                            best_node = fairness_relaxation(nodes, pod_request, history)
                        elif algorithm == 3:
                            best_node = least_allocated(nodes)
                        elif algorithm == 4:
                            best_node = requested_to_capacity_ratio(nodes, pod_request)
                        elif algorithm == 5:
                            best_node = dot_product_scoring(nodes, pod_request)
                        else:
                            print("Usage: Algorithm must be within 1-5")
                            sys.exit(2)

                        res = scheduler(pod_name, best_node)
                        print("mark1")
                        monitor.mark_pod_request_observed(pod_name, service_name)

                        monitor.record_schedule_event(
                            pod_name=pod_name,
                            service_name=service_name,
                            node=best_node,
                            cpu_req=pod_req_cpu,
                            mem_req=pod_req_mem,
                            storage_req=pod_req_storage
                        )
                        print("mark2")
                        update_history("scheduled", service_name, best_node)
                        print("Custom-Scheduler: {}: Scheduled {} (service={}) to {} "
                                "(cpu={} cores, mem={} MiB, storage={} GiB)".format(
                                get_timestamp(), pod_name, service_name, best_node,
                                pod_req_cpu, pod_req_mem, pod_req_storage
                            ))
                        global scheduled_counter
                        scheduled_counter = scheduled_counter + 1

                    except client.rest.ApiException as e:
                        pass
                        #print("Custom-Scheduler: {}: An exception occurred: {}".format(get_timestamp(), json.loads(e.body)['message']))
                elif pod.status.phase in ["Succeeded", "Failed"]:
                    node_name = pod.spec.node_name
                    # If you know the storage request for this pod, pass it; else None
                    monitor.record_termination_event(pod_name, service_name, node_name, storage_req=None)
                    update_history("terminated", service_name, node_name)
                    #print("Custom-Scheduler: {}: Pod {} (service={}) terminated on {}".format(
                    #    get_timestamp(), pod_name, service_name, node_name))

                if monitor.should_stop_on_plateau(idle_timeout_sec):
                    print(f"No new pods requested for {idle_timeout_sec}s. Stopping scheduler.")
                    break

            monitor.finalize_and_plot(scheduled_counter, output_dir=output_dir)
            break
        except ApiException as e:
            if e.status == 410:
                print("Watch expired (resourceVersion too old). Restarting watch...")

                pods = v1.list_namespaced_pod(namespace="boutique", resource_version="0")
                for pod in pods.items:
                    if pod.status.phase == "Pending" and pod.spec.scheduler_name == scheduler_name and pod.spec.node_name is None:
                        # We get an "event" whenever a pod needs to be scheduled
                        # and event['object'].spec.scheduler_name == scheduler_name:
                        pod = event['object']
                        pod_name = pod.metadata.name
                        service_name = pod.metadata.labels.get("app") if pod.metadata.labels else pod.metadata.name

                        # Update allocatable (example)
                        nodes = get_node_available_resources()
                        #print(nodes)
                        # Augment with storage allocatable if available
                        monitor.update_node_allocatable(nodes)

                        usage = get_node_usage_metrics()
                        monitor.update_node_usage(usage)


                        if pod.status.phase == "Pending" and pod.spec.scheduler_name == scheduler_name:
                            try:

                                pod_name = pod.metadata.name
                                pod_request = extract_pod_requests(pod)
                                pod_req_cpu = pod_request["cpu"]
                                pod_req_mem = pod_request["mem"]
                                pod_req_storage = pod_request["storage"]

                                #nodes = get_node_resources()
                                # Simple heuristic: pick node with most free CPU
                                #print("Node Resources:\n", nodes)
                                #best_node = max(nodes, key=lambda n: nodes[n]["cpu"])

                                #Random Choice for Testing
                                #nodes_list = list(set(nodes_available()))
                                #random_node = random.choice(nodes_list)

                                if algorithm == 1:
                                    best_node = lp_relaxation(nodes, pod_request)
                                elif algorithm == 2:
                                    best_node = fairness_relaxation(nodes, pod_request, history)
                                elif algorithm == 3:
                                    best_node = least_allocated(nodes)
                                elif algorithm == 4:
                                    best_node = requested_to_capacity_ratio(nodes, pod_request)
                                elif algorithm == 5:
                                    best_node = dot_product_scoring(nodes, pod_request)
                                else:
                                    print("Usage: Algorithm must be within 1-5")
                                    sys.exit(2)

                                res = scheduler(pod_name, best_node)
                                
                                monitor.mark_pod_request_observed(pod_name, service_name)

                                monitor.record_schedule_event(
                                    pod_name=pod_name,
                                    service_name=service_name,
                                    node=best_node,
                                    cpu_req=pod_req_cpu,
                                    mem_req=pod_req_mem,
                                    storage_req=pod_req_storage
                                )
                        
                                update_history("scheduled", service_name, best_node)
                                print("Custom-Scheduler: {}: Scheduled {} (service={}) to {} "
                                        "(cpu={} cores, mem={} MiB, storage={} GiB)".format(
                                        get_timestamp(), pod_name, service_name, best_node,
                                        pod_req_cpu, pod_req_mem, pod_req_storage
                                    ))
                                #global scheduled_counter
                                scheduled_counter = scheduled_counter + 1

                            except client.rest.ApiException as e:
                                pass
                                #print("Custom-Scheduler: {}: An exception occurred: {}".format(get_timestamp(), json.loads(e.body)['message']))
                        elif pod.status.phase in ["Succeeded", "Failed"]:
                            node_name = pod.spec.node_name
                            # If you know the storage request for this pod, pass it; else None
                            monitor.record_termination_event(pod_name, service_name, node_name, storage_req=None)
                            update_history("terminated", service_name, node_name)
                            #print("Custom-Scheduler: {}: Pod {} (service={}) terminated on {}".format(
                            #    get_timestamp(), pod_name, service_name, node_name))

                        if monitor.should_stop_on_plateau(idle_timeout_sec):
                            print(f"No new pods requested for {idle_timeout_sec}s. Stopping scheduler.")
                            break

                continue  # restart outer loop
            else:
                raise



if __name__ == '__main__':
    main()