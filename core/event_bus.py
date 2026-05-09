"""
core/event_bus.py
=================
Lightweight publish-subscribe event bus.
Modules publish events without knowing who listens.
This decouples the simulation, UI, and AI modules.
"""

from __future__ import annotations
from enum import Enum, auto
from typing import Callable, Dict, List, Any
from dataclasses import dataclass, field
import time


class EventType(Enum):
    """All event types that can flow through the bus."""
    # Simulation lifecycle
    SIM_STEP          = auto()   # A new simulation step has begun
    SIM_RESET         = auto()   # Simulation was reset
    SIM_PAUSED        = auto()
    SIM_RESUMED       = auto()

    # Graph mutations
    EDGE_FLOODED      = auto()   # Road flooded, edge blocked
    EDGE_CLEARED      = auto()   # Flood subsided, edge unblocked
    NODE_RISK_UPDATED = auto()   # A node's risk_index changed
    GRAPH_REBUILT     = auto()   # Entire graph was regenerated

    # Algorithm events
    CSP_PLACED        = auto()   # CSP placed a building
    CSP_CONFLICT      = auto()   # CSP detected constraint violation
    CSP_COMPLETE      = auto()   # CSP solver finished

    MST_EDGE_ADDED    = auto()   # Kruskal added an MST edge
    MST_COMPLETE      = auto()
    BRIDGE_FOUND      = auto()   # Tarjan found a bridge

    GA_GENERATION     = auto()   # GA completed one generation
    GA_COMPLETE       = auto()

    ASTAR_START       = auto()   # A* began routing
    ASTAR_COMPLETE    = auto()   # A* found (or failed) a path
    ASTAR_REPLAN      = auto()   # Dynamic replan triggered

    ML_TRAINED        = auto()   # ML model finished training
    ML_PREDICTED      = auto()   # Crime predictions applied to graph

    # UI events
    OVERLAY_CHANGED   = auto()
    NODE_HOVERED      = auto()
    SPEED_CHANGED     = auto()


@dataclass
class Event:
    """
    Wraps an event type with arbitrary payload data and timestamp.
    """
    event_type: EventType
    data:       Any   = field(default=None)
    timestamp:  float = field(default_factory=time.time)
    step:       int   = field(default=0)

    def __str__(self) -> str:
        return f"[{self.event_type.name}] step={self.step} data={self.data}"


class EventBus:
    """
    Singleton publish-subscribe event bus.

    Usage
    -----
    bus = EventBus.get_instance()
    bus.subscribe(EventType.EDGE_FLOODED, my_handler)
    bus.publish(Event(EventType.EDGE_FLOODED, data={"edge": (3,4)}))
    """

    _instance: "EventBus | None" = None

    def __init__(self):
        # Dict mapping EventType → list of callback functions
        self._subscribers: Dict[EventType, List[Callable[[Event], None]]] = {}
        # Ring buffer for event log (last N events)
        self._log: List[Event] = []
        self._log_max: int = 200

    @classmethod
    def get_instance(cls) -> "EventBus":
        """Returns the singleton EventBus instance."""
        if cls._instance is None:
            cls._instance = EventBus()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Resets the singleton (used between test runs)."""
        cls._instance = None

    def subscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """Register a callback for a given event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> None:
        """Remove a previously registered callback."""
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
            except ValueError:
                pass

    def publish(self, event: Event) -> None:
        """
        Dispatch an event to all registered subscribers.
        Events are also appended to the internal log ring-buffer.
        Subscribers are called synchronously in registration order.
        """
        # Add to log ring-buffer
        self._log.append(event)
        if len(self._log) > self._log_max:
            self._log.pop(0)

        # Dispatch to subscribers
        for callback in self._subscribers.get(event.event_type, []):
            try:
                callback(event)
            except Exception as exc:
                # Never let a bad subscriber crash the bus
                print(f"[EventBus] ERROR in subscriber for {event.event_type}: {exc}")

    def get_log(self, last_n: int = 20) -> List[Event]:
        """Returns the last N events from the log."""
        return self._log[-last_n:]

    def clear_log(self) -> None:
        self._log.clear()
