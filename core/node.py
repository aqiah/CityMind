"""
core/node.py
============
Defines the Node data class and LocationType enum.
Each node represents a cell in the city grid.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional


class LocationType(Enum):
    """Enum representing the type of facility/zone at each city node."""
    EMPTY = auto()
    RESIDENTIAL = auto()
    HOSPITAL = auto()
    SCHOOL = auto()
    INDUSTRIAL = auto()
    POWER_PLANT = auto()
    AMBULANCE_DEPOT = auto()

    def color(self) -> tuple:
        """Returns the RGBA color associated with this location type for rendering."""
        COLOR_MAP = {
            LocationType.EMPTY:          (30, 34, 45, 255),
            LocationType.RESIDENTIAL:    (70, 130, 180, 255),   # steel blue
            LocationType.HOSPITAL:       (50, 205, 100, 255),   # green
            LocationType.SCHOOL:         (255, 215, 0, 255),    # gold
            LocationType.INDUSTRIAL:     (180, 90, 40, 255),    # rust orange
            LocationType.POWER_PLANT:    (220, 80, 220, 255),   # magenta
            LocationType.AMBULANCE_DEPOT:(0, 200, 255, 255),    # cyan
        }
        return COLOR_MAP.get(self, (100, 100, 100, 255))

    def label(self) -> str:
        """Short label used in the UI overlay."""
        LABELS = {
            LocationType.EMPTY:          "—",
            LocationType.RESIDENTIAL:    "RES",
            LocationType.HOSPITAL:       "HOSP",
            LocationType.SCHOOL:         "SCH",
            LocationType.INDUSTRIAL:     "IND",
            LocationType.POWER_PLANT:    "PWR",
            LocationType.AMBULANCE_DEPOT:"AMB",
        }
        return LABELS.get(self, "?")

    def display_name(self) -> str:
        """Human-readable name for tooltips and legends."""
        NAMES = {
            LocationType.EMPTY:           "Empty",
            LocationType.RESIDENTIAL:     "Residential",
            LocationType.HOSPITAL:        "Hospital",
            LocationType.SCHOOL:          "School",
            LocationType.INDUSTRIAL:      "Industrial",
            LocationType.POWER_PLANT:     "Power plant",
            LocationType.AMBULANCE_DEPOT: "Ambulance depot",
        }
        return NAMES.get(self, "?")


@dataclass
class Node:
    """
    Represents a single cell/node in the city grid.

    Attributes
    ----------
    node_id        : Unique integer identifier.
    x              : Grid column (0-based).
    y              : Grid row (0-based).
    location_type  : What kind of facility is placed here.
    population     : Population density (0.0–1.0 normalised).
    risk_index     : Current risk score (0.0–1.0).
    accessible     : Whether this node is reachable (not permanently blocked).
    crime_level    : ML-predicted crime category ("High"/"Medium"/"Low"/None).
    neighbors      : List of adjacent node_ids (populated by GraphManager).
    cluster_label  : K-Means cluster label assigned by ML module.
    """

    node_id:       int
    x:             int
    y:             int
    location_type: LocationType   = field(default=LocationType.EMPTY)
    population:    float          = field(default=0.0)       # 0–1 normalised
    risk_index:    float          = field(default=0.0)       # 0–1 normalised
    accessible:    bool           = field(default=True)
    crime_level:   Optional[str]  = field(default=None)      # "High"/"Medium"/"Low"
    neighbors:     List[int]      = field(default_factory=list)
    cluster_label: int            = field(default=-1)

    # Pixel-space coordinates (set by GraphManager after layout is known)
    px: int = field(default=0)
    py: int = field(default=0)

    def __hash__(self) -> int:
        return hash(self.node_id)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Node):
            return self.node_id == other.node_id
        return NotImplemented

    def risk_color(self) -> tuple:
        """
        Returns an RGB color reflecting the node's risk_index.
        Interpolates from cool-blue (low risk) to hot-red (high risk).
        """
        r = int(self.risk_index * 220)
        g = int((1.0 - self.risk_index) * 100)
        b = int((1.0 - self.risk_index) * 200)
        return (min(r, 255), max(g, 0), max(b, 0))

    def crime_color(self) -> tuple:
        """Returns a distinct color per crime prediction level."""
        if self.crime_level == "High":
            return (220, 50, 50)
        if self.crime_level == "Medium":
            return (220, 160, 50)
        return (50, 180, 100)   # Low / None

    def to_dict(self) -> dict:
        """Serialise the node to a plain dict (used for logging / stats panel)."""
        return {
            "id":         self.node_id,
            "pos":        (self.x, self.y),
            "type":       self.location_type.name,
            "population": round(self.population, 3),
            "risk":       round(self.risk_index, 3),
            "crime":      self.crime_level or "—",
            "accessible": self.accessible,
        }
