import enum
import json
from datetime import datetime, timezone
from app.extensions import db


class SimulationStatus(str, enum.Enum):
    """Execution status of a simulation batch run."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class SimulationRun(db.Model):
    """Tracks a discrete-event simulation scenario run and its aggregate metrics."""
    __tablename__ = "simulation_runs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_code = db.Column(db.String(50), unique=True, index=True, nullable=False)
    parameters_json = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=SimulationStatus.PENDING.value,
        index=True,
    )
    start_time = db.Column(db.DateTime(timezone=True), nullable=True)
    end_time = db.Column(db.DateTime(timezone=True), nullable=True)
    summary_metrics_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    analysis_logs = db.relationship(
        "AnalysisLog",
        back_populates="simulation_run",
        lazy="dynamic",
    )

    def __init__(
        self,
        run_code: str,
        parameters: dict | str,
        status: str = SimulationStatus.PENDING.value,
    ):
        self.run_code = run_code.strip().upper()
        self.parameters_json = json.dumps(parameters) if isinstance(parameters, dict) else str(parameters)
        self.status = status.value if isinstance(status, SimulationStatus) else str(status).upper()

    def get_parameters(self) -> dict:
        """Parse parameters JSON."""
        return json.loads(self.parameters_json) if self.parameters_json else {}

    def get_summary_metrics(self) -> dict:
        """Parse summary metrics JSON."""
        return json.loads(self.summary_metrics_json) if self.summary_metrics_json else {}

    def start(self) -> None:
        """Mark simulation run as started."""
        self.status = SimulationStatus.RUNNING.value
        self.start_time = datetime.now(timezone.utc)

    def complete(self, summary_metrics: dict) -> None:
        """Mark simulation run as completed with summary results."""
        self.status = SimulationStatus.COMPLETED.value
        self.end_time = datetime.now(timezone.utc)
        self.summary_metrics_json = json.dumps(summary_metrics)

    def fail(self, error_details: dict) -> None:
        """Mark simulation run as failed."""
        self.status = SimulationStatus.FAILED.value
        self.end_time = datetime.now(timezone.utc)
        self.summary_metrics_json = json.dumps(error_details)

    def to_dict(self) -> dict:
        """Serialize simulation run to dictionary."""
        return {
            "id": self.id,
            "run_code": self.run_code,
            "status": self.status,
            "parameters": self.get_parameters(),
            "summary_metrics": self.get_summary_metrics(),
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<SimulationRun code={self.run_code} status={self.status}>"
