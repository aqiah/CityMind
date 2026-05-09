"""
core/edge.py
============
Defines the Edge data class connecting two nodes in the city graph.
Edges can be dynamically blocked (flooded roads) or have their weight
updated by external events.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import math


@dataclass
class Edge:
    """
    Represents a road/connection between two city nodes.

    Attributes
    ----------
    u        : Source node id.
    v        : Destination node id.
    weight   : Base travel cost (Euclidean distance by default).
    blocked  : If True the edge is impassable (flood / damage).
    bridge   : Marked True by Tarjan's algorithm if removing it disconnects the graph.
    augmented: True if this edge was added during hospital-depot augmentation.
    flood_ttl: Remaining simulation steps the flood lasts (0 = not flooded).
    """

    u:         int
    v:         int
    weight:    float = field(default=1.0)
    blocked:   bool  = field(default=False)
    bridge:    bool  = field(default=False)
    augmented: bool  = field(default=False)
    flood_ttl: int   = field(default=0)

    # Effective weight seen by A* — modified by risk multipliers and blocking
    effective_weight: float = field(default=1.0)

    def __post_init__(self):
        # Ensure effective weight is initialised to base weight
        if self.effective_weight == 1.0 and self.weight != 1.0:
            self.effective_weight = self.weight

    def key(self) -> tuple:
        """Canonical undirected key (smaller id first)."""
        return (min(self.u, self.v), max(self.u, self.v))

    def update_effective_weight(self, risk_u: float, risk_v: float) -> None:
        """
        Recompute effective weight based on endpoint risk indices.
        Higher risk on either endpoint increases the traversal cost.
        Formula: effective = weight * (1 + 0.5*(risk_u + risk_v))
        This ensures A* naturally avoids high-risk corridors.
        """
        if self.blocked:
            self.effective_weight = float('inf')
        else:
            avg_risk = (risk_u + risk_v) / 2.0
            self.effective_weight = self.weight * (1.0 + 0.5 * avg_risk)

    def color(self) -> tuple:
        """Render colour based on edge state."""
        if self.blocked:
            return (220, 50, 50)      # red — flooded
        if self.bridge:
            return (255, 165, 0)      # orange — bridge (critical)
        if self.augmented:
            return (0, 255, 200)      # cyan glow — augmented hospital link
        return (80, 100, 130)         # default road colour

    def __hash__(self) -> int:
        return hash(self.key())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Edge):
            return self.key() == other.key()
        return NotImplemented
