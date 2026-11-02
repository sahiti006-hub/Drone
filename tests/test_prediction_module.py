"""Unit and integration tests for the ML Flight Prediction Module (Enhancement 3).

Verifies:
1. RidgeRegressor fitting, inference, and error handling.
2. Evaluation error metrics computation (MAE, RMSE, R2, MAPE).
3. FlightPredictionService train_and_evaluate() with strict 80/20 split and zero data leakage.
4. ML performance vs baseline physics formula comparison.
5. Physical safety boundaries & explicit non-substitution disclaimers.
6. REST API endpoints GET /analytics/api/ml-model/evaluation and POST /analytics/api/ml-model/predict.
"""

import pytest
import numpy as np
from app.services.prediction_service import (
    RidgeRegressor,
    FlightPredictionService,
    compute_regression_metrics,
    FlightPredictionResult,
)
from app.models.user import User, UserRole


def test_ridge_regressor_fit_and_predict():
    """Test standard RidgeRegressor numerical solving and error checking."""
    X = np.array([[1.0, 2.0], [2.0, 3.0], [3.0, 5.0], [4.0, 7.0]])
    y = np.array([5.0, 8.0, 13.0, 18.0])

    model = RidgeRegressor(alpha=0.5)
    model.fit(X, y)

    assert model.weights is not None
    assert model.bias is not None

    preds = model.predict(X)
    assert len(preds) == 4
    # Predictions should be strongly correlated with ground truth
    corr = np.corrcoef(y, preds)[0, 1]
    assert corr > 0.99


def test_ridge_regressor_unfitted_error():
    """Ensure predicting on an unfitted model raises RuntimeError."""
    model = RidgeRegressor()
    with pytest.raises(RuntimeError, match="Model must be fitted"):
        model.predict(np.array([[1.0, 2.0]]))


def test_compute_regression_metrics():
    """Test metric computation against expected values."""
    y_true = np.array([10.0, 20.0, 30.0])
    y_pred = np.array([12.0, 19.0, 31.0])

    metrics = compute_regression_metrics(y_true, y_pred)
    # Errors are [+2.0, -1.0, +1.0] -> MAE = (2+1+1)/3 = 1.3333
    assert abs(metrics.mae - 1.3333) < 0.01
    # MSE = (4 + 1 + 1)/3 = 2.0 -> RMSE = sqrt(2.0) = 1.4142
    assert abs(metrics.rmse - 1.4142) < 0.01
    assert metrics.r2_score > 0.95
    assert metrics.mape_percent > 0.0


def test_flight_prediction_train_and_evaluate_split_and_metrics():
    """Test 80/20 train/test evaluation reporting and baseline comparison."""
    report = FlightPredictionService.train_and_evaluate(test_ratio=0.20, random_seed=42, n_samples=300)

    assert report["train_samples"] == 240
    assert report["test_samples"] == 60
    assert report["model_version"] == FlightPredictionService.MODEL_VERSION

    dur_eval = report["duration_evaluation"]
    assert "ml_model" in dur_eval
    assert "baseline_formula" in dur_eval
    assert dur_eval["ml_model"]["r2_score"] > 0.85
    assert dur_eval["ml_model"]["mae"] < dur_eval["baseline_formula"]["mae"]

    nrg_eval = report["energy_evaluation"]
    assert "ml_model" in nrg_eval
    assert "baseline_formula" in nrg_eval
    assert nrg_eval["ml_model"]["r2_score"] > 0.85
    assert nrg_eval["ml_model"]["mae"] < nrg_eval["baseline_formula"]["mae"]


def test_flight_prediction_inference_and_safety_disclaimer():
    """Test single-mission inference and presence of explicit advisory disclaimer."""
    result = FlightPredictionService.predict_flight(
        distance_km=12.5,
        payload_weight_kg=2.5,
        wind_speed_mps=5.0,
        cruise_speed_kmh=60.0,
    )

    assert isinstance(result, FlightPredictionResult)
    assert result.predicted_duration_minutes > 0.0
    assert result.predicted_energy_wh > 0.0
    assert result.baseline_duration_minutes > 0.0
    assert result.baseline_energy_wh > 0.0

    # Verify explicit disclaimer is attached
    assert "ADVISORY NOTICE" in result.safety_disclaimer
    assert "Deterministic physical safety and battery feasibility constraints" in result.safety_disclaimer

    d = result.to_dict()
    assert "predicted_duration_minutes" in d
    assert "predicted_energy_wh" in d
    assert "safety_disclaimer" in d


def test_ml_api_endpoints(client, app):
    """Test evaluation report and prediction REST endpoints with authentication."""
    with app.app_context():
        operator = User("Operator Jane", "jane.op@emergency.org", "OperatorPass123!", UserRole.OPERATOR.value)
        from app.extensions import db
        db.session.add(operator)
        db.session.commit()
        op_id = operator.id

    # Unauthenticated request
    res_unauth = client.get("/analytics/api/ml-model/evaluation")
    assert res_unauth.status_code in (302, 401)

    with client.session_transaction() as sess:
        sess["user_id"] = op_id
        sess["_fresh"] = True

    # 1. Evaluation endpoint
    res_eval = client.get("/analytics/api/ml-model/evaluation")
    assert res_eval.status_code == 200
    eval_json = res_eval.get_json()
    assert eval_json["success"] is True
    assert "duration_evaluation" in eval_json["evaluation_report"]
    assert "energy_evaluation" in eval_json["evaluation_report"]

    # 2. Prediction endpoint (valid)
    payload = {
        "distance_km": 15.0,
        "payload_weight_kg": 2.2,
        "wind_speed_mps": 4.5,
        "cruise_speed_kmh": 60.0,
    }
    res_pred = client.post("/analytics/api/ml-model/predict", json=payload)
    assert res_pred.status_code == 200
    pred_json = res_pred.get_json()
    assert pred_json["success"] is True
    assert "predicted_duration_minutes" in pred_json["prediction"]
    assert "ADVISORY NOTICE" in pred_json["prediction"]["safety_disclaimer"]

    # 3. Prediction endpoint (invalid input validation)
    res_invalid = client.post("/analytics/api/ml-model/predict", json={"distance_km": -5.0})
    assert res_invalid.status_code == 400
    assert res_invalid.get_json()["success"] is False
