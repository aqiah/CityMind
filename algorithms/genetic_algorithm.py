"""
algorithms/genetic_algorithm.py
================================
Challenge 3 — Genetic Algorithm for Ambulance Placement.

Goal
----
Minimise worst-case response time: the furthest any node is from its
nearest ambulance depot.

Representation
--------------
Chromosome: a list of N node IDs where ambulances are stationed.
N = number of ambulance depots placed by CSP.

Genetic operators
-----------------
* Tournament selection (size k=3)
* Single-point crossover
* Random-reset mutation
* Elitism — top E individuals always survive

Fitness function
----------------
  fitness = −max(min_dist_to_ambulance for each node)
  (negated so higher = better; we minimise worst case)

Warm restart
------------
After convergence, inject the current elite into a fresh population
to escape local optima.  Repeated up to MAX_RESTARTS times.
"""

from __future__ import annotations
from typing import List, Tuple, Dict, Optional
import random
import math
import networkx as nx

from core.graph_manager import GraphManager
from core.node import LocationType
from core.event_bus import EventBus, Event, EventType


# ──────────────────────────────────────────────────────── #
#  Hyper-parameters                                         #
# ──────────────────────────────────────────────────────── #
POP_SIZE        = 40
NUM_GENERATIONS = 80
TOURNAMENT_K    = 3
CROSSOVER_RATE  = 0.80
MUTATION_RATE   = 0.20
ELITE_COUNT     = 4
MAX_RESTARTS    = 2
CONVERGENCE_THR = 10   # plateau generations before restart


Chromosome = List[int]   # list of node_ids


