"""
simulation/simulation_manager.py
=================================
Orchestrates the configurable-length CityMind simulation.

Each simulation step
--------------------
1.  Tick flood timers (clear expired blocks).
2.  Randomly flood 0–2 roads with random TTL.
3.  Update risk indices (slight random drift + flood proximity boost).
4.  Check if active ambulance route is still valid; replan if needed.
5.  Re-evaluate GA fitness every 5 steps (ambulance reevaluation).
6.  Update ML crime predictions every 7 steps.
7.  Publish SIM_STEP event with full step data.

Day/night cycle
---------------
First half of total steps = day, remainder = night (first ~half / second ~half).
Night increases flood probability and risk drift.

Weather
-------
Random weather intensity (0–1) per step affects flood chance and
node risk drift magnitude.
"""

from __future__ import annotations
from typing import Optional, List, Dict
import random
import time

from core.graph_manager import GraphManager
from core.node import LocationType
from core.event_bus import EventBus, Event, EventType
from algorithms.csp_solver import CSPSolver
from algorithms.road_network import RoadNetworkBuilder
from algorithms.genetic_algorithm import GeneticAlgorithmSolver
from algorithms.astar_router import AStarRouter
from algorithms.police_deployment import allocate_police_positions
from ml.crime_predictor import CrimePredictor


MIN_SIMULATION_STEPS = 5
MAX_SIMULATION_STEPS = 500
DEFAULT_SIMULATION_STEPS = 20


