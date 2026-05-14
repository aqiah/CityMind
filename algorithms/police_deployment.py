"""
algorithms/police_deployment.py
================================
Challenge 5 — deploy a fixed squad of police officers using ML crime predictions.

Greedy placement maximises predicted risk at each step while penalising
already-chosen neighbours (Manhattan distance ≤ 1) so units spread across
hotspots instead of stacking on one corner.
"""

from __future__ import annotations

from typing import Dict, List, Set

from core.graph_manager import GraphManager
from core.node import LocationType

POLICE_COUNT = 10
# Reduces stacking adjacent officers while still favouring high-crime cells.
NEIGHBOR_PENALTY = 0.18


def allocate_police_positions(
    crime_map: Dict[int, float],
    *,
    count: int = POLICE_COUNT,
) -> List[int]:
    """
    Return exactly ``count`` distinct node IDs for officer deployment.

    Parameters
    ----------
    crime_map
        Per-node risk score in [0, 1], e.g. from ``CrimePredictor.crime_heatmap()``.
    """
    gm = GraphManager.get_instance()
    if not gm.nodes:
        return []

    # Patrol zoned cells first; include empties only if we cannot fill ``count``.
    candidates = [
        nid for nid, node in gm.nodes.items()
        if node.location_type != LocationType.EMPTY
    ]
    pool: Set[int] = set(candidates if len(candidates) >= count else gm.nodes.keys())

    def manhattan(a: int, b: int) -> int:
        na, nb = gm.nodes[a], gm.nodes[b]
        return abs(na.x - nb.x) + abs(na.y - nb.y)

    def score(nid: int, chosen: Set[int]) -> float:
        base = float(crime_map.get(nid, 0.0))
        node = gm.nodes[nid]
        tie = 0.01 * node.population
        pen = NEIGHBOR_PENALTY * sum(1 for s in chosen if manhattan(nid, s) <= 1)
        return base + tie - pen

    selected: List[int] = []
    chosen: Set[int] = set()
    n_need = min(count, len(gm.nodes))

    while len(selected) < n_need and pool:
        best = max(pool, key=lambda nid: score(nid, chosen))
        selected.append(best)
        chosen.add(best)
        pool.discard(best)

    return selected
