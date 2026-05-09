"""
ml/crime_predictor.py
=====================
Challenge 5 — Machine Learning Crime Prediction Pipeline.

Pipeline
--------
1. Feature extraction from GraphManager nodes.
2. K-Means clustering (unsupervised) → cluster_label feature.
3. Synthetic crime dataset generation with Gaussian noise.
4. Random Forest classifier training (supervised).
5. Inference on all nodes → crime_level ∈ {High, Medium, Low}.
6. Risk multiplier application: High×1.5, Medium×1.2, Low×1.0.
7. Feature importance extraction for the AI explanation panel.

Why these algorithms?
---------------------
K-Means clusters nodes by spatial/density similarity before classification.
The cluster label becomes an additional feature that encodes neighbourhood
context — something a single node's features alone can't capture.

Random Forest is robust to feature correlation and provides built-in
feature importance scores, making it naturally explainable.
"""

from __future__ import annotations
from typing import Dict, List, Tuple, Optional
import math
import random
import numpy as np

from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import MinMaxScaler

from core.graph_manager import GraphManager
from core.node import Node, LocationType
from core.event_bus import EventBus, Event, EventType

# Crime level → risk multiplier
RISK_MULTIPLIERS = {"High": 1.5, "Medium": 1.2, "Low": 1.0}
CRIME_LABELS     = ["Low", "Medium", "High"]
N_CLUSTERS       = 4     # K-Means clusters
N_SYNTHETIC      = 400   # synthetic training samples


