"""
algorithms/astar_router.py
==========================
Challenge 4 — Dynamic A* Emergency Routing.

Algorithm
---------
A* search finds the shortest path from source to target using:
  f(n) = g(n) + h(n)
  g(n) = actual cost from start to n (via the best known path)
  h(n) = admissible heuristic — Euclidean distance to target

Admissibility
-------------
h(n) ≤ true cost → A* is guaranteed optimal.
Euclidean distance never overestimates road distance, so it is admissible.

Dynamic replanning
------------------
When a flood event blocks a road mid-route, the router detects the
obstruction and reruns A* from the current position.
This is a simplified D* Lite approach.

Waypoint routing
----------------
Multi-stop routes are supported: find path from A→B→C by chaining A*
calls.  Each leg is solved independently then concatenated.
"""

from __future__ import annotations
from typing import List, Optional, Dict, Tuple
import heapq
import math

from core.graph_manager import GraphManager
from core.event_bus import EventBus, Event, EventType


class AStarRouter:
    """
    A* pathfinder with dynamic replanning support.

    Attributes
    ----------
    current_path    : The currently active route as list of node IDs.
    current_pos_idx : Index into current_path (where ambulance is now).
    last_cost       : Cost of current_path.
    replan_count    : How many times we have dynamically replanned.
    """

    def __init__(self):
        self.gm              = GraphManager.get_instance()
        self.bus             = EventBus.get_instance()
        self.current_path:   List[int] = []
        self.current_pos_idx: int      = 0
        self.last_cost:       float    = 0.0
        self.replan_count:    int      = 0

        # Subscribe to flood events for dynamic replanning
        self.bus.subscribe(EventType.EDGE_FLOODED, self._on_edge_flooded)

    # ------------------------------------------------------------------ #
    #  Core A* implementation                                              #
    # ------------------------------------------------------------------ #

    def find_path(self, source: int, target: int) -> Tuple[List[int], float]:
        """
        Run A* from source to target on the current passable graph.

        Returns
        -------
        (path, cost) where path is list of node IDs, cost is total weight.
        Returns ([], inf) if no path exists.

        Data structures
        ---------------
        open_set : min-heap of (f_score, node_id)
        g_score  : dict node_id → best known g cost
        came_from: dict node_id → predecessor (for path reconstruction)
        """
        passable = self.gm.get_passable_graph()

        if source not in passable or target not in passable:
            return [], float('inf')

        # ── Initialise ───────────────────────────────────────────────── #
        g_score:   Dict[int, float] = {source: 0.0}
        came_from: Dict[int, int]   = {}
        open_set = []
        # heap entry: (f_score, node_id)
        heapq.heappush(open_set, (self._heuristic(source, target), source))
        closed: set = set()

        # ── Main loop ────────────────────────────────────────────────── #
        while open_set:
            f, current = heapq.heappop(open_set)

            if current == target:
                # Reconstruct path by following came_from back to source
                return self._reconstruct(came_from, current), g_score[current]

            if current in closed:
                continue    # stale entry in heap (lazy deletion)
            closed.add(current)

            for neighbor in passable.neighbors(current):
                edge_w = passable[current][neighbor].get('weight', 1.0)
                if edge_w == float('inf'):
                    continue   # impassable
                tentative_g = g_score[current] + edge_w

                if tentative_g < g_score.get(neighbor, float('inf')):
                    # Found a better path to neighbor
                    g_score[neighbor]   = tentative_g
                    came_from[neighbor] = current
                    f_new = tentative_g + self._heuristic(neighbor, target)
                    heapq.heappush(open_set, (f_new, neighbor))

        return [], float('inf')   # no path found

    def _heuristic(self, a: int, b: int) -> float:
        """
        Admissible Euclidean distance heuristic.
        h(n) ≤ actual cost always, so A* remains optimal.
        """
        return self.gm.euclidean_distance(a, b)

    def _reconstruct(self, came_from: Dict[int, int], current: int) -> List[int]:
        """Walk back through came_from to build the path."""
        path = [current]
        while current in came_from:
            current = came_from[current]
            path.append(current)
        return list(reversed(path))

    # ------------------------------------------------------------------ #
    #  Waypoint routing                                                    #
    # ------------------------------------------------------------------ #

    def find_waypoint_path(self, waypoints: List[int]) -> Tuple[List[int], float]:
        """
        Find a multi-stop route through a list of waypoints.
        Solves A* for each consecutive pair and concatenates results.

        Returns (full_path, total_cost).
        """
        if len(waypoints) < 2:
            return waypoints[:], 0.0

        full_path: List[int] = []
        total_cost = 0.0

        for i in range(len(waypoints) - 1):
            segment, cost = self.find_path(waypoints[i], waypoints[i + 1])
            if not segment:
                return [], float('inf')   # unreachable waypoint
            # Avoid duplicating junction nodes
            if full_path and segment:
                segment = segment[1:]
            full_path.extend(segment)
            total_cost += cost

        return full_path, total_cost

    # ------------------------------------------------------------------ #
    #  Active route management                                             #
    # ------------------------------------------------------------------ #

    def start_route(self, source: int, target: int) -> bool:
        """
        Begin a new emergency route.  Stores the path for animation.
        Returns True if a valid path was found.
        """
        path, cost = self.find_path(source, target)
        if not path:
            return False
        self.current_path    = path
        self.current_pos_idx = 0
        self.last_cost       = cost
        self.bus.publish(Event(EventType.ASTAR_START,
                               data={"from": source, "to": target,
                                     "cost": cost, "hops": len(path)}))
        return True

    def advance(self) -> Optional[int]:
        """
        Move the ambulance one step along current_path.
        Returns the new current node ID, or None if route is complete.
        """
        if self.current_pos_idx + 1 >= len(self.current_path):
            return None
        self.current_pos_idx += 1
        return self.current_path[self.current_pos_idx]

    def current_node(self) -> Optional[int]:
        """Returns the node ID where the ambulance is currently located."""
        if not self.current_path:
            return None
        return self.current_path[self.current_pos_idx]

    def remaining_path(self) -> List[int]:
        """Returns the yet-to-be-traversed portion of the current route."""
        return self.current_path[self.current_pos_idx:]

    def is_route_blocked(self) -> bool:
        """
        Check whether any edge in the remaining route is currently flooded.
        If so, dynamic replanning is triggered.
        """
        remaining = self.remaining_path()
        for i in range(len(remaining) - 1):
            u, v = remaining[i], remaining[i + 1]
            edge = self.gm.get_edge(u, v)
            if edge and edge.blocked:
                return True
        return False

    def replan(self, target: int) -> bool:
        """
        Dynamic replan: rerun A* from current position to target.
        Triggered when a flood blocks the active route.
        """
        current = self.current_node()
        if current is None:
            return False

        old_cost = self.last_cost
        path, cost = self.find_path(current, target)
        if not path:
            return False

        self.current_path    = path
        self.current_pos_idx = 0
        self.last_cost       = cost
        self.replan_count   += 1

        self.bus.publish(Event(EventType.ASTAR_REPLAN,
                               data={"from": current, "to": target,
                                     "old_cost": old_cost, "new_cost": cost,
                                     "replan_num": self.replan_count}))
        return True

    # ------------------------------------------------------------------ #
    #  Event handler                                                       #
    # ------------------------------------------------------------------ #

    def _on_edge_flooded(self, event: Event) -> None:
        """
        Callback invoked when an edge flood event fires.
        If the flooded edge is on our current route, trigger replan.
        """
        if not self.current_path:
            return
        flooded_key = event.data.get("edge")
        remaining   = self.remaining_path()
        for i in range(len(remaining) - 1):
            u, v = remaining[i], remaining[i + 1]
            if (min(u, v), max(u, v)) == flooded_key:
                # Flooded edge is on our path — need to replan
                if remaining:
                    target = remaining[-1]
                    self.replan(target)
                return

    # ------------------------------------------------------------------ #
    #  Analytics                                                           #
    # ------------------------------------------------------------------ #

    def route_efficiency(self) -> dict:
        """Returns analytics for the AI explanation panel."""
        return {
            "total_hops":    len(self.current_path),
            "cost":          round(self.last_cost, 2),
            "replans":       self.replan_count,
            "current_node":  self.current_node(),
        }
