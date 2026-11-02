from datetime import datetime, timezone
from app.extensions import db
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.models.analysis_log import AnalysisLog, EvaluationStatus


def test_simulation_run_lifecycle(app):
    """Test creating, starting, and completing a simulation run."""
    sim = SimulationRun(
        run_code="SIM-TEST-001",
        parameters={"fleet_size": 5, "dispatch_rule": "FIFO"},
    )
    db.session.add(sim)
    db.session.commit()

    assert sim.id is not None
    assert sim.status == SimulationStatus.PENDING.value
    assert sim.get_parameters()["fleet_size"] == 5

    # Start simulation
    sim.start()
    db.session.commit()
    assert sim.status == SimulationStatus.RUNNING.value
    assert sim.start_time is not None

    # Complete simulation
    metrics = {"dispatches": 10, "success_rate_percent": 100.0}
    sim.complete(metrics)
    db.session.commit()
    assert sim.status == SimulationStatus.COMPLETED.value
    assert sim.end_time is not None
    assert sim.get_summary_metrics()["dispatches"] == 10


def test_analysis_logs_recording(app):
    """Test recording predicted vs actual simulated metrics in analysis logs."""
    sim = SimulationRun("SIM-ANALYSIS-01", {"test": True})
    db.session.add(sim)
    db.session.commit()

    log = AnalysisLog(
        simulation_run_id=sim.id,
        algorithm_name="DIJKSTRA_V1",
        scenario_reference="HOSPITAL_URGENT_CORRIDOR",
        predicted_metrics={"distance_km": 10.0, "duration_min": 12.0, "energy_wh": 120.0},
        actual_simulated_metrics={"distance_km": 10.2, "duration_min": 12.5, "energy_wh": 124.0},
        evaluation_status=EvaluationStatus.OPTIMAL,
        notes="High correlation between modeled energy and simulated output.",
    )
    db.session.add(log)
    db.session.commit()

    fetched = db.session.get(AnalysisLog, log.id)
    assert fetched is not None
    assert fetched.algorithm_name == "DIJKSTRA_V1"
    assert fetched.evaluation_status == "OPTIMAL"
    assert fetched.get_predicted_metrics()["distance_km"] == 10.0
    assert fetched.get_actual_metrics()["energy_wh"] == 124.0
    assert fetched.simulation_run.id == sim.id