class SimulationManager:
    """
    Central simulation controller.

    Attributes
    ----------
    step            : Current simulation step (1 … total_simulation_steps).
    running         : True while simulation is active.
    paused          : True when user pauses.
    speed           : Steps per second (controlled by speed slider).
    phase           : 'day' or 'night'.
    weather         : Current weather intensity 0–1.
    ambulance_target: Node ID the ambulance is heading to (for A* demo).
    modules         : Named dict of all AI module instances.
    log             : Text log for UI event panel.
    """

    def __init__(self):
        self.gm              = GraphManager.get_instance()
        self.bus             = EventBus.get_instance()

        # AI modules
        self.csp:     Optional[CSPSolver]             = None
        self.roads:   Optional[RoadNetworkBuilder]    = None
        self.ga:      Optional[GeneticAlgorithmSolver]= None
        self.router:  AStarRouter                     = AStarRouter()
        self.ml:      Optional[CrimePredictor]        = None

        # Simulation state
        self.step:            int   = 0
        self.running:         bool  = False
        self.paused:          bool  = False
        self.speed:           float = 1.0   # steps per second
        self.phase:           str   = "day"
        self.weather:         float = 0.0
        self.ambulance_source: Optional[int] = None
        self.ambulance_target: Optional[int] = None
        self.log:             List[str] = []

        # Coverage / heatmap caches
        self.coverage_map: Dict[int, float] = {}
        self.crime_map:    Dict[int, float] = {}
        # ML-driven police deployment (Challenge 5)
        self.police_nodes: List[int] = []

        self.total_simulation_steps: int = DEFAULT_SIMULATION_STEPS

        # Subscribe to events for logging
        self.bus.subscribe(EventType.EDGE_FLOODED,      self._log_flood)
        self.bus.subscribe(EventType.ASTAR_REPLAN,      self._log_replan)
        self.bus.subscribe(EventType.ML_PREDICTED,      self._log_ml)
        self.bus.subscribe(EventType.GA_COMPLETE,       self._log_ga)

    # ------------------------------------------------------------------ #
    #  Initialisation                                                      #
    # ------------------------------------------------------------------ #

    def initialise(self, grid_w: int = 10, grid_h: int = 10,
                   cell_px: int = 60, origin_x: int = 20, origin_y: int = 60,
                   total_simulation_steps: int = DEFAULT_SIMULATION_STEPS) -> None:
        """
        Build graph and run all AI modules in sequence.
        This is the setup phase before the live simulation begins.
        """
        ts = max(MIN_SIMULATION_STEPS,
                 min(MAX_SIMULATION_STEPS, int(total_simulation_steps)))
        self.total_simulation_steps = ts

        self._log_msg("=== CityMind Initialising ===")

        # 1. Build grid graph
        self.gm.build_grid(grid_w, grid_h, cell_px, origin_x, origin_y)
        self._log_msg(f"Grid built: {grid_w}×{grid_h} ({grid_w*grid_h} nodes)")

        # 2. CSP — place buildings
        self._log_msg("[CSP] Solving city layout...")
        self.csp = CSPSolver()
        self.csp.solve()
        violations = self.csp.validate_solution()
        self._log_msg(f"[CSP] Done. Violations: {len(violations)}")

        self.gm.assign_primary_facilities()
        if self.gm.primary_hospital_id is not None and self.gm.primary_depot_id is not None:
            self._log_msg(
                f"[CSP] Primary hospital {self.gm.primary_hospital_id}, "
                f"primary depot {self.gm.primary_depot_id}"
            )

        # 3. MST — build road network
        self._log_msg("[MST] Building road network...")
        self.roads = RoadNetworkBuilder()
        self.roads.build()
        self._log_msg(f"[MST] Done. Bridges: {len(self.roads.bridge_edges)}")

        # 4. GA — optimise ambulance placement
        self._log_msg("[GA] Optimising ambulance placement...")
        self.ga = GeneticAlgorithmSolver()
        self.ga.evolve()
        self.coverage_map = self.ga.coverage_heatmap()
        self._log_msg(f"[GA] Done. Best fitness: {self.ga.best_fitness:.2f}")

        # 5. ML — crime prediction
        self._log_msg("[ML] Training crime prediction model...")
        self.ml = CrimePredictor()
        self.ml.run_pipeline()
        self.crime_map = self.ml.crime_heatmap()
        self._log_msg("[ML] Done. Predictions applied.")

        self._deploy_police()

        # 6. Set up initial A* route: depot → nearest hospital
        self._setup_initial_route()

        self.step    = 0
        self.running = True
        self.paused  = True   # user presses play to start
        self._log_msg("=== Ready. Press PLAY to begin simulation ===")

    def _deploy_police(self) -> None:
        """Place 10 officers from current ``crime_map`` (refreshed with ML)."""
        self.police_nodes = allocate_police_positions(self.crime_map)
        if self.police_nodes:
            preview = ", ".join(str(n) for n in self.police_nodes[:5])
            more = "..." if len(self.police_nodes) > 5 else ""
            self._log_msg(
                f"[Police] Deployed {len(self.police_nodes)} units at nodes "
                f"{preview}{more}"
            )

    def _setup_initial_route(self) -> None:
        """Find a good source/target pair for A* demonstration."""
        depots    = self.gm.get_nodes_by_type(LocationType.AMBULANCE_DEPOT)
        hospitals = self.gm.get_nodes_by_type(LocationType.HOSPITAL)
        if self.gm.primary_depot_id is not None and self.gm.primary_hospital_id is not None:
            self.ambulance_source = self.gm.primary_depot_id
            self.ambulance_target = self.gm.primary_hospital_id
            self.router.start_route(self.ambulance_source, self.ambulance_target)
            self._log_msg(
                f"[A*] Route: primary depot {self.ambulance_source} -> "
                f"primary hospital {self.ambulance_target}"
            )
        elif depots and hospitals:
            self.ambulance_source = depots[0].node_id
            self.ambulance_target = hospitals[0].node_id
            self.router.start_route(self.ambulance_source, self.ambulance_target)
            self._log_msg(f"[A*] Route: depot {self.ambulance_source} -> hospital {self.ambulance_target}")

    # ------------------------------------------------------------------ #
    #  Simulation loop                                                     #
    # ------------------------------------------------------------------ #

    def tick(self) -> bool:
        """
        Advance the simulation by one step.
        Returns True if more steps remain, False if simulation is complete.
        Called by the Pygame main loop at the configured speed.
        """
        if self.paused or not self.running:
            return self.running

        if self.step >= self.total_simulation_steps:
            self.running = False
            self._log_msg("=== Simulation Complete ===")
            return False

        self.step += 1
        self._log_msg(f"\n── STEP {self.step} ──")

        # Day/night cycle — split timeline at midpoint of configured length
        half = max(1, self.total_simulation_steps // 2)
        self.phase   = "day" if self.step <= half else "night"
        self.weather = random.uniform(0.0, 1.0)
        night_mult   = 1.5 if self.phase == "night" else 1.0

        # 1. Clear expired floods
        cleared = self.gm.tick_floods()
        if cleared:
            self._log_msg(f"  Flood cleared: {cleared}")

        # 2. Random new flood events
        self._trigger_random_floods(night_mult)

        # 3. Update risk indices
        self._update_risks(night_mult)

        # 4. Advance ambulance along route (1 step)
        self._advance_ambulance()

        # 5. GA re-evaluation every 5 steps
        if self.step % 5 == 0 and self.ga:
            self._log_msg("  [GA] Re-evaluating ambulance placement...")
            self.ga.evolve()
            self.coverage_map = self.ga.coverage_heatmap()

        # 6. ML re-prediction every 7 steps
        if self.step % 7 == 0 and self.ml:
            self._log_msg("  [ML] Refreshing crime predictions...")
            self.ml.run_pipeline()
            self.crime_map = self.ml.crime_heatmap()
            self._deploy_police()

        # Publish step event
        self.bus.publish(Event(EventType.SIM_STEP,
                               data={"step": self.step, "phase": self.phase,
                                     "weather": round(self.weather, 2)},
                               step=self.step))
        return True

    # ------------------------------------------------------------------ #
    #  Flood events                                                        #
    # ------------------------------------------------------------------ #

    def _trigger_random_floods(self, night_mult: float) -> None:
        """
        Randomly flood 0–2 edges per step.
        Probability and TTL scale with weather intensity and night multiplier.
        Bridges have higher flood probability (they're more exposed).
        """
        passable_edges = [(key, e) for key, e in self.gm.edges.items()
                          if not e.blocked and e.effective_weight != float('inf')]
        if not passable_edges:
            return

        n_floods = random.choices([0, 1, 2], weights=[0.5, 0.35, 0.15])[0]
        flood_prob = 0.3 * self.weather * night_mult

        for _ in range(n_floods):
            if random.random() < flood_prob:
                key, edge = random.choice(passable_edges)
                ttl = random.randint(2, 5)
                if edge.bridge:
                    ttl += 2   # bridges take longer to fix
                self.gm.flood_edge(edge.u, edge.v, ttl)

    # ------------------------------------------------------------------ #
    #  Risk updates                                                        #
    # ------------------------------------------------------------------ #

    def _update_risks(self, night_mult: float) -> None:
        """
        Drift risk indices slightly each step.
        Flooded-adjacent nodes get a risk boost.
        Night increases risk drift magnitude.
        """
        drift_scale = 0.05 * night_mult * self.weather
        for nid, node in self.gm.nodes.items():
            drift = random.uniform(-drift_scale, drift_scale * 1.5)
            # Boost risk if adjacent to a flooded edge
            for nb_id in node.neighbors:
                edge = self.gm.get_edge(nid, nb_id)
                if edge and edge.blocked:
                    drift += 0.05
                    break
            new_risk = max(0.0, min(1.0, node.risk_index + drift))
            self.gm.update_node_risk(nid, new_risk)

    # ------------------------------------------------------------------ #
    #  Ambulance movement                                                  #
    # ------------------------------------------------------------------ #

    def _advance_ambulance(self) -> None:
        """Move the ambulance one hop; replan if route is blocked."""
        if not self.router.current_path:
            # Restart route if no active path
            if self.ambulance_source and self.ambulance_target:
                self.router.start_route(self.ambulance_source, self.ambulance_target)
            return

        if self.router.is_route_blocked():
            if self.ambulance_target:
                self.router.replan(self.ambulance_target)
            return

        next_node = self.router.advance()
        if next_node is None:
            # Route complete — pick a new target
            self._log_msg("  [A*] Route complete. Selecting new target...")
            self._pick_new_route()

    def _pick_new_route(self) -> None:
        """
        Start the next leg after a route completes.

        For primary facilities: alternate **return to base** (hospital -> depot)
        and **outbound mission** (depot -> hospital) so the ambulance does not
        teleport back to the depot after each delivery.
        """
        hospitals = self.gm.get_nodes_by_type(LocationType.HOSPITAL)
        depots    = self.gm.get_nodes_by_type(LocationType.AMBULANCE_DEPOT)
        ph        = self.gm.primary_hospital_id
        pd        = self.gm.primary_depot_id

        if ph is not None and pd is not None:
            here = self.router.current_node()
            if here == ph:
                self.ambulance_source = ph
                self.ambulance_target = pd
                leg = "return to depot"
            else:
                self.ambulance_source = pd
                self.ambulance_target = ph
                leg = "outbound to hospital"
            ok = self.router.start_route(self.ambulance_source, self.ambulance_target)
            if ok:
                self._log_msg(
                    f"  [A*] New route ({leg}): "
                    f"{self.ambulance_source} -> {self.ambulance_target}"
                )
            return

        if depots:
            self.ambulance_source = random.choice(depots).node_id
        if hospitals:
            self.ambulance_target = random.choice(hospitals).node_id
        if self.ambulance_source is not None and self.ambulance_target is not None:
            ok = self.router.start_route(self.ambulance_source, self.ambulance_target)
            if ok:
                self._log_msg(
                    f"  [A*] New route: {self.ambulance_source} -> {self.ambulance_target}"
                )

    # ------------------------------------------------------------------ #
    #  Controls                                                            #
    # ------------------------------------------------------------------ #

    def play(self) -> None:
        self.paused  = False
        self.running = True
        self.bus.publish(Event(EventType.SIM_RESUMED))

    def pause(self) -> None:
        self.paused = True
        self.bus.publish(Event(EventType.SIM_PAUSED))

    def reset(self) -> None:
        """Full reset — tears down singleton state and reinitialises."""
        GraphManager.reset()
        EventBus.reset()
        # Reinitialise
        self.__init__()
        self.bus.publish(Event(EventType.SIM_RESET))

    def set_speed(self, speed: float) -> None:
        """Set simulation steps per second (0.25 – 5.0)."""
        self.speed = max(0.25, min(5.0, speed))
        self.bus.publish(Event(EventType.SPEED_CHANGED, data={"speed": self.speed}))

    def configure_total_steps(self, n: int) -> bool:
        """
        Set total_simulation_steps only while no step has been executed yet (step == 0).
        Value is clamped to [MIN_SIMULATION_STEPS, MAX_SIMULATION_STEPS].
        Returns False if the run has already advanced (edit not allowed).
        """
        if self.step > 0:
            return False
        self.total_simulation_steps = max(
            MIN_SIMULATION_STEPS, min(MAX_SIMULATION_STEPS, int(n))
        )
        return True

    # ------------------------------------------------------------------ #
    #  Logging helpers                                                     #
    # ------------------------------------------------------------------ #

    def _log_msg(self, msg: str) -> None:
        self.log.append(msg)
        if len(self.log) > 300:
            self.log.pop(0)
        print(msg)

    def _log_flood(self, event: Event) -> None:
        key = event.data.get("edge", "?")
        ttl = event.data.get("ttl", "?")
        self._log_msg(f"  [FLOOD] Edge {key} blocked for {ttl} steps")

    def _log_replan(self, event: Event) -> None:
        d = event.data
        self._log_msg(
            f"  [A*] Replan #{d.get('replan_num','?')}: "
            f"old_cost={d.get('old_cost',0):.1f} → new_cost={d.get('new_cost',0):.1f}"
        )

    def _log_ml(self, event: Event) -> None:
        self._log_msg(f"  [ML] Predictions updated for {event.data.get('samples','?')} nodes")

    def _log_ga(self, event: Event) -> None:
        self._log_msg(f"  [GA] Best fitness: {event.data.get('best_fitness',0):.2f}")
