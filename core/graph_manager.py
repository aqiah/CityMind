"""
core/graph_manager.py
=====================
GraphManager is the single source of truth for the entire city graph.
Every AI module reads/writes through this class — no module maintains
its own graph copy.  This guarantees consistency across the simulation.

Design: Singleton + Observer (via EventBus).
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple, Set
import math
import random
import networkx as nx

from .node import Node, LocationType
from .edge import Edge
from .event_bus import EventBus, Event, EventType


class GraphManager:
    """
    Centralised city graph store.

    Responsibilities
    ----------------
    * Owns all Node and Edge objects.
    * Exposes NetworkX DiGraph for algorithm consumption.
    * Broadcasts mutations through EventBus.
    * Recomputes effective edge weights after risk updates.
    * Handles flood events (temporarily blocking edges).
    """

    _instance: "GraphManager | None" = None

    # ------------------------------------------------------------------ #
    #  Singleton lifecycle                                                 #
    # ------------------------------------------------------------------ #

    def __init__(self):
        self._nodes: Dict[int, Node]         = {}
        self._edges: Dict[tuple, Edge]       = {}
        self._graph: nx.Graph                = nx.Graph()
        self._bus:   EventBus                = EventBus.get_instance()
        self._grid_w: int                    = 0
        self._grid_h: int                    = 0
        self.primary_hospital_id: Optional[int] = None
        self.primary_depot_id: Optional[int]    = None

    @classmethod
    def get_instance(cls) -> "GraphManager":
        if cls._instance is None:
            cls._instance = GraphManager()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Destroys the current singleton so tests/resets start fresh."""
        cls._instance = None

    # ------------------------------------------------------------------ #
    #  Graph construction                                                  #
    # ------------------------------------------------------------------ #

    def build_grid(self, width: int, height: int,
                   cell_px: int = 60, origin_x: int = 10, origin_y: int = 10) -> None:
        """
        Construct a W×H grid graph.
        Each grid cell becomes a Node; 4-connected edges are created between
        adjacent cells.  Diagonal edges are NOT created (keeps the city grid
        looking like a real street network).

        Parameters
        ----------
        width, height : Grid dimensions in cells.
        cell_px       : Pixel size of each cell (for rendering).
        origin_x/y    : Top-left pixel offset of the grid on screen.
        """
        self._nodes.clear()
        self._edges.clear()
        self._graph = nx.Graph()
        self._grid_w = width
        self._grid_h = height
        self.primary_hospital_id = None
        self.primary_depot_id = None

        # --- Create nodes ---
        for row in range(height):
            for col in range(width):
                nid = row * width + col
                node = Node(
                    node_id=nid,
                    x=col,
                    y=row,
                    px=origin_x + col * cell_px + cell_px // 2,
                    py=origin_y + row * cell_px + cell_px // 2,
                    population=round(random.uniform(0.1, 0.9), 3),
                )
                self._nodes[nid] = node
                self._graph.add_node(nid, data=node)

        # --- Create 4-connected edges ---
        for row in range(height):
            for col in range(width):
                nid = row * width + col
                # Right neighbour
                if col + 1 < width:
                    right = row * width + (col + 1)
                    self._add_edge(nid, right, cell_px)
                # Down neighbour
                if row + 1 < height:
                    down = (row + 1) * width + col
                    self._add_edge(nid, down, cell_px)

        # Populate neighbor lists on Node objects
        for nid in self._graph.nodes:
            self._nodes[nid].neighbors = list(self._graph.neighbors(nid))

        self._bus.publish(Event(EventType.GRAPH_REBUILT,
                                data={"nodes": len(self._nodes), "edges": len(self._edges)}))

    def _add_edge(self, u: int, v: int, base_weight: float) -> None:
        """Internal helper to create and register an Edge object."""
        # Euclidean distance as base weight (all grid edges equal here)
        edge = Edge(u=u, v=v, weight=base_weight, effective_weight=base_weight)
        key = edge.key()
        self._edges[key] = edge
        self._graph.add_edge(u, v, weight=base_weight, data=edge)

    # ------------------------------------------------------------------ #
    #  Accessors                                                           #
    # ------------------------------------------------------------------ #

    @property
    def nodes(self) -> Dict[int, Node]:
        return self._nodes

    @property
    def edges(self) -> Dict[tuple, Edge]:
        return self._edges

    @property
    def graph(self) -> nx.Graph:
        """The underlying NetworkX graph (read-only reference)."""
        return self._graph

    @property
    def grid_w(self) -> int:
        return self._grid_w

    @property
    def grid_h(self) -> int:
        return self._grid_h

    def get_node(self, nid: int) -> Optional[Node]:
        return self._nodes.get(nid)

    def get_edge(self, u: int, v: int) -> Optional[Edge]:
        return self._edges.get((min(u, v), max(u, v)))

    def get_nodes_by_type(self, ltype: LocationType) -> List[Node]:
        return [n for n in self._nodes.values() if n.location_type == ltype]

    def all_node_ids(self) -> List[int]:
        return list(self._nodes.keys())

    def assign_primary_facilities(self) -> None:
        """
        After CSP placement: pick the hospital–depot pair with **maximum**
        Euclidean separation so EMS missions span the map (longer paths).

        Tie-break: lower hospital node id, then lower depot id.
        """
        self.primary_hospital_id = None
        self.primary_depot_id = None
        hospitals = self.get_nodes_by_type(LocationType.HOSPITAL)
        depots = self.get_nodes_by_type(LocationType.AMBULANCE_DEPOT)
        if not hospitals or not depots:
            return
        _, self.primary_hospital_id, self.primary_depot_id = max(
            (
                (
                    self.euclidean_distance(h.node_id, d.node_id),
                    h.node_id,
                    d.node_id,
                )
                for h in hospitals
                for d in depots
            ),
            key=lambda t: (t[0], -t[1], -t[2]),
        )

    # ------------------------------------------------------------------ #
    #  Mutations                                                           #
    # ------------------------------------------------------------------ #

    def set_location_type(self, nid: int, ltype: LocationType) -> None:
        """Change the location type of a node (CSP module uses this)."""
        if nid in self._nodes:
            self._nodes[nid].location_type = ltype
            self._bus.publish(Event(EventType.CSP_PLACED,
                                    data={"node": nid, "type": ltype.name}))

    def update_node_risk(self, nid: int, risk: float) -> None:
        """
        Update a node's risk_index and recompute all incident edge weights.
        Risk changes ripple out to edge costs so A* reroutes automatically.
        """
        if nid not in self._nodes:
            return
        self._nodes[nid].risk_index = max(0.0, min(1.0, risk))
        # Recompute incident edges
        for neighbor_id in self._nodes[nid].neighbors:
            key = (min(nid, neighbor_id), max(nid, neighbor_id))
            if key in self._edges:
                edge = self._edges[key]
                edge.update_effective_weight(
                    self._nodes[nid].risk_index,
                    self._nodes[neighbor_id].risk_index
                )
                # Sync effective weight back into networkx edge data
                self._graph[nid][neighbor_id]['weight'] = edge.effective_weight

        self._bus.publish(Event(EventType.NODE_RISK_UPDATED,
                                data={"node": nid, "risk": self._nodes[nid].risk_index}))

    def flood_edge(self, u: int, v: int, ttl: int = 3) -> None:
        """
        Block an edge for `ttl` simulation steps (simulates flooding).
        Sets weight to infinity so A* won't route through it.
        """
        key = (min(u, v), max(u, v))
        if key not in self._edges:
            return
        edge = self._edges[key]
        edge.blocked  = True
        edge.flood_ttl = ttl
        edge.effective_weight = float('inf')
        if self._graph.has_edge(u, v):
            self._graph[u][v]['weight'] = float('inf')

        self._bus.publish(Event(EventType.EDGE_FLOODED,
                                data={"edge": key, "ttl": ttl}))

    def tick_floods(self) -> List[tuple]:
        """
        Called once per simulation step.
        Decrements flood TTL; clears edges whose TTL reaches 0.
        Returns list of edge keys that were cleared this tick.
        """
        cleared = []
        for key, edge in self._edges.items():
            if edge.blocked and edge.flood_ttl > 0:
                edge.flood_ttl -= 1
                if edge.flood_ttl == 0:
                    edge.blocked = False
                    # Restore effective weight
                    u, v = key
                    edge.update_effective_weight(
                        self._nodes[u].risk_index,
                        self._nodes[v].risk_index
                    )
                    if self._graph.has_edge(u, v):
                        self._graph[u][v]['weight'] = edge.effective_weight
                    cleared.append(key)
                    self._bus.publish(Event(EventType.EDGE_CLEARED, data={"edge": key}))
        return cleared

    def add_augmented_edge(self, u: int, v: int, weight: float) -> None:
        """Add a redundancy edge (hospital-depot link) during road augmentation."""
        edge = Edge(u=u, v=v, weight=weight, effective_weight=weight, augmented=True)
        key = edge.key()
        if key not in self._edges:
            self._edges[key] = edge
            self._graph.add_edge(u, v, weight=weight, data=edge)
            # Update neighbor lists
            if v not in self._nodes[u].neighbors:
                self._nodes[u].neighbors.append(v)
            if u not in self._nodes[v].neighbors:
                self._nodes[v].neighbors.append(u)

    def mark_bridge(self, u: int, v: int) -> None:
        """Mark an edge as a bridge (found by Tarjan's algorithm)."""
        key = (min(u, v), max(u, v))
        if key in self._edges:
            self._edges[key].bridge = True

    def get_passable_graph(self) -> nx.Graph:
        """
        Return a subgraph containing only non-blocked edges.
        Used by A* so it never even considers flooded roads.
        """
        passable = nx.Graph()
        passable.add_nodes_from(self._graph.nodes(data=True))
        for (u, v) in self._graph.edges():
            key = (min(u, v), max(u, v))
            edge = self._edges.get(key)
            if edge and not edge.blocked:
                passable.add_edge(u, v, weight=edge.effective_weight)
        return passable

    # ------------------------------------------------------------------ #
    #  Utility                                                             #
    # ------------------------------------------------------------------ #

    def euclidean_distance(self, a: int, b: int) -> float:
        """Pixel-space Euclidean distance between two nodes (A* heuristic)."""
        na, nb = self._nodes[a], self._nodes[b]
        return math.hypot(na.px - nb.px, na.py - nb.py)

    def grid_distance(self, a: int, b: int) -> int:
        """Manhattan distance in grid cells (fast heuristic)."""
        na, nb = self._nodes[a], self._nodes[b]
        return abs(na.x - nb.x) + abs(na.y - nb.y)

    def node_at(self, gx: int, gy: int) -> Optional[Node]:
        """Return the node at grid position (gx, gy), or None."""
        nid = gy * self._grid_w + gx
        return self._nodes.get(nid)

    def reachable(self, source: int) -> Set[int]:
        """BFS from source; returns set of reachable node ids on passable graph."""
        passable = self.get_passable_graph()
        return nx.node_connected_component(passable, source) if source in passable else set()

    def stats(self) -> dict:
        """Returns a statistics dict for the UI statistics panel."""
        hospitals  = len(self.get_nodes_by_type(LocationType.HOSPITAL))
        depots     = len(self.get_nodes_by_type(LocationType.AMBULANCE_DEPOT))
        flooded    = sum(1 for e in self._edges.values() if e.blocked)
        bridges    = sum(1 for e in self._edges.values() if e.bridge)
        avg_risk   = (sum(n.risk_index for n in self._nodes.values()) / max(len(self._nodes), 1))
        high_crime = sum(1 for n in self._nodes.values() if n.crime_level == "High")
        out = {
            "nodes":      len(self._nodes),
            "edges":      len(self._edges),
            "hospitals":  hospitals,
            "depots":     depots,
            "flooded":    flooded,
            "bridges":    bridges,
            "avg_risk":   round(avg_risk, 3),
            "high_crime": high_crime,
        }
        if self.primary_hospital_id is not None:
            out["primary_hospital"] = self.primary_hospital_id
        if self.primary_depot_id is not None:
            out["primary_depot"] = self.primary_depot_id
        return out
