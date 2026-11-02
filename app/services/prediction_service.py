"""Machine Learning Flight Duration & Energy Consumption Prediction Module (Enhancement 3).

Trains and evaluates regression models to predict simulated flight duration
and energy consumption compared to analytical baseline physics formulas.

Key Architectural Guarantees:
1. Strict 80/20 Train/Test split with random seed to guarantee zero data leakage.
2. Reports comprehensive error metrics: MAE, RMSE, R-squared, and MAPE.
3. Explicit Safety Boundary: ML predictions are labeled advisory only and NEVER
   substitute or bypass deterministic hard safety feasibility checks.
"""

from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Any
import numpy as np


@dataclass(frozen=True)
class PredictionMetrics:
    """Evaluation error metrics for comparing ML predictions against ground truth and baseline."""
    mae: float
    rmse: float
    r2_score: float
    mape_percent: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "mae": round(self.mae, 4),
            "rmse": round(self.rmse, 4),
            "r2_score": round(self.r2_score, 4),
            "mape_percent": round(self.mape_percent, 2),
        }


@dataclass
class FlightPredictionResult:
    """Advisory prediction output comparing ML inference with baseline analytical formula."""
    predicted_duration_minutes: float
    predicted_energy_wh: float
    baseline_duration_minutes: float
    baseline_energy_wh: float
    duration_difference_minutes: float
    energy_difference_wh: float
    model_version: str
    features_used: Dict[str, float]
    safety_disclaimer: str = (
        "ADVISORY NOTICE: Machine learning predictions are for operational estimation only. "
        "Deterministic physical safety and battery feasibility constraints strictly govern dispatch."
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "predicted_duration_minutes": round(self.predicted_duration_minutes, 2),
            "predicted_energy_wh": round(self.predicted_energy_wh, 2),
            "baseline_duration_minutes": round(self.baseline_duration_minutes, 2),
            "baseline_energy_wh": round(self.baseline_energy_wh, 2),
            "duration_difference_minutes": round(self.duration_difference_minutes, 2),
            "energy_difference_wh": round(self.energy_difference_wh, 2),
            "model_version": self.model_version,
            "features_used": self.features_used,
            "safety_disclaimer": self.safety_disclaimer,
        }


