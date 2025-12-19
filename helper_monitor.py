# helper_monitor.py

import time
import math
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from kubernetes import client

import requests
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

PROM_URL = "http://localhost:9090/"

@dataclass
class EventRecord:
    timestamp: float
    event_id: int
    event_type: str  # "requested", "scheduled", "terminated"
    pod_name: str
    service_name: str
    node: Optional[str] = None
    cpu_req: Optional[float] = None  # cores
    mem_req: Optional[float] = None  # MiB
    storage_req: Optional[float] = None  # GiB


@dataclass
class NodeSnapshot:
    timestamp: float
    node: str
    cpu_allocatable: float  # cores
    mem_allocatable: float  # MiB
    cpu_usage: Optional[float] = None  # cores
    mem_usage: Optional[float] = None  # MiB
    storage_allocatable: Optional[float] = None  # GiB (if available)
    storage_used: Optional[float] = None  # GiB (tracked by us)

def parse_cpu(cpu_raw: str) -> float:
    # Convert to cores
    if cpu_raw.endswith("n"):  # nanocores
        return float(cpu_raw.rstrip("n")) / 1e9
    elif cpu_raw.endswith("u"):  # microcores
        return float(cpu_raw.rstrip("u")) / 1e6
    elif cpu_raw.endswith("m"):  # millicores
        return float(cpu_raw.rstrip("m")) / 1000.0
    else:
        return float(cpu_raw)  # assume cores

def parse_mem(mem_raw: str) -> float:
    # Convert to MiB
    if mem_raw.endswith("Ki"):
        return float(mem_raw.rstrip("Ki")) / 1024.0
    elif mem_raw.endswith("Mi"):
        return float(mem_raw.rstrip("Mi"))
    elif mem_raw.endswith("Gi"):
        return float(mem_raw.rstrip("Gi")) * 1024.0
    elif mem_raw.endswith("Ti"):
        return float(mem_raw.rstrip("Ti")) * 1024.0 * 1024.0
    elif mem_raw.endswith("n"):  # raw bytes with 'n'
        return float(mem_raw.rstrip("n")) / (1024.0 * 1024.0)
    else:
        return float(mem_raw)  # assume MiB

def get_node_usage_metrics():
    metrics_api = client.CustomObjectsApi()
    usage = metrics_api.list_cluster_custom_object(
        group="metrics.k8s.io", version="v1beta1", plural="nodes"
    )

    node_usage = {}
    for item in usage["items"]:
        name = item["metadata"]["name"]
        cpu_raw = item["usage"]["cpu"]
        mem_raw = item["usage"]["memory"]

        cpu_val = parse_cpu(cpu_raw)
        mem_val = parse_mem(mem_raw)

        node_usage[name] = {"cpu": cpu_val, "mem": mem_val}

    return node_usage

def plot_frontend_replicas(output_file):
    end = int(time.time())
    start = end - 3600  # last 1 hour

    df_avail = fetch_prometheus_data(
        PROM_URL,
        'kube_deployment_status_replicas_available{deployment="frontend"}',
        start, end
    )
    df_total = fetch_prometheus_data(
        PROM_URL,
        'kube_deployment_status_replicas{deployment="frontend"}',
        start, end
    )

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(df_avail["timestamp"], df_avail["value"], label="Available Replicas")
    ax.plot(df_total["timestamp"], df_total["value"], label="Desired Replicas")
    ax.set_title("Frontend Deployment Replicas (last 1h)")
    ax.set_xlabel("Time")
    ax.set_ylabel("Replicas")
    ax.legend()
    fig.savefig(output_file)
    plt.close(fig)

def plot_segment(df, title, output_file):
    fig, ax = plt.subplots(figsize=(10, 5))
    for metric, group in df.groupby("metric"):
        ax.plot(group["timestamp"], group["value"], label=metric)
    ax.set_title(title)
    ax.set_xlabel("Time")
    ax.set_ylabel("Value")
    ax.legend()
    fig.savefig(output_file)
    plt.close(fig)

