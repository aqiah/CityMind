"""
algorithms/csp_solver.py
========================
Challenge 1 — Constraint Satisfaction Problem (CSP) City Layout Planner.

Algorithms implemented
----------------------
* Backtracking search with recursive call stack
* MRV (Minimum Remaining Values) — choose the variable with fewest legal values
* LCV (Least Constraining Value) — prefer values that leave neighbors most freedom
* Forward Checking — prune domains after each assignment

Constraints enforced
--------------------
1. Industrial zones must NOT be adjacent to schools or hospitals.
2. Every residential zone must be within 3 hops of at least one hospital.
3. Every power plant must be within 2 hops of at least one industrial zone.
4. Hospitals and ambulance depots must not share the same node.
5. Maximum instances of each type enforced by type_counts limits.
"""

from __future__ import annotations
from typing import Dict, List, Optional, Set, Tuple
import random
import networkx as nx

from core.graph_manager import GraphManager
from core.node import LocationType
from core.event_bus import EventBus, Event, EventType


# Fixed placement quotas for a 10×10 grid
TYPE_QUOTAS = {
    LocationType.RESIDENTIAL:    20,
    LocationType.HOSPITAL:        3,
    LocationType.SCHOOL:          4,
    LocationType.INDUSTRIAL:      5,
    LocationType.POWER_PLANT:     2,
    LocationType.AMBULANCE_DEPOT: 3,
    LocationType.EMPTY:           0,   # remainder
}

# Incompatible adjacency pairs: key must not be adjacent to any value
ADJACENCY_CONFLICTS: Dict[LocationType, Set[LocationType]] = {
    LocationType.INDUSTRIAL: {LocationType.SCHOOL, LocationType.HOSPITAL},
    LocationType.SCHOOL:     {LocationType.INDUSTRIAL},
    LocationType.HOSPITAL:   {LocationType.INDUSTRIAL},
}