class RidgeRegressor:
    """Closed-form Ridge (L2-regularized Ordinary Least Squares) Regression model using NumPy.

    Normal equation:
        theta = (X^T X + lambda * I)^(-1) X^T y
    """

    def __init__(self, alpha: float = 1.0):
        self.alpha = float(alpha)
        self.weights: np.ndarray | None = None
        self.bias: float = 0.0
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> RidgeRegressor:
        """Fit ridge regression model to standardized feature matrix."""
        X_arr = np.asarray(X, dtype=np.float64)
        y_arr = np.asarray(y, dtype=np.float64)

        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(-1, 1)

        n_samples, n_features = X_arr.shape
        if n_samples == 0:
            raise ValueError("Cannot train model on empty training set.")

        # Standardize features (zero mean, unit variance) to avoid scaling bias
        self.mean_ = np.mean(X_arr, axis=0)
        self.std_ = np.std(X_arr, axis=0)
        self.std_[self.std_ == 0] = 1.0  # Prevent division by zero for constant features

        X_norm = (X_arr - self.mean_) / self.std_

        # Add bias column
        X_b = np.column_stack([np.ones((n_samples, 1)), X_norm])

        # Regularization matrix (do not regularize bias)
        reg = self.alpha * np.eye(n_features + 1)
        reg[0, 0] = 0.0

        # Solve normal equations: (X^T X + reg)^(-1) X^T y
        A = X_b.T @ X_b + reg
        b = X_b.T @ y_arr
        theta = np.linalg.solve(A, b)

        self.bias = float(theta[0])
        self.weights = theta[1:]
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Generate predictions for feature matrix X."""
        if self.weights is None or self.mean_ is None or self.std_ is None:
            raise RuntimeError("Model must be fitted before predict() is called.")

        X_arr = np.asarray(X, dtype=np.float64)
        if X_arr.ndim == 1:
            X_arr = X_arr.reshape(-1, 1)

        X_norm = (X_arr - self.mean_) / self.std_
        return np.asarray(X_norm @ self.weights + self.bias, dtype=np.float64)


def compute_regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> PredictionMetrics:
    """Calculate MAE, RMSE, R2, and MAPE error metrics."""
    y_true_arr = np.asarray(y_true, dtype=np.float64)
    y_pred_arr = np.asarray(y_pred, dtype=np.float64)

    errors = y_true_arr - y_pred_arr
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors ** 2)))

    ss_res = float(np.sum(errors ** 2))
    ss_tot = float(np.sum((y_true_arr - np.mean(y_true_arr)) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 1.0

    # Avoid zero division in MAPE
    denom = np.where(np.abs(y_true_arr) < 1e-4, 1.0, np.abs(y_true_arr))
    mape = float(np.mean(np.abs(errors / denom)) * 100.0)

    return PredictionMetrics(mae=mae, rmse=rmse, r2_score=r2, mape_percent=mape)


class FlightPredictionService:
    """Service for training, evaluating, and serving flight duration and energy ML models."""

    MODEL_VERSION = "Ridge-OLS-Poly-v1.0"
    FEATURE_NAMES = [
        "distance_km",
        "payload_weight_kg",
        "wind_speed_mps",
        "cruise_speed_kmh",
        "payload_distance_interaction",
        "wind_squared_drag",
    ]

    _duration_model: RidgeRegressor | None = None
    _energy_model: RidgeRegressor | None = None
    _evaluation_report: Dict[str, Any] | None = None

    @classmethod
    def extract_features(
        cls,
        distance_km: float,
        payload_weight_kg: float,
        wind_speed_mps: float,
        cruise_speed_kmh: float,
    ) -> np.ndarray:
        """Construct feature vector with non-linear polynomial and interaction terms."""
        d = float(distance_km)
        w = float(payload_weight_kg)
        v = float(wind_speed_mps)
        s = float(cruise_speed_kmh)

        interaction = d * w
        drag_term = v ** 2

        return np.array([d, w, v, s, interaction, drag_term], dtype=np.float64)

    @classmethod
    def generate_synthetic_dataset(
        cls,
        n_samples: int = 400,
        random_seed: int = 42,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Generate synthetic dataset of simulated drone missions.

        Features: [distance_km, payload_weight_kg, wind_speed_mps, cruise_speed_kmh]
        Targets:
            - y_duration_min: true simulated flight duration including wind drag and climb/descent
            - y_energy_wh: true simulated energy including aerodynamic drag, payload induced power, and battery internal resistance
        """
        rng = np.random.RandomState(random_seed)

        # Realistic flight parameters
        distances = rng.uniform(1.0, 25.0, size=n_samples)          # 1 to 25 km
        payloads = rng.uniform(0.1, 5.0, size=n_samples)             # 0.1 to 5.0 kg
        wind_speeds = rng.uniform(0.0, 10.0, size=n_samples)         # 0 to 10 m/s
        cruise_speeds = rng.choice([45.0, 50.0, 60.0, 70.0], size=n_samples)  # km/h

        X_raw = np.column_stack([distances, payloads, wind_speeds, cruise_speeds])

        # True simulation physics with non-linear air resistance & climb acceleration
        # Nominal duration: (distance / speed) * 60 + climb/maneuver latency + wind impediment
        durations = (
            (distances / cruise_speeds) * 60.0
            + (distances * (wind_speeds / 50.0))  # Headwind/crosswind penalty
            + 1.2  # takeoff, ascent, descent, and landing maneuver fixed time
            + rng.normal(0, 0.15, size=n_samples)  # Micro-turbulence jitter
        )

        # Nominal energy: base avionics + induced hover power (payload) + parasite drag (wind^2)
        base_power_w = 120.0
        induced_power_per_kg = 35.0
        parasite_power = 2.5 * (wind_speeds ** 1.8)
        flight_hours = durations / 60.0
        total_power_w = base_power_w + (payloads * induced_power_per_kg) + parasite_power
        energies = (total_power_w * flight_hours) + rng.normal(0, 1.0, size=n_samples)

        # Build feature matrix with interaction terms
        X_features = np.zeros((n_samples, len(cls.FEATURE_NAMES)), dtype=np.float64)
        for i in range(n_samples):
            X_features[i] = cls.extract_features(
                distance_km=distances[i],
                payload_weight_kg=payloads[i],
                wind_speed_mps=wind_speeds[i],
                cruise_speed_kmh=cruise_speeds[i],
            )

        return X_features, durations, energies

    @classmethod
    def train_and_evaluate(
        cls,
        test_ratio: float = 0.20,
        random_seed: int = 42,
        n_samples: int = 400,
    ) -> Dict[str, Any]:
        """Train models with strict 80/20 train/test split and calculate baseline vs ML metrics.

        Guarantees zero data leakage:
        - Shuffling with deterministic random seed.
        - Training and test sets strictly separated before feature standardization and parameter estimation.
        """
        X, y_dur, y_nrg = cls.generate_synthetic_dataset(n_samples=n_samples, random_seed=random_seed)

        n_samples_total = X.shape[0]
        n_test = int(n_samples_total * test_ratio)
        n_train = n_samples_total - n_test

        indices = np.arange(n_samples_total)
        rng = np.random.RandomState(random_seed)
        rng.shuffle(indices)

        train_idx = indices[:n_train]
        test_idx = indices[n_train:]

        X_train, X_test = X[train_idx], X[test_idx]
        y_dur_train, y_dur_test = y_dur[train_idx], y_dur[test_idx]
        y_nrg_train, y_nrg_test = y_nrg[train_idx], y_nrg[test_idx]

        # Fit ML Models
        cls._duration_model = RidgeRegressor(alpha=1.0).fit(X_train, y_dur_train)
        cls._energy_model = RidgeRegressor(alpha=1.0).fit(X_train, y_nrg_train)

        # ML Predictions on unseen test set
        ml_pred_dur = cls._duration_model.predict(X_test)
        ml_pred_nrg = cls._energy_model.predict(X_test)

        # Baseline Analytical Physics Formula Predictions on the same unseen test set
        # Baseline formula:
        # duration = (distance / speed) * 60
        # energy = (150 W + 30 W * payload) * (duration / 60)
        base_pred_dur = np.zeros(n_test, dtype=np.float64)
        base_pred_nrg = np.zeros(n_test, dtype=np.float64)
        for i in range(n_test):
            dist = X_test[i, 0]
            payload = X_test[i, 1]
            speed = X_test[i, 3]
            calc_dur = (dist / speed) * 60.0
            calc_nrg = (150.0 + 30.0 * payload) * (calc_dur / 60.0)
            base_pred_dur[i] = calc_dur
            base_pred_nrg[i] = calc_nrg

        # Calculate metrics
        ml_dur_metrics = compute_regression_metrics(y_dur_test, ml_pred_dur)
        base_dur_metrics = compute_regression_metrics(y_dur_test, base_pred_dur)

        ml_nrg_metrics = compute_regression_metrics(y_nrg_test, ml_pred_nrg)
        base_nrg_metrics = compute_regression_metrics(y_nrg_test, base_pred_nrg)

        cls._evaluation_report = {
            "model_version": cls.MODEL_VERSION,
            "train_samples": n_train,
            "test_samples": n_test,
            "features": cls.FEATURE_NAMES,
            "duration_evaluation": {
                "ml_model": ml_dur_metrics.to_dict(),
                "baseline_formula": base_dur_metrics.to_dict(),
                "mae_improvement_pct": round(
                    ((base_dur_metrics.mae - ml_dur_metrics.mae) / base_dur_metrics.mae) * 100.0, 2
                ) if base_dur_metrics.mae > 0 else 0.0,
            },
            "energy_evaluation": {
                "ml_model": ml_nrg_metrics.to_dict(),
                "baseline_formula": base_nrg_metrics.to_dict(),
                "mae_improvement_pct": round(
                    ((base_nrg_metrics.mae - ml_nrg_metrics.mae) / base_nrg_metrics.mae) * 100.0, 2
                ) if base_nrg_metrics.mae > 0 else 0.0,
            },
        }

        return cls._evaluation_report

    @classmethod
    def get_evaluation_report(cls) -> Dict[str, Any]:
        """Return cached or freshly trained evaluation report."""
        if cls._evaluation_report is None:
            cls.train_and_evaluate()
        return cls._evaluation_report or {}

    @classmethod
    def predict_flight(
        cls,
        distance_km: float,
        payload_weight_kg: float,
        wind_speed_mps: float,
        cruise_speed_kmh: float,
    ) -> FlightPredictionResult:
        """Generate advisory ML predictions alongside physics baseline estimates."""
        if cls._duration_model is None or cls._energy_model is None:
            cls.train_and_evaluate()

        features = cls.extract_features(
            distance_km=distance_km,
            payload_weight_kg=payload_weight_kg,
            wind_speed_mps=wind_speed_mps,
            cruise_speed_kmh=cruise_speed_kmh,
        )

        assert cls._duration_model is not None
        assert cls._energy_model is not None

        ml_dur = float(cls._duration_model.predict(features.reshape(1, -1))[0])
        ml_nrg = float(cls._energy_model.predict(features.reshape(1, -1))[0])

        # Baseline analytical formula
        base_dur = (distance_km / cruise_speed_kmh) * 60.0
        base_nrg = (150.0 + 30.0 * payload_weight_kg) * (base_dur / 60.0)

        # Enforce physical floor (cannot have negative duration or energy)
        ml_dur = max(0.5, ml_dur)
        ml_nrg = max(1.0, ml_nrg)

        return FlightPredictionResult(
            predicted_duration_minutes=ml_dur,
            predicted_energy_wh=ml_nrg,
            baseline_duration_minutes=base_dur,
            baseline_energy_wh=base_nrg,
            duration_difference_minutes=ml_dur - base_dur,
            energy_difference_wh=ml_nrg - base_nrg,
            model_version=cls.MODEL_VERSION,
            features_used={
                "distance_km": round(distance_km, 3),
                "payload_weight_kg": round(payload_weight_kg, 2),
                "wind_speed_mps": round(wind_speed_mps, 2),
                "cruise_speed_kmh": round(cruise_speed_kmh, 1),
            },
        )
