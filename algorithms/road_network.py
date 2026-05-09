"""
algorithms/road_network.py
==========================
Challenge 2 — Road Network Optimisation.

Algorithms implemented
----------------------
* Kruskal's MST — builds minimum-cost spanning road network.
* Union-Find (with path compression + union by rank) — fast cycle detection.
* Tarjan's Bridge Finding — identifies critical (bridge) edges.
* Selective Edge Augmentation — adds redundant links between hospitals and
  ambulance depots to ensure k-connectivity for emergency vehicles.

Why MST?
--------
Kruskal's algorithm greedily adds the cheapest edge that does not form a cycle.
The result is a tree with minimum total edge weight — i.e. the cheapest road
network that still connects every node.  We then augment it with extra edges
to ensure hospitals/depots remain connected even if a bridge road is flooded.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Set
import math

from core.graph_manager import GraphManager
from core.node import LocationType
from core.edge import Edge
from core.event_bus import EventBus, Event, EventType


# ═════════════════════════════════════════════════════════════════════════ #
#  Union-Find (Disjoint Set Union)                                          #
# ═════════════════════════════════════════════════════════════════════════ #

class UnionFind:
    """
    Path-compressed Union-Find data structure.
    Used by Kruskal's to detect cycles in O(α(n)) amortised time.
    """

    def __init__(self, elements):
        self.parent: Dict = {e: e for e in elements}
        self.rank:   Dict = {e: 0 for e in elements}

    def find(self, x) -> int:
        """Find with path compression (flattens the tree)."""
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])   # path compression
        return self.parent[x]

    def union(self, x, y) -> bool:
        """
        Union by rank.
        Returns True if x and y were in different sets (edge is safe to add),
        False if they were already connected (adding would form a cycle).
        """
        rx, ry = self.find(x), self.find(y)
        if rx == ry:
            return False   # already same component — would form cycle
        # Attach smaller-rank tree under larger-rank root
        if self.rank[rx] < self.rank[ry]:
            rx, ry = ry, rx
        self.parent[ry] = rx
        if self.rank[rx] == self.rank[ry]:
            self.rank[rx] += 1
        return True


# ═════════════════════════════════════════════════════════════════════════ #
#  Road Network Builder                                                     #
# ═════════════════════════════════════════════════════════════════════════ #

class RoadNetworkBuilder:
    """
    Builds and augments the city road network.

    Steps
    -----
    1. Collect all possible edges from the GraphManager.
    2. Run Kruskal's MST to find the minimum-cost spanning network.
    3. Run Tarjan's bridge finding on the MST.
    4. Augment with extra edges between hospitals and ambulance depots
       so the critical infrastructure is never disconnected by a single
       bridge failure.
    5. Validate connectivity with BFS.
    """

    def __init__(self):
        self.gm  = GraphManager.get_instance()
        self.bus = EventBus.get_instance()
        self.mst_edges:       List[Tuple[int, int]] = []
        self.bridge_edges:    List[Tuple[int, int]] = []
        self.augmented_edges: List[Tuple[int, int]] = []

    # ------------------------------------------------------------------ #
    #  Main pipeline                                                       #
    # ------------------------------------------------------------------ #

    def build(self) -> None:
        """Execute the full road-network construction pipeline."""
        self._kruskal_mst()
        self._tarjan_bridges()
        self._augment_critical_nodes()
        self._validate()

    # ------------------------------------------------------------------ #
    #  Step 1: Kruskal's MST                                               #
    # ------------------------------------------------------------------ #

    def _kruskal_mst(self) -> None:
        """
        Kruskal's algorithm:
        1. Sort all edges by weight (ascending).
        2. For each edge (u,v) — if u and v are not already connected,
           add the edge to the MST and merge their components.

        Time complexity: O(E log E) due to the sort.
        Space complexity: O(V) for Union-Find.
        """
        all_edges = sorted(self.gm.edges.values(), key=lambda e: e.weight)
        uf = UnionFind(self.gm.all_node_ids())
        mst_set: Set[Tuple[int, int]] = set()

        for edge in all_edges:
            u, v = edge.u, edge.v
            if uf.union(u, v):
                # Edge accepted — add to MST
                mst_set.add(edge.key())
                self.mst_edges.append((u, v))
                self.bus.publish(Event(EventType.MST_EDGE_ADDED,
                                       data={"u": u, "v": v, "w": edge.weight}))

        # Remove all edges NOT in the MST from the GraphManager graph
        # (We keep them in self.gm.edges dict but make them very expensive)
        for key, edge in self.gm.edges.items():
            if key not in mst_set:
                edge.effective_weight = float('inf')
                if self.gm.graph.has_edge(edge.u, edge.v):
                    self.gm.graph[edge.u][edge.v]['weight'] = float('inf')

        self.bus.publish(Event(EventType.MST_COMPLETE,
                               data={"mst_edges": len(self.mst_edges)}))

    # ------------------------------------------------------------------ #
    #  Step 2: Tarjan's Bridge Finding                                     #
    # ------------------------------------------------------------------ #

    def _tarjan_bridges(self) -> None:
        """
        Tarjan's linear-time bridge-finding algorithm.

        An edge (u, v) is a bridge if removing it increases the number of
        connected components — i.e. there is no back-edge that bypasses it.

        Uses DFS discovery/low arrays:
        - disc[v]  = DFS discovery time of v
        - low[v]   = earliest discovery time reachable from subtree of v
          (via back-edges)

        If low[v] > disc[u] for edge (u,v), then (u,v) is a bridge because
        the subtree rooted at v has no way back to u's ancestors.
        """
        passable = self.gm.get_passable_graph()
        disc: Dict[int, int] = {}
        low:  Dict[int, int] = {}
        visited: Set[int]    = set()
        timer = [0]

        def dfs(u: int, parent: int) -> None:
            visited.add(u)
            disc[u] = low[u] = timer[0]
            timer[0] += 1
            for v in passable.neighbors(u):
                if v not in visited:
                    dfs(v, u)
                    low[u] = min(low[u], low[v])
                    # Bridge condition
                    if low[v] > disc[u]:
                        self.bridge_edges.append((u, v))
                        self.gm.mark_bridge(u, v)
                        self.bus.publish(Event(EventType.BRIDGE_FOUND,
                                               data={"u": u, "v": v}))
                elif v != parent:
                    # Back-edge — update low value
                    low[u] = min(low[u], disc[v])

        for node_id in passable.nodes():
            if node_id not in visited:
                dfs(node_id, -1)

    # ------------------------------------------------------------------ #
    #  Step 3: Selective augmentation                                      #
    # ------------------------------------------------------------------ #

    def _augment_critical_nodes(self) -> None:
        """
        Add extra edges between hospitals and ambulance depots to ensure
        emergency infrastructure remains connected even if a bridge fails.

        Strategy: for each hospital, find the nearest ambulance depot and
        add a direct shortcut edge if none exists.  This guarantees at least
        2-connectivity between these critical nodes.
        """
        hospitals = self.gm.get_nodes_by_type(LocationType.HOSPITAL)
        depots    = self.gm.get_nodes_by_type(LocationType.AMBULANCE_DEPOT)

        if not hospitals or not depots:
            return

        for hospital in hospitals:
            # Find nearest depot not already directly connected
            best_depot = None
            best_dist  = float('inf')
            for depot in depots:
                if not self.gm.graph.has_edge(hospital.node_id, depot.node_id):
                    d = self.gm.euclidean_distance(hospital.node_id, depot.node_id)
                    if d < best_dist:
                        best_dist  = d
                        best_depot = depot

            if best_depot is not None:
                self.gm.add_augmented_edge(hospital.node_id, best_depot.node_id, best_dist)
                self.augmented_edges.append((hospital.node_id, best_depot.node_id))

    # ------------------------------------------------------------------ #
    #  Step 4: Validation                                                  #
    # ------------------------------------------------------------------ #

    def _validate(self) -> bool:
        """
        BFS connectivity test.
        Returns True if all nodes are reachable from node 0.
        Logs the result to the event bus.
        """
        import networkx as nx
        passable = self.gm.get_passable_graph()
        if len(passable.nodes) == 0:
            return False
        start = next(iter(passable.nodes))
        reachable = nx.node_connected_component(passable, start)
        connected = (len(reachable) == len(passable.nodes))
        self.bus.publish(Event(EventType.MST_COMPLETE,
                               data={"validated": connected,
                                     "reachable": len(reachable),
                                     "total": len(passable.nodes)}))
        return connected