class CSPSolver:
    """
    Solves the city layout problem using CSP backtracking with
    MRV, LCV, and forward-checking pruning.

    Attributes
    ----------
    gm            : Shared GraphManager (single source of truth).
    bus           : EventBus for broadcasting placement events.
    assignment    : Current node_id → LocationType mapping.
    domains       : node_id → list of still-legal LocationTypes.
    type_remaining: How many more of each type may still be placed.
    conflicts     : List of (node_id, constraint_description) for UI.
    """

    def __init__(self):
        self.gm             = GraphManager.get_instance()
        self.bus            = EventBus.get_instance()
        self.assignment:    Dict[int, LocationType] = {}
        self.domains:       Dict[int, List[LocationType]] = {}
        self.type_remaining = dict(TYPE_QUOTAS)
        self.conflicts:     List[Tuple[int, str]] = []
        self.steps:         List[Tuple[int, LocationType]] = []  # animation steps

    # ------------------------------------------------------------------ #
    #  Public entry point                                                  #
    # ------------------------------------------------------------------ #

    def solve(self) -> bool:
        """
        Run CSP solver.  Returns True if a complete solution was found,
        False if backtracking exhausted all options (fallback to min-conflicts).
        """
        self.assignment.clear()
        self.conflicts.clear()
        self.steps.clear()
        self.type_remaining = dict(TYPE_QUOTAS)

        # Build initial full domain for every unassigned node
        all_types = [t for t, q in TYPE_QUOTAS.items() if q > 0]
        for nid in self.gm.all_node_ids():
            self.domains[nid] = list(all_types)

        success = self._backtrack()
        if not success:
            # Fall back: greedy min-conflict assignment
            self._min_conflict_fallback()

        # Apply final assignment to the GraphManager
        for nid, ltype in self.assignment.items():
            self.gm.set_location_type(nid, ltype)

        # Remaining nodes become EMPTY
        for nid in self.gm.all_node_ids():
            if nid not in self.assignment:
                self.gm.set_location_type(nid, LocationType.EMPTY)

        self.bus.publish(Event(EventType.CSP_COMPLETE,
                               data={"placed": len(self.assignment),
                                     "conflicts": len(self.conflicts)}))
        return success

    # ------------------------------------------------------------------ #
    #  Backtracking engine                                                 #
    # ------------------------------------------------------------------ #

    def _backtrack(self) -> bool:
        """
        Recursive backtracking search.
        Returns True when all quotas are satisfied.
        """
        # Base case: all non-empty quotas have been fulfilled
        if all(v == 0 for k, v in self.type_remaining.items() if k != LocationType.EMPTY):
            return True

        # MRV: choose the unassigned node whose domain is smallest
        var = self._select_variable_mrv()
        if var is None:
            return True   # no more variables needed

        # LCV: order values so least-constraining come first
        ordered_values = self._order_values_lcv(var)

        for value in ordered_values:
            if self.type_remaining.get(value, 0) <= 0:
                continue   # quota exhausted — skip

            if self._is_consistent(var, value):
                # Assign
                self.assignment[var] = value
                self.type_remaining[value] -= 1
                self.steps.append((var, value))

                # Forward checking: prune domains of unassigned neighbors
                pruned = self._forward_check(var, value)

                result = self._backtrack()
                if result:
                    return True

                # Undo (backtrack)
                self._restore_domains(pruned)
                del self.assignment[var]
                self.type_remaining[value] += 1

        return False   # failure at this branch

    # ------------------------------------------------------------------ #
    #  MRV heuristic                                                       #
    # ------------------------------------------------------------------ #

    def _select_variable_mrv(self) -> Optional[int]:
        """
        MRV: return the unassigned node with the smallest legal domain.
        Ties broken randomly to avoid systematic bias.
        Only considers nodes that still have types with remaining quota.
        """
        candidates = []
        for nid in self.gm.all_node_ids():
            if nid in self.assignment:
                continue
            # Filter domain to types with remaining quota
            legal = [t for t in self.domains.get(nid, [])
                     if self.type_remaining.get(t, 0) > 0]
            if legal:
                candidates.append((len(legal), nid))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        # Return from the minimum-domain group (random tie-break)
        min_size = candidates[0][0]
        min_group = [nid for sz, nid in candidates if sz == min_size]
        return random.choice(min_group)

    # ------------------------------------------------------------------ #
    #  LCV heuristic                                                       #
    # ------------------------------------------------------------------ #

    def _order_values_lcv(self, var: int) -> List[LocationType]:
        """
        LCV: sort values by how few constraints they impose on neighbours.
        A value is 'least constraining' if it eliminates the fewest
        remaining values from neighbours' domains.
        """
        scores = []
        for value in self.domains.get(var, []):
            if self.type_remaining.get(value, 0) <= 0:
                continue
            # Count how many (neighbour, type) pairs this assignment eliminates
            eliminated = 0
            node = self.gm.get_node(var)
            for nb_id in node.neighbors:
                if nb_id in self.assignment:
                    continue
                for nb_val in self.domains.get(nb_id, []):
                    if self._would_conflict(var, value, nb_id, nb_val):
                        eliminated += 1
            scores.append((eliminated, value))

        scores.sort(key=lambda x: x[0])   # prefer least-eliminating
        return [v for _, v in scores]

    def _would_conflict(self, var: int, val: LocationType,
                        nb: int, nb_val: LocationType) -> bool:
        """Check if assigning val to var would make nb_val illegal for nb."""
        # If assigning val=INDUSTRIAL to var and nb_val is SCHOOL/HOSPITAL
        conflicts = ADJACENCY_CONFLICTS.get(val, set())
        if nb_val in conflicts:
            # nb is adjacent to var, so this would be a conflict
            nb_node = self.gm.get_node(nb)
            if var in nb_node.neighbors:
                return True
        # Also check reverse
        conflicts2 = ADJACENCY_CONFLICTS.get(nb_val, set())
        if val in conflicts2:
            return True
        return False

    # ------------------------------------------------------------------ #
    #  Forward checking                                                    #
    # ------------------------------------------------------------------ #

    def _forward_check(self, var: int, value: LocationType) -> Dict[int, List[LocationType]]:
        """
        After assigning value to var, remove values from neighbours' domains
        that would violate adjacency constraints.
        Returns a dict of {nb_id: removed_values} for backtracking restoration.
        """
        pruned: Dict[int, List[LocationType]] = {}
        node = self.gm.get_node(var)
        forbidden_for_neighbors = ADJACENCY_CONFLICTS.get(value, set())

        for nb_id in node.neighbors:
            if nb_id in self.assignment:
                continue
            to_remove = []
            for nb_val in self.domains.get(nb_id, []):
                if nb_val in forbidden_for_neighbors:
                    to_remove.append(nb_val)
                # Also: if nb_val would conflict with this assignment
                if value in ADJACENCY_CONFLICTS.get(nb_val, set()):
                    if nb_val not in to_remove:
                        to_remove.append(nb_val)
            if to_remove:
                pruned[nb_id] = to_remove
                for rv in to_remove:
                    if rv in self.domains.get(nb_id, []):
                        self.domains[nb_id].remove(rv)
        return pruned

    def _restore_domains(self, pruned: Dict[int, List[LocationType]]) -> None:
        """Re-add pruned values when backtracking."""
        for nb_id, removed in pruned.items():
            for rv in removed:
                if rv not in self.domains.get(nb_id, []):
                    self.domains.setdefault(nb_id, []).append(rv)

    # ------------------------------------------------------------------ #
    #  Consistency check                                                   #
    # ------------------------------------------------------------------ #

    def _is_consistent(self, var: int, value: LocationType) -> bool:
        """
        Check all hard constraints for assigning value to var.
        Returns True if this assignment does not violate any constraint.
        """
        node = self.gm.get_node(var)
        forbidden_neighbors = ADJACENCY_CONFLICTS.get(value, set())

        # C1 — adjacency conflict check
        for nb_id in node.neighbors:
            if nb_id not in self.assignment:
                continue
            assigned_type = self.assignment[nb_id]
            if assigned_type in forbidden_neighbors:
                self.conflicts.append((var, f"{value.name} adj to {assigned_type.name}"))
                self.bus.publish(Event(EventType.CSP_CONFLICT,
                                       data={"node": var, "type": value.name,
                                             "conflict_with": nb_id}))
                return False
            # Reverse check
            if value in ADJACENCY_CONFLICTS.get(assigned_type, set()):
                self.conflicts.append((var, f"{assigned_type.name} adj to {value.name}"))
                return False

        return True

    # ------------------------------------------------------------------ #
    #  Min-conflict fallback                                               #
    # ------------------------------------------------------------------ #

    def _min_conflict_fallback(self) -> None:
        """
        Greedy fallback: assign types with minimum conflicts.
        Called when backtracking finds no complete solution.
        """
        unassigned = [nid for nid in self.gm.all_node_ids()
                      if nid not in self.assignment]
        random.shuffle(unassigned)

        for nid in unassigned:
            best_type = LocationType.EMPTY
            best_conflicts = float('inf')
            for ltype, quota in self.type_remaining.items():
                if ltype == LocationType.EMPTY or quota <= 0:
                    continue
                conflict_count = 0
                node = self.gm.get_node(nid)
                for nb_id in node.neighbors:
                    assigned = self.assignment.get(nb_id)
                    if assigned and assigned in ADJACENCY_CONFLICTS.get(ltype, set()):
                        conflict_count += 1
                if conflict_count < best_conflicts:
                    best_conflicts = conflict_count
                    best_type = ltype

            if best_type != LocationType.EMPTY and self.type_remaining.get(best_type, 0) > 0:
                self.assignment[nid] = best_type
                self.type_remaining[best_type] -= 1
                self.steps.append((nid, best_type))

    # ------------------------------------------------------------------ #
    #  Constraint validation                                               #
    # ------------------------------------------------------------------ #

    def validate_solution(self) -> List[str]:
        """
        Post-solve validation.  Returns list of violated constraint descriptions.
        Used by tests and the AI explanation panel.
        """
        violations = []
        graph = self.gm.graph

        for nid, ltype in self.assignment.items():
            forbidden_nb = ADJACENCY_CONFLICTS.get(ltype, set())
            node = self.gm.get_node(nid)
            for nb_id in node.neighbors:
                nb_type = self.assignment.get(nb_id)
                if nb_type and nb_type in forbidden_nb:
                    violations.append(
                        f"Node {nid} ({ltype.name}) adj to {nb_id} ({nb_type.name})"
                    )

        # Check residential-hospital distance
        residential = [n for n, t in self.assignment.items() if t == LocationType.RESIDENTIAL]
        hospitals   = [n for n, t in self.assignment.items() if t == LocationType.HOSPITAL]
        for res in residential:
            if hospitals:
                try:
                    dist = min(nx.shortest_path_length(graph, res, h) for h in hospitals)
                    if dist > 3:
                        violations.append(f"Residential {res} is {dist} hops from nearest hospital (>3)")
                except nx.NetworkXNoPath:
                    violations.append(f"Residential {res} has no path to any hospital")

        # Check power-plant industrial proximity
        power_plants = [n for n, t in self.assignment.items() if t == LocationType.POWER_PLANT]
        industrial   = [n for n, t in self.assignment.items() if t == LocationType.INDUSTRIAL]
        for pp in power_plants:
            if industrial:
                try:
                    dist = min(nx.shortest_path_length(graph, pp, i) for i in industrial)
                    if dist > 2:
                        violations.append(f"PowerPlant {pp} is {dist} hops from nearest industrial (>2)")
                except nx.NetworkXNoPath:
                    violations.append(f"PowerPlant {pp} has no path to any industrial zone")

        return violations