class CrimePredictor:
    """
    Full ML pipeline for predicting crime risk on city nodes.

    Attributes
    ----------
    kmeans      : Fitted KMeans model.
    classifier  : Fitted RandomForestClassifier.
    scaler      : MinMaxScaler fitted on training features.
    importances : Feature importance array from Random Forest.
    predictions : Dict {node_id: crime_level_string}.
    """

    def __init__(self):
        self.gm          = GraphManager.get_instance()
        self.bus         = EventBus.get_instance()
        self.kmeans:      Optional[KMeans]                  = None
        self.classifier:  Optional[RandomForestClassifier]  = None
        self.scaler:      MinMaxScaler                      = MinMaxScaler()
        self.importances: List[float]                       = []
        self.predictions: Dict[int, str]                    = {}
        self.feature_names = ["population", "ind_proximity",
                               "loc_type_enc", "cluster_label"]

    # ------------------------------------------------------------------ #
    #  Public pipeline entry                                               #
    # ------------------------------------------------------------------ #

    def run_pipeline(self) -> None:
        """Execute the full ML pipeline end-to-end."""
        node_features = self._extract_features()
        self._run_kmeans(node_features)
        X_train, y_train = self._generate_synthetic_dataset()
        self._train_classifier(X_train, y_train)
        self._infer_all_nodes(node_features)
        self._apply_risk_multipliers()

        self.bus.publish(Event(EventType.ML_TRAINED,
                               data={"n_nodes": len(self.predictions),
                                     "importances": self.importances}))

    # ------------------------------------------------------------------ #
    #  Step 1: Feature extraction                                          #
    # ------------------------------------------------------------------ #

    def _extract_features(self) -> Dict[int, List[float]]:
        """
        Extract raw features from each node.

        Features
        --------
        * population       : Normalised population density (already 0-1).
        * ind_proximity    : Distance to nearest industrial node (normalised).
        * loc_type_enc     : Ordinal encoding of LocationType.
        * cluster_label    : Assigned after K-Means (initially -1).
        """
        industrial_nodes = self.gm.get_nodes_by_type(LocationType.INDUSTRIAL)

        features: Dict[int, List[float]] = {}
        for nid, node in self.gm.nodes.items():
            pop = node.population

            # Distance to nearest industrial zone (normalised by grid diagonal)
            if industrial_nodes:
                grid_diag = math.hypot(self.gm.grid_w, self.gm.grid_h)
                min_ind_dist = min(
                    math.hypot(node.x - ind.x, node.y - ind.y) / grid_diag
                    for ind in industrial_nodes
                )
            else:
                min_ind_dist = 1.0

            # Ordinal location type encoding (normalised 0–1)
            type_enc = self._encode_location_type(node.location_type)

            features[nid] = [pop, min_ind_dist, type_enc, -1.0]  # cluster tbd

        return features

    def _encode_location_type(self, ltype: LocationType) -> float:
        """Ordinal encoding of LocationType for use as a numeric feature."""
        encoding = {
            LocationType.EMPTY:          0.0,
            LocationType.RESIDENTIAL:    0.2,
            LocationType.SCHOOL:         0.3,
            LocationType.HOSPITAL:       0.4,
            LocationType.AMBULANCE_DEPOT:0.5,
            LocationType.POWER_PLANT:    0.7,
            LocationType.INDUSTRIAL:     1.0,
        }
        return encoding.get(ltype, 0.0)

    # ------------------------------------------------------------------ #
    #  Step 2: K-Means clustering                                          #
    # ------------------------------------------------------------------ #

    def _run_kmeans(self, features: Dict[int, List[float]]) -> None:
        """
        K-Means clustering on (population, ind_proximity) features.
        Assigns each node a cluster label that encodes neighbourhood context.
        The label is then appended to the feature vector for the classifier.
        """
        node_ids = list(features.keys())
        X = np.array([[features[n][0], features[n][1]] for n in node_ids])

        self.kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
        labels = self.kmeans.fit_predict(X)

        # Write cluster labels into node objects and feature vectors
        for i, nid in enumerate(node_ids):
            label = int(labels[i])
            self.gm.nodes[nid].cluster_label = label
            features[nid][3] = float(label) / N_CLUSTERS   # normalise

    # ------------------------------------------------------------------ #
    #  Step 3: Synthetic dataset generation                                #
    # ------------------------------------------------------------------ #

    def _generate_synthetic_dataset(self) -> Tuple[np.ndarray, np.ndarray]:
        """
        Generate a synthetic labelled crime dataset with realistic correlations:
        - High-density industrial areas → high crime (with noise).
        - Low-density residential → low crime.
        - Mixed zones → medium crime.
        Gaussian noise is added to avoid over-clean decision boundaries.
        """
        rng = random.Random(2024)
        X_rows, y_rows = [], []

        for _ in range(N_SYNTHETIC):
            pop          = rng.uniform(0.0, 1.0)
            ind_prox     = rng.uniform(0.0, 1.0)   # 0=near industrial
            type_enc     = rng.choice([0.0, 0.2, 0.5, 0.7, 1.0])
            cluster      = rng.uniform(0.0, 1.0)

            # Crime score: higher near industrial, higher population density
            # Gaussian noise σ=0.15 adds realistic uncertainty
            noise = rng.gauss(0.0, 0.15)
            crime_score = (
                0.45 * (1.0 - ind_prox)   # closer to industrial → higher
                + 0.35 * pop              # denser population → higher
                + 0.20 * type_enc         # industrial/power → higher
                + noise
            )

            # Threshold to label
            if crime_score > 0.65:
                label = 2   # High
            elif crime_score > 0.35:
                label = 1   # Medium
            else:
                label = 0   # Low

            X_rows.append([pop, ind_prox, type_enc, cluster])
            y_rows.append(label)

        return np.array(X_rows), np.array(y_rows)

    # ------------------------------------------------------------------ #
    #  Step 4: Train Random Forest                                         #
    # ------------------------------------------------------------------ #

    def _train_classifier(self, X: np.ndarray, y: np.ndarray) -> None:
        """
        Train a Random Forest on the synthetic dataset.
        Random Forest: ensemble of decision trees trained on bootstrap samples.
        Feature importance = mean decrease in impurity across all trees.
        """
        X_scaled = self.scaler.fit_transform(X)
        self.classifier = RandomForestClassifier(
            n_estimators=100,
            max_depth=6,
            random_state=42,
            class_weight='balanced'
        )
        self.classifier.fit(X_scaled, y)
        self.importances = self.classifier.feature_importances_.tolist()

    # ------------------------------------------------------------------ #
    #  Step 5: Inference                                                   #
    # ------------------------------------------------------------------ #

    def _infer_all_nodes(self, features: Dict[int, List[float]]) -> None:
        """
        Run the trained classifier on every city node.
        Stores the predicted crime level string in self.predictions and
        writes it back to the Node objects in the GraphManager.
        """
        if self.classifier is None:
            return

        node_ids = list(features.keys())
        X = np.array([features[nid] for nid in node_ids])
        X_scaled = self.scaler.transform(X)
        raw_preds = self.classifier.predict(X_scaled)

        for i, nid in enumerate(node_ids):
            level = CRIME_LABELS[int(raw_preds[i])]
            self.predictions[nid] = level
            self.gm.nodes[nid].crime_level = level

        self.bus.publish(Event(EventType.ML_PREDICTED,
                               data={"samples": len(node_ids)}))

    # ------------------------------------------------------------------ #
    #  Step 6: Apply risk multipliers                                      #
    # ------------------------------------------------------------------ #

    def _apply_risk_multipliers(self) -> None:
        """
        Update each node's risk_index based on its predicted crime level.
        High crime → risk × 1.5 (capped at 1.0).
        This propagates into A* edge weights automatically via GraphManager.
        """
        for nid, level in self.predictions.items():
            node = self.gm.get_node(nid)
            if node is None:
                continue
            multiplier = RISK_MULTIPLIERS.get(level, 1.0)
            new_risk = min(1.0, node.risk_index * multiplier + 0.1 * (multiplier - 1.0))
            self.gm.update_node_risk(nid, new_risk)

    # ------------------------------------------------------------------ #
    #  Analysis helpers                                                    #
    # ------------------------------------------------------------------ #

    def crime_heatmap(self) -> Dict[int, float]:
        """
        Returns {node_id: 0.0–1.0} mapping for heatmap overlay.
        High=1.0, Medium=0.5, Low=0.0.
        """
        level_to_val = {"High": 1.0, "Medium": 0.5, "Low": 0.0}
        return {nid: level_to_val.get(lvl, 0.0)
                for nid, lvl in self.predictions.items()}

    def feature_importance_dict(self) -> Dict[str, float]:
        """Returns a labelled feature importance dict for the UI chart."""
        return dict(zip(self.feature_names, self.importances))

    def cluster_centers(self) -> Optional[np.ndarray]:
        """Return K-Means cluster centres (2D, population × ind_proximity)."""
        return self.kmeans.cluster_centers_ if self.kmeans else None
