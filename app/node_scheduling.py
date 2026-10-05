"""Scheduling policy for enrolled Cloud/NODE-01/NODE-02 worker heartbeats."""
import math


def choose_node(nodes, capability, now, max_cost=None):
    candidates = []
    for node in nodes:
        if now - node.get('last_seen', 0) >= 30 or capability not in node.get('capabilities', []):
            continue
        if node.get('active_jobs', 0) >= node.get('max_concurrency', 1):
            continue
        resources = node.get('resources') or {}
        load = (resources.get('load') or [0])[0] / max(1, resources.get('cpu_count') or 1)
        cost = (node.get('cost') or {}).get('per_job')
        known_cost = isinstance(cost, (float, int)) and math.isfinite(cost) and cost >= 0
        if load >= 2 or (max_cost is not None and (not known_cost or cost > max_cost)):
            continue
        candidates.append(((cost if known_cost else math.inf, load, node['id']), node['id']))
    return min(candidates)[1] if candidates else None
