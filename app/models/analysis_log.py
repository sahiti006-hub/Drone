import enum
import json
from datetime import datetime, timezone
from app.extensions import db


class EvaluationStatus(str, enum.Enum):
    """Evaluation status comparing predicted route performance against simulated reality."""
    OPTIMAL = "OPTIMAL"
    SUB_OPTIMAL = "SUB_OPTIMAL"
    FEASIBLE = "FEASIBLE"
    FAILED = "FAILED"
    PENDING = "PENDING"


class AnalysisLog(db.Model):
    """Audit log capturing algorithm predictions vs. simulated physical execution."""
    __tablename__ = "analysis_logs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    simulation_run_id = db.Column(
        db.Integer,
        db.ForeignKey("simulation_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    algorithm_name = db.Column(db.String(50), nullable=False, index=True)
    scenario_reference = db.Column(db.String(100), nullable=False, index=True)
    predicted_metrics_json = db.Column(db.Text, nullable=False)
    actual_simulated_metrics_json = db.Column(db.Text, nullable=True)
    evaluation_status = db.Column(
        db.String(30),
        nullable=False,
        default=EvaluationStatus.PENDING.value,
        index=True,
    )
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    simulation_run = db.relationship("SimulationRun", back_populates="analysis_logs")

    def __init__(
        self,
        algorithm_name: str,
        scenario_reference: str,
        predicted_metrics: dict | str,
        actual_simulated_metrics: dict | str = None,
        evaluation_status: str = EvaluationStatus.PENDING.value,
        simulation_run_id: int = None,
        notes: str = None,
    ):
        self.algorithm_name = algorithm_name.strip()
        self.scenario_reference = scenario_reference.strip()
        self.predicted_metrics_json = (
            json.dumps(predicted_metrics) if isinstance(predicted_metrics, dict) else str(predicted_metrics)
        )
        self.actual_simulated_metrics_json = (
            json.dumps(actual_simulated_metrics)
            if isinstance(actual_simulated_metrics, dict)
            else (str(actual_simulated_metrics) if actual_simulated_metrics is not None else None)
        )
        self.evaluation_status = (
            evaluation_status.value
            if isinstance(evaluation_status, EvaluationStatus)
            else str(evaluation_status).upper()
        )
        self.simulation_run_id = simulation_run_id
        self.notes = notes

    def get_predicted_metrics(self) -> dict:
        """Parse predicted metrics JSON."""
        return json.loads(self.predicted_metrics_json) if self.predicted_metrics_json else {}

    def get_actual_metrics(self) -> dict:
        """Parse actual simulated metrics JSON."""
        return json.loads(self.actual_simulated_metrics_json) if self.actual_simulated_metrics_json else {}

    def to_dict(self) -> dict:
        """Serialize analysis log to dictionary."""
        return {
            "id": self.id,
            "simulation_run_id": self.simulation_run_id,
            "algorithm_name": self.algorithm_name,
            "scenario_reference": self.scenario_reference,
            "predicted_metrics": self.get_predicted_metrics(),
            "actual_simulated_metrics": self.get_actual_metrics(),
            "evaluation_status": self.evaluation_status,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<AnalysisLog id={self.id} algo={self.algorithm_name} scenario={self.scenario_reference} eval={self.evaluation_status}>"