def fetch_prometheus_data(prom_url, query, start, end, step="30s"):
    """
    Fetch time-series data from Prometheus.
    prom_url: base URL of Prometheus (e.g. http://prometheus:9090)
    query: PromQL query string
    start, end: unix timestamps or RFC3339 times
    step: resolution step
    """
    url = f"{prom_url}/api/v1/query_range"
    params = {"query": query, "start": start, "end": end, "step": step}
    r = requests.get(url, params=params)
    r.raise_for_status()
    result = r.json()["data"]["result"]

    # Flatten into DataFrame
    dfs = []
    for series in result:
        metric = series["metric"]
        values = series["values"]
        df = pd.DataFrame(values, columns=["timestamp", "value"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
        df["value"] = df["value"].astype(float)
        df["metric"] = str(metric)
        dfs.append(df)
    return pd.concat(dfs, ignore_index=True)


class SchedulerMonitor:
    def __init__(self, namespace: str = "boutique"):
        self.namespace = namespace

        # Event history
        self._events: List[EventRecord] = []
        self._event_counter: int = 0

        # Node metrics history (time series snapshots)
        self._node_snapshots: List[NodeSnapshot] = []

        # Live state
        self._active_pods_on_node: Dict[str, int] = {}            # node -> active count
        self._storage_used_on_node: Dict[str, float] = {}         # node -> GiB
        self._allocatable_by_node: Dict[str, Tuple[float, float]] = {}  # node -> (cpu cores, mem MiB)
        self._last_pod_request_ts: Optional[float] = None

        self._service_pods_on_node: Dict[str, Dict[str, int]] = {}

        # Placement success
        self._requested_total: int = 0
        self._scheduled_total: int = 0

        # Thread-safety (optional)
        self._lock = threading.RLock()

    # -----------------------
    # Event recording helpers
    # -----------------------
    def _next_event_id(self) -> int:
        self._event_counter += 1
        return self._event_counter

    def mark_pod_request_observed(self, pod_name: str, service_name: str):
        """Call when you observe a new Pending pod that targets this scheduler."""
        with self._lock:
            ts = time.time()
            print(ts)
            self._last_pod_request_ts = ts
            self._requested_total += 1
            self._events.append(EventRecord(
                timestamp=ts,
                event_id=self._next_event_id(),
                event_type="requested",
                pod_name=pod_name,
                service_name=service_name
            ))

    def record_schedule_event(
        self,
        pod_name: str,
        service_name: str,
        node: str,
        cpu_req: Optional[float],
        mem_req: Optional[float],
        storage_req: Optional[float]
    ):
        """Call after binding a pod to a node."""
        with self._lock:
            ts = time.time()
            self._scheduled_total += 1
            self._active_pods_on_node[node] = self._active_pods_on_node.get(node, 0) + 1

            if node not in self._service_pods_on_node:
                self._service_pods_on_node[node] = {}
            self._service_pods_on_node[node][service_name] = (
                self._service_pods_on_node[node].get(service_name, 0) + 1
            )

            if storage_req is not None:
                self._storage_used_on_node[node] = self._storage_used_on_node.get(node, 0.0) + float(storage_req)

            self._events.append(EventRecord(
                timestamp=ts,
                event_id=self._next_event_id(),
                event_type="scheduled",
                pod_name=pod_name,
                service_name=service_name,
                node=node,
                cpu_req=cpu_req,
                mem_req=mem_req,
                storage_req=storage_req
            ))

    def record_termination_event(self, pod_name: str, service_name: str, node: str, storage_req: Optional[float] = None):
        """Call when a pod transitions to Succeeded/Failed (terminated)."""
        with self._lock:
            ts = time.time()
            # Decrement active pods
            self._active_pods_on_node[node] = max(self._active_pods_on_node.get(node, 0) - 1, 0)

            if node in self._service_pods_on_node and service_name in self._service_pods_on_node[node]:
                self._service_pods_on_node[node][service_name] = max(
                    self._service_pods_on_node[node][service_name] - 1, 0
                )

            # Reduce storage usage if we tracked a storage request for the pod
            if storage_req is not None:
                self._storage_used_on_node[node] = max(self._storage_used_on_node.get(node, 0.0) - float(storage_req), 0.0)

            self._events.append(EventRecord(
                timestamp=ts,
                event_id=self._next_event_id(),
                event_type="terminated",
                pod_name=pod_name,
                service_name=service_name,
                node=node
            ))

    # --------------------------------
    # Node allocatable and usage update
    # --------------------------------
    def update_node_allocatable(self, node_allocs: Dict[str, Dict[str, float]]):
        """
        node_allocs: {node: {"cpu": cores, "mem": MiB, "storage": GiB (optional)}}
        Use this to keep allocatable capacity current.
        """
        with self._lock:
            ts = time.time()
            for node, caps in node_allocs.items():
                cpu = float(caps.get("cpu", 0.0))
                mem = float(caps.get("mem", 0.0))
                storage = float(caps.get("storage", 0.0)) if "storage" in caps else None
                self._allocatable_by_node[node] = (cpu, mem)
                # Snapshot (usage will be filled if update_node_usage is called)
                self._node_snapshots.append(NodeSnapshot(
                    timestamp=ts,
                    node=node,
                    cpu_allocatable=cpu,
                    mem_allocatable=mem,
                    storage_allocatable=storage,
                    storage_used=self._storage_used_on_node.get(node, None)
                ))

    def update_node_usage(self, node_usage: Dict[str, Dict[str, float]]):
        """
        node_usage: {node: {"cpu": cores_used, "mem": MiB_used}}
        Typically populated from metrics (e.g., metrics.k8s.io).
        """
        with self._lock:
            ts = time.time()
            for node, usage in node_usage.items():
                cpu_used = float(usage.get("cpu", float("nan")))
                mem_used = float(usage.get("mem", float("nan")))
                # Update latest snapshot for this node (append a fresh one to keep a time series)
                cpu_alloc, mem_alloc = self._allocatable_by_node.get(node, (float("nan"), float("nan")))
                self._node_snapshots.append(NodeSnapshot(
                    timestamp=ts,
                    node=node,
                    cpu_allocatable=cpu_alloc,
                    mem_allocatable=mem_alloc,
                    cpu_usage=cpu_used,
                    mem_usage=mem_used,
                    storage_used=self._storage_used_on_node.get(node, None)
                ))

    # -------------------
    # Plateau (idle) stop
    # -------------------
    def should_stop_on_plateau(self, idle_timeout_sec: int) -> bool:
        """
        Returns True if no new pod requests observed for idle_timeout_sec.
        Call this periodically in the scheduler loop.
        """
        with self._lock:
            now = time.time()
            if self._last_pod_request_ts is None:
                # No requests ever observed; do not stop yet
                return False
            return (now - self._last_pod_request_ts) >= idle_timeout_sec

    # ------------------
    # Fairness metrics
    # ------------------
    @staticmethod
    def _safe_list(values: List[float]) -> List[float]:
        return [v for v in values if v is not None and not math.isnan(v)]

    @staticmethod
    def jains_index(values: List[float]) -> float:
        vals = np.array(values, dtype=float)
        if len(vals) == 0:
            return float("nan")
        num = (vals.sum() ** 2)
        den = len(vals) * (np.square(vals).sum())
        return float(num / den) if den > 0 else float("nan")

    @staticmethod
    def std_dev(values: List[float]) -> float:
        vals = np.array(values, dtype=float)
        return float(np.std(vals)) if len(vals) > 0 else float("nan")

    @staticmethod
    def max_min_ratio(values: List[float]) -> float:
        vals = [v for v in values if v is not None and not math.isnan(v)]
        if not vals:
            return float("nan")
        return float(max(vals) / min(vals)) if min(vals) > 0 else float("inf")

    @staticmethod
    def resource_fragmentation(allocs: List[float], useds: List[float]) -> float:
        """
        Fraction of allocatable capacity left unused (sum-based).
        Lower is better.
        """
        if len(allocs) == 0 or len(useds) == 0:
            return float("nan")
        total_alloc = float(np.sum(allocs))
        total_used = float(np.sum(useds))
        if total_alloc <= 0:
            return float("nan")
        unused = max(total_alloc - total_used, 0.0)
        return unused / total_alloc

    def compute_service_fairness(self) -> Dict[str, Dict[str, float]]:
        fairness = {}
        for service in {e.service_name for e in self._events if e.event_type == "scheduled"}:
            counts = []
            for node, services in self._service_pods_on_node.items():
                if node == "node-0":  # skip node 0 if desired
                    continue
                counts.append(services.get(service, 0))
            if counts:
                fairness[service] = {
                    "stddev": self.std_dev(counts),
                    "max_min_ratio": self.max_min_ratio(counts),
                    "jains": self.jains_index(counts)  # now returns % fairness
                }
        return fairness

    def compute_fairness_summary(self) -> Dict[str, float]:
        """
        Computes fairness metrics from the latest node usage snapshot.
        If usage is missing, falls back to estimated usage from active pods or request sums if possible.
        """
        with self._lock:
            # Take the latest snapshot per node
            latest_by_node: Dict[str, NodeSnapshot] = {}
            for snap in self._node_snapshots:
                latest_by_node[snap.node] = snap

            cpu_allocs = []
            mem_allocs = []
            cpu_useds = []
            mem_useds = []
            storage_allocs = []
            storage_useds = []

            for node, snap in latest_by_node.items():
                if node == "node0":
                    continue
                cpu_allocs.append(snap.cpu_allocatable)
                mem_allocs.append(snap.mem_allocatable)
                if snap.cpu_usage is not None:
                    cpu_useds.append(snap.cpu_usage)
                if snap.mem_usage is not None:
                    mem_useds.append(snap.mem_usage)
                if snap.storage_allocatable is not None:
                    storage_allocs.append(snap.storage_allocatable)
                if snap.storage_used is not None:
                    storage_useds.append(snap.storage_used)

            metrics = {}

            # CPU fairness
            if self._safe_list(cpu_useds):
                #metrics["cpu_stddev"] = self.std_dev(cpu_useds)
                metrics["cpu_max_min_ratio"] = self.max_min_ratio(cpu_useds)
                metrics["cpu_jains"] = self.jains_index(cpu_useds)
                metrics["cpu_fragmentation"] = self.resource_fragmentation(cpu_allocs, cpu_useds)
            else:
                #metrics["cpu_stddev"] = float("nan")
                metrics["cpu_max_min_ratio"] = float("nan")
                metrics["cpu_jains"] = float("nan")
                metrics["cpu_fragmentation"] = float("nan")

            # Memory fairness
            if self._safe_list(mem_useds):
                #metrics["mem_stddev"] = self.std_dev(mem_useds)
                metrics["mem_max_min_ratio"] = self.max_min_ratio(mem_useds)
                metrics["mem_jains"] = self.jains_index(mem_useds)
                metrics["mem_fragmentation"] = self.resource_fragmentation(mem_allocs, mem_useds)
            else:
                #metrics["mem_stddev"] = float("nan")
                metrics["mem_max_min_ratio"] = float("nan")
                metrics["mem_jains"] = float("nan")
                metrics["mem_fragmentation"] = float("nan")

            # Storage fairness (requested-based tracking)
            '''
            if self._safe_list(storage_useds) and self._safe_list(storage_allocs):
                metrics["storage_stddev"] = self.std_dev(storage_useds)
                metrics["storage_max_min_ratio"] = self.max_min_ratio(storage_useds)
                metrics["storage_jains"] = self.jains_index(storage_useds)
                metrics["storage_fragmentation"] = self.resource_fragmentation(storage_allocs, storage_useds)
            else:
                metrics["storage_stddev"] = float("nan")
                metrics["storage_max_min_ratio"] = float("nan")
                metrics["storage_jains"] = float("nan")
                metrics["storage_fragmentation"] = float("nan")
            '''
            '''
            # Pod placement success
            metrics["pod_placement_success_rate"] = (
                float(self._scheduled_total) / float(self._requested_total)
                if self._requested_total > 0 else float("nan")
            )
            '''

            # Multi-resource fairness: average Jain’s across CPU/mem/storage (where available)
            jains_values = [metrics.get("cpu_jains"), metrics.get("mem_jains"), metrics.get("storage_jains")]
            jains_values = [v for v in jains_values if v is not None and not math.isnan(v)]
            #metrics["multi_resource_fairness"] = float(np.mean(jains_values)) if jains_values else float("nan")

            return metrics

    # ---------------
    # Plotting / export
    # ---------------
    def plot_service_distribution(self, output_dir=None):
        data = []
        for node, services in self._service_pods_on_node.items():
            for svc, count in services.items():
                data.append({"node": node, "service": svc, "count": count})

        df = pd.DataFrame(data)
        if df.empty:
            return

        fig, ax = plt.subplots(figsize=(10, 6))
        df.pivot(index="node", columns="service", values="count").plot(kind="bar", ax=ax)
        ax.set_title("Pod distribution per service across nodes")
        ax.set_ylabel("Pod count")
        ax.set_xlabel("Node")
        plt.xticks(rotation=0)

        if output_dir:
            fig.savefig(f"{output_dir}/service_distribution.png")
            plt.close(fig)
        else:
            plt.show()

    def finalize_and_plot(self, pods, output_dir: Optional[str] = None):
        """
        Generates visualizations of utilization and fairness metrics.
        If output_dir is provided, saves PNGs there; otherwise shows interactively.
        """
        with self._lock:
            # Build DataFrames
            events_df = pd.DataFrame([e.__dict__ for e in self._events])
            snaps_df = pd.DataFrame([s.__dict__ for s in self._node_snapshots])

            # Basic plots: time series of CPU/mem usage per node
            figs = []

            if not snaps_df.empty:
                # CPU usage timeseries
                fig1, ax1 = plt.subplots(figsize=(10, 5))
                for node, group in snaps_df.groupby("node"):
                    g = group.dropna(subset=["cpu_usage"])
                    if not g.empty:
                        y = g["cpu_usage"]
                        scheduled_df = events_df[events_df["event_type"] == "scheduled"]
                        times = scheduled_df["timestamp"]
                        elapsed = times.max() - times.min()
                        x = np.linspace(0, elapsed, len(y))
                        ax1.plot(x, y, label=node)
                ax1.set_title("CPU usage by node (cores)")
                ax1.set_xlabel("Time Elapsed (s)")
                ax1.set_ylabel("CPU (cores)")
                ax1.legend(loc="upper right", fontsize="small")
                figs.append(("cpu_usage_timeseries.png", fig1))

                # Memory usage timeseries
                fig2, ax2 = plt.subplots(figsize=(10, 5))
                for node, group in snaps_df.groupby("node"):
                    g = group.dropna(subset=["mem_usage"])
                    if not g.empty:
                        y = g["mem_usage"]
                        scheduled_df = events_df[events_df["event_type"] == "scheduled"]
                        times = scheduled_df["timestamp"]
                        elapsed = times.max() - times.min()
                        x = np.linspace(0, elapsed, len(y))
                        ax2.plot(x, y, label=node)
                ax2.set_title("Memory usage by node (MiB)")
                ax2.set_xlabel("Time Elapsed (s)")
                ax2.set_ylabel("Memory (MiB)")
                ax2.legend(loc="upper right", fontsize="small")
                figs.append(("mem_usage_timeseries.png", fig2))

                # Storage used per node (bar)
                latest = snaps_df.sort_values("timestamp").groupby("node").tail(1)
                storage_latest = latest.dropna(subset=["storage_used"])
                if not storage_latest.empty:
                    fig3, ax3 = plt.subplots(figsize=(8, 5))
                    ax3.bar(storage_latest["node"], storage_latest["storage_used"])
                    ax3.set_title("Storage used per node (GiB)")
                    ax3.set_xlabel("Node")
                    ax3.set_ylabel("Storage used (GiB)")
                    figs.append(("storage_used_per_node.png", fig3))

            # Fairness metrics summary bar chart
            metrics = self.compute_fairness_summary()
            if metrics:
                fig4, ax4 = plt.subplots(figsize=(10, 5))
                names = list(metrics.keys())
                vals = [metrics[k] for k in names]
                ax4.bar(names, vals)
                ax4.set_title("Fairness metrics summary")
                ax4.set_ylabel("Value")
                ax4.set_xticklabels(names, rotation=45, ha="right")
                figs.append(("fairness_metrics_summary.png", fig4))

            # Event timeline (requested vs scheduled vs terminated)
            if not events_df.empty:
                fig5, ax5 = plt.subplots(figsize=(10, 4))
                # Count events over time buckets
                events_df["time_bucket"] = pd.to_datetime(events_df["timestamp"], unit="s").dt.floor("min")
                counts = events_df.groupby(["time_bucket", "event_type"]).size().unstack(fill_value=0)
                counts.plot(ax=ax5)
                ax5.set_title("Event timeline (requested/scheduled/terminated) per minute")
                ax5.set_xlabel("Time")
                ax5.set_ylabel("Count")
                figs.append(("event_timeline.png", fig5))

            # Save or show
            if output_dir:
                for fname, fig in figs:
                    try:
                        fig.tight_layout()
                        fig.savefig(f"{output_dir.rstrip('/')}/{fname}")
                    except Exception:
                        pass
                    finally:
                        plt.close(fig)
            else:
                for _, fig in figs:
                    fig.tight_layout()
                plt.show()
            
            # Service distribution chart
            self.plot_service_distribution(output_dir)

            # Service fairness summary
            service_fairness = self.compute_service_fairness()
            if service_fairness:
                fig, ax = plt.subplots(figsize=(10, 6))
                for svc, metrics in service_fairness.items():
                    ax.bar([f"{svc}-stddev", f"{svc}-ratio", f"{svc}-jains%"],
                           [metrics["stddev"], metrics["max_min_ratio"], metrics["jains"]])
                ax.set_title("Per-service fairness metrics")
                ax.set_ylabel("Value")
                plt.xticks(rotation=45, ha="right")
                if output_dir:
                    fig.savefig(f"{output_dir}/service_fairness_summary.png")
                    plt.close(fig)
                else:
                    plt.show()

            #Plot Graphana Frontend Data
            plot_frontend_replicas(f"{output_dir}/frontend_replicas.png")