class GeneticAlgorithmSolver:
    """
    Optimises ambulance placement using a Genetic Algorithm.

    Attributes
    ----------
    n_ambulances    : Number of ambulances to place.
    candidate_nodes : All passable node IDs (ambulances can park anywhere).
    best_chromosome : Best solution found across all generations.
    best_fitness    : Fitness of best_chromosome (higher = better).
    history         : [(generation, best_fitness, avg_fitness), ...]
    population      : Current population.
    """

    def __init__(self, n_ambulances: Optional[int] = None):
        self.gm  = GraphManager.get_instance()
        self.bus = EventBus.get_instance()

        # Number of ambulances = number of depots placed by CSP (or default 3)
        depots = self.gm.get_nodes_by_type(LocationType.AMBULANCE_DEPOT)
        self.n_ambulances = n_ambulances or max(len(depots), 3)

        # Pre-compute shortest path distances for fitness evaluation
        self.candidate_nodes: List[int] = list(self.gm.all_node_ids())
        self._dist_cache: Dict[Tuple[int,int], float] = {}

        self.population:       List[Chromosome] = []
        self.best_chromosome:  Chromosome       = []
        self.best_fitness:     float            = -float('inf')
        self.history:          List[Tuple]      = []  # (gen, best, avg)
        self._precompute_distances()

    # ------------------------------------------------------------------ #
    #  Distance pre-computation                                            #
    # ------------------------------------------------------------------ #

    def _precompute_distances(self) -> None:
        """
        Pre-compute all-pairs shortest paths on the passable graph.
        Uses NetworkX which implements Dijkstra internally.
        Cached as a dict for O(1) lookup during fitness evaluation.
        """
        passable = self.gm.get_passable_graph()
        try:
            lengths = dict(nx.all_pairs_dijkstra_path_length(
                passable, weight='weight', cutoff=None))
            for src, dests in lengths.items():
                for dst, dist in dests.items():
                    self._dist_cache[(src, dst)] = dist
        except Exception:
            # Fallback: use Euclidean for disconnected graphs
            for a in self.candidate_nodes:
                for b in self.candidate_nodes:
                    self._dist_cache[(a, b)] = self.gm.euclidean_distance(a, b)

    def _min_dist_to_ambulance(self, node_id: int, chromosome: Chromosome) -> float:
        """Returns the shortest distance from node_id to the nearest ambulance in chromosome."""
        if not chromosome:
            return float('inf')
        return min(self._dist_cache.get((node_id, amb), float('inf'))
                   for amb in chromosome)

    # ------------------------------------------------------------------ #
    #  Fitness function                                                    #
    # ------------------------------------------------------------------ #

    def fitness(self, chromosome: Chromosome) -> float:
        """
        Fitness = −worst_case_response_time.
        We want to MINIMISE the maximum distance to any ambulance,
        so we return the negative to turn it into a maximisation problem.
        Penalise duplicate placements (duplicate genes waste coverage).
        """
        if len(set(chromosome)) < len(chromosome):
            # Penalty for duplicates
            return -float('inf')

        worst = max(
            self._min_dist_to_ambulance(nid, chromosome)
            for nid in self.candidate_nodes
        )
        return -worst   # higher is better

    # ------------------------------------------------------------------ #
    #  Initialisation                                                      #
    # ------------------------------------------------------------------ #

    def _random_chromosome(self) -> Chromosome:
        """Generate a random chromosome with unique node IDs."""
        return random.sample(self.candidate_nodes, self.n_ambulances)

    def _initialise_population(self, inject: Optional[List[Chromosome]] = None) -> None:
        """
        Create initial population.
        If 'inject' is given (warm restart), keep elite individuals.
        """
        self.population = []
        if inject:
            self.population.extend(inject[:ELITE_COUNT])
        while len(self.population) < POP_SIZE:
            self.population.append(self._random_chromosome())

    # ------------------------------------------------------------------ #
    #  Selection                                                           #
    # ------------------------------------------------------------------ #

    def _tournament_select(self) -> Chromosome:
        """
        Tournament selection: pick k individuals randomly, return the fittest.
        Larger k → more selection pressure (fitter individuals win more often).
        """
        competitors = random.sample(self.population, min(TOURNAMENT_K, len(self.population)))
        return max(competitors, key=self.fitness)

    # ------------------------------------------------------------------ #
    #  Crossover                                                           #
    # ------------------------------------------------------------------ #

    def _crossover(self, parent_a: Chromosome, parent_b: Chromosome) -> Tuple[Chromosome, Chromosome]:
        """
        Single-point crossover.
        Swap tails at a random split point.
        After swap, remove duplicates by filling with random unused nodes.
        """
        if random.random() > CROSSOVER_RATE:
            return parent_a[:], parent_b[:]

        point = random.randint(1, self.n_ambulances - 1)
        child_a = parent_a[:point] + parent_b[point:]
        child_b = parent_b[:point] + parent_a[point:]

        child_a = self._fix_duplicates(child_a)
        child_b = self._fix_duplicates(child_b)
        return child_a, child_b

    def _fix_duplicates(self, chrom: Chromosome) -> Chromosome:
        """Replace duplicate gene values with random unused node IDs."""
        seen = set()
        fixed = []
        duplicates = []
        for gene in chrom:
            if gene in seen:
                duplicates.append(gene)
            else:
                seen.add(gene)
                fixed.append(gene)
        # Replace duplicates with random unused nodes
        available = [n for n in self.candidate_nodes if n not in seen]
        random.shuffle(available)
        for i, _ in enumerate(duplicates):
            if available:
                replacement = available.pop()
                fixed.append(replacement)
                seen.add(replacement)
        return fixed[:self.n_ambulances]

    # ------------------------------------------------------------------ #
    #  Mutation                                                            #
    # ------------------------------------------------------------------ #

    def _mutate(self, chromosome: Chromosome) -> Chromosome:
        """
        Random-reset mutation: replace a random gene with a new random node.
        Applied with probability MUTATION_RATE per chromosome.
        """
        if random.random() > MUTATION_RATE:
            return chromosome[:]
        mutated = chromosome[:]
        idx = random.randrange(len(mutated))
        new_node = random.choice([n for n in self.candidate_nodes if n not in mutated])
        mutated[idx] = new_node
        return mutated

    # ------------------------------------------------------------------ #
    #  Main GA loop                                                        #
    # ------------------------------------------------------------------ #

    def evolve(self) -> Chromosome:
        """
        Run the full GA with warm restarts.
        Returns the best chromosome found.
        """
        self._initialise_population()
        plateau = 0

        for restart in range(MAX_RESTARTS + 1):
            for gen in range(NUM_GENERATIONS):
                # Evaluate and sort
                scored = [(self.fitness(c), c) for c in self.population]
                scored.sort(key=lambda x: x[0], reverse=True)

                best_fit  = scored[0][0]
                avg_fit   = sum(f for f, _ in scored) / len(scored)
                self.history.append((len(self.history), best_fit, avg_fit))

                # Track global best
                if best_fit > self.best_fitness:
                    self.best_fitness    = best_fit
                    self.best_chromosome = scored[0][1][:]
                    plateau = 0
                else:
                    plateau += 1

                # Publish generation stats to event bus
                self.bus.publish(Event(EventType.GA_GENERATION,
                                       data={"gen": len(self.history),
                                             "best": best_fit,
                                             "avg":  avg_fit,
                                             "restart": restart}))

                # Next generation
                new_pop = [c for _, c in scored[:ELITE_COUNT]]   # elitism
                while len(new_pop) < POP_SIZE:
                    p1 = self._tournament_select()
                    p2 = self._tournament_select()
                    c1, c2 = self._crossover(p1, p2)
                    new_pop.append(self._mutate(c1))
                    if len(new_pop) < POP_SIZE:
                        new_pop.append(self._mutate(c2))
                self.population = new_pop

                # Check for convergence plateau → trigger warm restart
                if plateau >= CONVERGENCE_THR:
                    break

            # Warm restart: inject elite from this run into fresh population
            if restart < MAX_RESTARTS:
                elite = [c for _, c in sorted(
                    [(self.fitness(c), c) for c in self.population],
                    key=lambda x: x[0], reverse=True
                )[:ELITE_COUNT]]
                self._initialise_population(inject=elite)
                plateau = 0

        # Apply best placement to graph
        self._apply_best_placement()

        self.bus.publish(Event(EventType.GA_COMPLETE,
                               data={"best_fitness": self.best_fitness,
                                     "placement": self.best_chromosome,
                                     "generations": len(self.history)}))
        return self.best_chromosome

    def _apply_best_placement(self) -> None:
        """
        Mark the nodes in best_chromosome as AMBULANCE_DEPOT in the graph.
        Existing depot placements from CSP are overridden.
        """
        # Clear existing depots
        for node in self.gm.get_nodes_by_type(LocationType.AMBULANCE_DEPOT):
            from core.node import LocationType as LT
            self.gm.set_location_type(node.node_id, LT.EMPTY)

        for nid in self.best_chromosome:
            self.gm.set_location_type(nid, LocationType.AMBULANCE_DEPOT)

    # ------------------------------------------------------------------ #
    #  Coverage analysis                                                   #
    # ------------------------------------------------------------------ #

    def coverage_heatmap(self) -> Dict[int, float]:
        """
        Returns dict {node_id: distance_to_nearest_ambulance}.
        Normalised 0–1 (0 = ambulance is here, 1 = furthest point).
        Used for the UI coverage heatmap overlay.
        """
        if not self.best_chromosome:
            return {}
        raw = {nid: self._min_dist_to_ambulance(nid, self.best_chromosome)
               for nid in self.candidate_nodes}
        max_d = max(raw.values()) or 1.0
        return {nid: d / max_d for nid, d in raw.items()}
