import enum
import json
from datetime import datetime, timezone
from app.extensions import db


class SimulationStatus(str, enum.Enum):
    """Execution status of a simulation batch or mission run."""
    CREATED = "CREATED"
    PENDING = "PENDING"      # Maintained for backwards-compatibility
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class SimulationRun(db.Model):
    """Tracks a discrete-event simulation scenario run, kinematics telemetry, and aggregate metrics."""
    __tablename__ = "simulation_runs"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    run_code = db.Column(db.String(50), unique=True, index=True, nullable=False)
    assignment_id = db.Column(
        db.Integer,
        db.ForeignKey("drone_assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    parameters_json = db.Column(db.Text, nullable=False)
    status = db.Column(
        db.String(20),
        nullable=False,
        default=SimulationStatus.PENDING.value,
        index=True,
    )
    start_time = db.Column(db.DateTime(timezone=True), nullable=True)
    end_time = db.Column(db.DateTime(timezone=True), nullable=True)

    # Real-time / Checkpoint telemetry fields
    current_progress_percent = db.Column(db.Float, default=0.0, nullable=False)
    current_latitude = db.Column(db.Numeric(10, 7), nullable=True)
    current_longitude = db.Column(db.Numeric(10, 7), nullable=True)
    current_altitude_m = db.Column(db.Numeric(6, 2), nullable=True)
    elapsed_sim_seconds = db.Column(db.Float, default=0.0, nullable=False)
    total_sim_seconds = db.Column(db.Float, default=0.0, nullable=False)
    distance_covered_km = db.Column(db.Float, default=0.0, nullable=False)
    remaining_distance_km = db.Column(db.Float, default=0.0, nullable=False)
    current_battery_wh = db.Column(db.Float, nullable=True)
    speed_multiplier = db.Column(db.Float, default=1.0, nullable=False)
    checkpoint_json = db.Column(db.Text, nullable=True)

    summary_metrics_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(
        db.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    assignment = db.relationship(
        "DroneAssignment",
        backref=db.backref("simulation_runs", lazy="dynamic", cascade="all, delete-orphan"),
    )
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
        assignment_id: int = None,
        total_sim_seconds: float = 0.0,
        remaining_distance_km: float = 0.0,
        current_battery_wh: float = None,
    ):
        self.run_code = run_code.strip().upper()
        self.parameters_json = json.dumps(parameters) if isinstance(parameters, dict) else str(parameters)
        self.status = status.value if isinstance(status, SimulationStatus) else str(status).upper()
        self.assignment_id = assignment_id
        self.total_sim_seconds = float(total_sim_seconds)
        self.remaining_distance_km = float(remaining_distance_km)
        self.current_battery_wh = current_battery_wh

    def get_parameters(self) -> dict:
        """Parse parameters JSON."""
        return json.loads(self.parameters_json) if self.parameters_json else {}

    def get_summary_metrics(self) -> dict:
        """Parse summary metrics JSON."""
        return json.loads(self.summary_metrics_json) if self.summary_metrics_json else {}

    def get_checkpoint(self) -> dict:
        """Parse checkpoint JSON."""
        return json.loads(self.checkpoint_json) if self.checkpoint_json else {}

    def start(self) -> None:
        """Mark simulation run as started."""
        self.status = SimulationStatus.RUNNING.value
        if not self.start_time:
            self.start_time = datetime.now(timezone.utc)

    def pause(self) -> None:
        """Mark simulation run as paused."""
        self.status = SimulationStatus.PAUSED.value

    def resume(self) -> None:
        """Resume paused simulation run."""
        self.status = SimulationStatus.RUNNING.value

    def complete(self, summary_metrics: dict) -> None:
        """Mark simulation run as completed with summary results."""
        self.status = SimulationStatus.COMPLETED.value
        self.current_progress_percent = 100.0
        self.remaining_distance_km = 0.0
        self.end_time = datetime.now(timezone.utc)
        self.summary_metrics_json = json.dumps(summary_metrics)

    def cancel(self, reason: str = "Operator cancelled") -> None:
        """Mark simulation run as cancelled."""
        self.status = SimulationStatus.CANCELLED.value
        self.end_time = datetime.now(timezone.utc)
        metrics = self.get_summary_metrics()
        metrics["cancellation_reason"] = reason
        self.summary_metrics_json = json.dumps(metrics)

    def fail(self, error_details: dict) -> None:
        """Mark simulation run as failed."""
        self.status = SimulationStatus.FAILED.value
        self.end_time = datetime.now(timezone.utc)
        self.summary_metrics_json = json.dumps(error_details)

    def update_checkpoint(
        self,
        progress_percent: float,
        latitude: float,
        longitude: float,
        altitude_m: float,
        elapsed_seconds: float,
        distance_covered_km: float,
        remaining_distance_km: float,
        current_battery_wh: float,
        speed_multiplier: float = None,
        extra_data: dict = None,
    ) -> None:
        """Persist kinematic checkpoint state."""
        self.current_progress_percent = round(float(progress_percent), 2)
        self.current_latitude = round(float(latitude), 7)
        self.current_longitude = round(float(longitude), 7)
        self.current_altitude_m = round(float(altitude_m), 2)
        self.elapsed_sim_seconds = round(float(elapsed_seconds), 2)
        self.distance_covered_km = round(float(distance_covered_km), 3)
        self.remaining_distance_km = round(float(remaining_distance_km), 3)
        self.current_battery_wh = round(float(current_battery_wh), 2)
        if speed_multiplier is not None:
            self.speed_multiplier = float(speed_multiplier)
        if extra_data:
            self.checkpoint_json = json.dumps(extra_data)

    def to_dict(self) -> dict:
        """Serialize simulation run to dictionary."""
        return {
            "id": self.id,
            "run_code": self.run_code,
            "assignment_id": self.assignment_id,
            "status": self.status,
            "parameters": self.get_parameters(),
            "summary_metrics": self.get_summary_metrics(),
            "checkpoint": self.get_checkpoint(),
            "telemetry": {
                "progress_percent": self.current_progress_percent,
                "latitude": float(self.current_latitude) if self.current_latitude is not None else None,
                "longitude": float(self.current_longitude) if self.current_longitude is not None else None,
                "altitude_m": float(self.current_altitude_m) if self.current_altitude_m is not None else None,
                "elapsed_sim_seconds": self.elapsed_sim_seconds,
                "total_sim_seconds": self.total_sim_seconds,
                "distance_covered_km": self.distance_covered_km,
                "remaining_distance_km": self.remaining_distance_km,
                "current_battery_wh": self.current_battery_wh,
                "speed_multiplier": self.speed_multiplier,
            },
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<SimulationRun code={self.run_code} status={self.status}>"
