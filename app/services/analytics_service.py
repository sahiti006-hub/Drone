"""Analytics, metrics aggregation, and performance evaluation service.

Leverages Pandas for statistical analysis, algorithmic benchmarking,
and scenario comparisons while maintaining the database as the authoritative
source for all operational records.
"""

import csv
import io
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from sqlalchemy import func

from app.extensions import db
from app.models.analysis_log import AnalysisLog, EvaluationStatus
from app.models.delivery_request import (
    DeliveryRequest,
    EmergencyType,
    RequestPriority,
    RequestStatus,
)
from app.models.drone import Drone, DroneStatus
from app.models.drone_assignment import AssignmentStatus, DroneAssignment
from app.models.route import FeasibilityStatus, Route
from app.models.route_waypoint import RouteWaypoint
from app.models.simulation_run import SimulationRun, SimulationStatus
from app.models.user import User, UserRole


class AnalyticsService:
    """Provides role-aware operational statistics, delivery tracking, and algorithmic benchmarking."""

    @classmethod
    def get_dashboard_metrics(cls, user: User) -> Dict[str, Any]:
        """Calculates system-wide or role-scoped operational metrics.

        Rule Definitions:
        - Total Delivery Requests: Count of requests (scoped to user.id if REQUESTER).
        - Pending Requests: Requests in PENDING or ROUTE_CALCULATED status.
        - Assigned Deliveries: Requests in ASSIGNED or with an ACTIVE assignment.
        - Active Simulations: Simulations in RUNNING or PAUSED status.
        - Completed Deliveries: Requests in DELIVERED status.
        - Cancelled or Failed Deliveries: Requests in CANCELLED/REJECTED or assignments ABORTED/FAILED.
        - Available Drones: Active, non-decommissioned drones in AVAILABLE status.
        - Drones In Transit: Drones currently in IN_TRANSIT status.
        - Drones In Maintenance: Drones currently in MAINTENANCE status.
        - Infeasible Route Attempts: Routes flagged with INFEASIBLE status.
        - Fleet Utilization Rate: (Drones in transit / Total active drones) * 100.
        - Mission Success Rate: (Completed deliveries / Total completed+failed) * 100.
        """
        is_requester = (user.role == UserRole.REQUESTER.value)

        # Base delivery request query
        req_query = DeliveryRequest.query
        if is_requester:
            req_query = req_query.filter_by(requester_id=user.id)

        total_requests = req_query.count()

        pending_requests = req_query.filter(
            DeliveryRequest.status.in_([
                RequestStatus.PENDING.value,
                RequestStatus.ROUTE_CALCULATED.value,
            ])
        ).count()

        assigned_deliveries = req_query.filter_by(
            status=RequestStatus.ASSIGNED.value
        ).count()

        completed_deliveries = req_query.filter_by(
            status=RequestStatus.DELIVERED.value
        ).count()

        cancelled_or_failed = req_query.filter(
            DeliveryRequest.status.in_([
                RequestStatus.CANCELLED.value,
                RequestStatus.REJECTED.value,
            ])
        ).count()

        # Active simulations query
        sim_query = SimulationRun.query.filter(
            SimulationRun.status.in_([
                SimulationStatus.RUNNING.value,
                SimulationStatus.PAUSED.value,
            ])
        )
        if is_requester:
            sim_query = sim_query.join(DroneAssignment).join(DeliveryRequest).filter(
                DeliveryRequest.requester_id == user.id
            )
        active_simulations = sim_query.count()

        # Drones metrics (System-wide asset oversight for Admin/Operator, context for Requester)
        total_active_drones = Drone.query.filter_by(is_decommissioned=False).count()
        available_drones = Drone.query.filter_by(
            status=DroneStatus.AVAILABLE.value,
            is_decommissioned=False,
        ).count()
        in_transit_drones = Drone.query.filter_by(
            status=DroneStatus.IN_TRANSIT.value,
            is_decommissioned=False,
        ).count()
        maintenance_drones = Drone.query.filter_by(
            status=DroneStatus.MAINTENANCE.value,
            is_decommissioned=False,
        ).count()
        charging_drones = Drone.query.filter_by(
            status=DroneStatus.CHARGING.value,
            is_decommissioned=False,
        ).count()

        # Route feasibility count
        route_query = Route.query
        if is_requester:
            route_query = route_query.join(DeliveryRequest).filter(
                DeliveryRequest.requester_id == user.id
            )
        infeasible_routes_count = route_query.filter(
            Route.feasibility_status == FeasibilityStatus.INFEASIBLE.value
        ).count()
        feasible_routes_count = route_query.filter(
            Route.feasibility_status == FeasibilityStatus.FEASIBLE.value
        ).count()

        # Safe percentage calculations (Preventing division by zero)
        fleet_utilization_pct = (
            round((in_transit_drones / total_active_drones) * 100.0, 1)
            if total_active_drones > 0
            else 0.0
        )

        closed_missions = completed_deliveries + cancelled_or_failed
        delivery_success_pct = (
            round((completed_deliveries / closed_missions) * 100.0, 1)
            if closed_missions > 0
            else 0.0
        )

        return {
            "total_requests": total_requests,
            "pending_requests": pending_requests,
            "assigned_deliveries": assigned_deliveries,
            "active_simulations": active_simulations,
            "completed_deliveries": completed_deliveries,
            "cancelled_or_failed_deliveries": cancelled_or_failed,
            "available_drones": available_drones,
            "in_transit_drones": in_transit_drones,
            "maintenance_drones": maintenance_drones,
            "charging_drones": charging_drones,
            "total_active_drones": total_active_drones,
            "infeasible_routes_count": infeasible_routes_count,
            "feasible_routes_count": feasible_routes_count,
            "fleet_utilization_pct": fleet_utilization_pct,
            "delivery_success_pct": delivery_success_pct,
        }

    @classmethod
    def get_delivery_monitoring_data(
        cls,
        user: User,
        status_filter: Optional[str] = None,
        priority_filter: Optional[str] = None,
        emergency_type_filter: Optional[str] = None,
        search_query: Optional[str] = None,
        sort_by: str = "created_desc",
    ) -> List[Dict[str, Any]]:
        """Returns delivery records with live assignment, drone, route, and simulation status.

        Enforces strict role-based scoping: Requesters see only their own requests.
        """
        query = DeliveryRequest.query

        if user.role == UserRole.REQUESTER.value:
            query = query.filter(DeliveryRequest.requester_id == user.id)

        # Filters
        if status_filter and status_filter.upper() != "ALL":
            query = query.filter(DeliveryRequest.status == status_filter.strip().upper())

        if priority_filter and priority_filter.upper() != "ALL":
            query = query.filter(DeliveryRequest.priority == priority_filter.strip().upper())

        if emergency_type_filter and emergency_type_filter.upper() != "ALL":
            query = query.filter(DeliveryRequest.emergency_type == emergency_type_filter.strip().upper())

        if search_query:
            term = f"%{search_query.strip()}%"
            query = query.filter(
                (DeliveryRequest.emergency_type.ilike(term))
                | (DeliveryRequest.description.ilike(term))
                | (db.cast(DeliveryRequest.id, db.String).like(term.replace("#", "")))
            )

        # Sorting
        if sort_by == "created_asc":
            query = query.order_by(DeliveryRequest.created_at.asc())
        elif sort_by == "priority_desc":
            # Priority triage ordering: CRITICAL > HIGH > MEDIUM > LOW
            query = query.order_by(
                db.case(
                    (DeliveryRequest.priority == RequestPriority.CRITICAL.value, 1),
                    (DeliveryRequest.priority == RequestPriority.HIGH.value, 2),
                    (DeliveryRequest.priority == RequestPriority.MEDIUM.value, 3),
                    (DeliveryRequest.priority == RequestPriority.LOW.value, 4),
                    else_=5,
                ),
                DeliveryRequest.created_at.desc(),
            )
        elif sort_by == "payload_desc":
            query = query.order_by(DeliveryRequest.payload_weight_kg.desc())
        else:
            query = query.order_by(DeliveryRequest.created_at.desc())

        requests_list = query.all()
        results = []

        for req in requests_list:
            # Most recent assignment
            latest_assignment = (
                DroneAssignment.query
                .filter_by(delivery_request_id=req.id)
                .order_by(DroneAssignment.id.desc())
                .first()
            )

            # Selected or best feasible route
            selected_route = (
                Route.query
                .filter_by(delivery_request_id=req.id, feasibility_status=FeasibilityStatus.FEASIBLE.value)
                .order_by(Route.route_score.asc().nullslast())
                .first()
            )

            # Active simulation run
            active_sim = None
            if latest_assignment:
                active_sim = (
                    SimulationRun.query
                    .filter_by(assignment_id=latest_assignment.id)
                    .order_by(SimulationRun.id.desc())
                    .first()
                )

            record = {
                "id": req.id,
                "requester_id": req.requester_id,
                "requester_name": req.requester.full_name if req.requester else "Unknown",
                "emergency_type": req.emergency_type,
                "priority": req.priority,
                "status": req.status,
                "payload_weight_kg": float(req.payload_weight_kg),
                "created_at": req.created_at.strftime("%Y-%m-%d %H:%M UTC") if req.created_at else "-",
                "description": req.description or "No description provided",
                "assignment_id": latest_assignment.id if latest_assignment else None,
                "assignment_status": latest_assignment.status if latest_assignment else "UNASSIGNED",
                "drone_code": latest_assignment.drone.drone_code if latest_assignment and latest_assignment.drone else None,
                "drone_model": latest_assignment.drone.model_name if latest_assignment and latest_assignment.drone else None,
                "estimated_distance_km": float(selected_route.estimated_distance_km) if selected_route else None,
                "estimated_duration_min": float(selected_route.estimated_duration_minutes) if selected_route else None,
                "estimated_energy_wh": float(selected_route.estimated_energy_wh) if selected_route else None,
                "simulation_id": active_sim.id if active_sim else None,
                "simulation_status": active_sim.status if active_sim else None,
                "progress_percent": active_sim.current_progress_percent if active_sim else 0.0,
            }
            results.append(record)

        return results

    @classmethod
    def get_route_analytics_comparison(cls) -> Dict[str, Any]:
        """Compares baseline shortest-feasible corridors vs. weighted-objective optimizer.

        Uses Pandas DataFrames to compute statistical aggregations, energy variances,
        and feasibility distributions across identical delivery scenarios.
        """
        routes = Route.query.all()
        if not routes:
            return cls._empty_route_analytics()

        # Build Pandas DataFrame from persisted Route entities
        data = []
        for r in routes:
            algo_raw = r.algorithm_name
            # Parse algorithm type: baseline vs multi-objective
            if "DIRECT" in algo_raw.upper() or "BASELINE" in algo_raw.upper():
                method_group = "BASELINE_SHORTEST"
            else:
                method_group = "WEIGHTED_OPTIMIZER"

            data.append({
                "route_id": r.id,
                "delivery_request_id": r.delivery_request_id,
                "algorithm_name": r.algorithm_name,
                "method_group": method_group,
                "distance_km": float(r.estimated_distance_km),
                "duration_minutes": float(r.estimated_duration_minutes),
                "energy_wh": float(r.estimated_energy_wh),
                "route_score": float(r.route_score) if r.route_score is not None else None,
                "feasibility_status": r.feasibility_status,
                "is_feasible": 1 if r.feasibility_status == FeasibilityStatus.FEASIBLE.value else 0,
                "rejection_reason": r.rejection_reason or "None",
            })

        df = pd.DataFrame(data)

        # Group comparisons: Baseline Shortest vs. Weighted Optimizer
        baseline_df = df[df["method_group"] == "BASELINE_SHORTEST"]
        optimizer_df = df[df["method_group"] == "WEIGHTED_OPTIMIZER"]

        baseline_feasible = baseline_df[baseline_df["is_feasible"] == 1]
        optimizer_feasible = optimizer_df[optimizer_df["is_feasible"] == 1]

        def get_stats(subset: pd.DataFrame) -> Dict[str, float]:
            if subset.empty:
                return {
                    "avg_distance_km": 0.0,
                    "avg_duration_min": 0.0,
                    "avg_energy_wh": 0.0,
                    "min_energy_wh": 0.0,
                    "max_energy_wh": 0.0,
                    "total_routes": 0,
                    "feasible_count": 0,
                    "feasibility_rate_pct": 0.0,
                }
            return {
                "avg_distance_km": round(float(subset["distance_km"].mean()), 2),
                "avg_duration_min": round(float(subset["duration_minutes"].mean()), 2),
                "avg_energy_wh": round(float(subset["energy_wh"].mean()), 2),
                "min_energy_wh": round(float(subset["energy_wh"].min()), 2),
                "max_energy_wh": round(float(subset["energy_wh"].max()), 2),
                "total_routes": int(len(subset)),
                "feasible_count": int(subset["is_feasible"].sum()),
                "feasibility_rate_pct": round(float(subset["is_feasible"].mean() * 100.0), 1),
            }

        baseline_stats = get_stats(baseline_df)
        optimizer_stats = get_stats(optimizer_df)

        # Rejection reasons breakdown using Pandas value_counts
        infeasible_df = df[df["is_feasible"] == 0]
        reasons_dist = {}
        if not infeasible_df.empty:
            for raw_reason in infeasible_df["rejection_reason"]:
                # Split multiple semicolon-separated reasons
                for sub_reason in str(raw_reason).split(";"):
                    cleaned = sub_reason.strip()
                    if cleaned and cleaned != "None":
                        # Categorize category label
                        if "payload" in cleaned.lower():
                            cat = "Payload Limit Exceeded"
                        elif "battery" in cleaned.lower() or "reserve" in cleaned.lower():
                            cat = "Battery Reserve Margin Breached"
                        elif "wind" in cleaned.lower():
                            cat = "Wind Speed Limit Exceeded"
                        elif "visibility" in cleaned.lower():
                            cat = "Low Visibility Hazard"
                        elif "precipitation" in cleaned.lower():
                            cat = "Excessive Precipitation Hazard"
                        elif "weather" in cleaned.lower():
                            cat = "Missing Weather Observation Data"
                        else:
                            cat = cleaned[:40]
                        reasons_dist[cat] = reasons_dist.get(cat, 0) + 1

        # Delivery status distribution
        req_df = pd.DataFrame([
            {"status": r.status} for r in DeliveryRequest.query.all()
        ])
        status_dist = {}
        if not req_df.empty:
            status_dist = req_df["status"].value_counts().to_dict()

        # Drone utilization distribution
        drone_df = pd.DataFrame([
            {"status": d.status} for d in Drone.query.filter_by(is_decommissioned=False).all()
        ])
        drone_dist = {}
        if not drone_df.empty:
            drone_dist = drone_df["status"].value_counts().to_dict()

        # AnalysisLog predicted vs actual simulated outcomes comparison
        logs = AnalysisLog.query.all()
        audit_records = []
        for l in logs:
            pred = l.get_predicted_metrics()
            act = l.get_actual_metrics()
            audit_records.append({
                "algorithm": l.algorithm_name,
                "scenario": l.scenario_reference,
                "pred_distance_km": float(pred.get("distance_km", 0.0)),
                "actual_distance_km": float(act.get("distance_km", 0.0)),
                "pred_energy_wh": float(pred.get("energy_wh", 0.0)),
                "actual_energy_wh": float(act.get("energy_wh", 0.0)),
                "pred_duration_min": float(pred.get("duration_min", 0.0)),
                "actual_duration_min": float(act.get("duration_min", 0.0)),
                "evaluation_status": l.evaluation_status,
            })

        audit_df = pd.DataFrame(audit_records)
        accuracy_metrics = {
            "total_audited_missions": len(audit_df),
            "energy_mean_error_wh": 0.0,
            "duration_mean_error_min": 0.0,
        }
        if not audit_df.empty and len(audit_df) > 0:
            if "actual_energy_wh" in audit_df and "pred_energy_wh" in audit_df:
                audit_df["energy_error"] = (audit_df["actual_energy_wh"] - audit_df["pred_energy_wh"]).abs()
                accuracy_metrics["energy_mean_error_wh"] = round(float(audit_df["energy_error"].mean()), 2)
            if "actual_duration_min" in audit_df and "pred_duration_min" in audit_df:
                audit_df["duration_error"] = (audit_df["actual_duration_min"] - audit_df["pred_duration_min"]).abs()
                accuracy_metrics["duration_mean_error_min"] = round(float(audit_df["duration_error"].mean()), 2)

        return {
            "baseline": baseline_stats,
            "optimizer": optimizer_stats,
            "reasons_distribution": reasons_dist,
            "status_distribution": status_dist,
            "drone_distribution": drone_dist,
            "accuracy_metrics": accuracy_metrics,
            "total_scenarios_evaluated": int(df["delivery_request_id"].nunique()),
        }

    @classmethod
    def _empty_route_analytics(cls) -> Dict[str, Any]:
        """Provides a safe empty-state structure when no routes are in the database."""
        empty_stats = {
            "avg_distance_km": 0.0,
            "avg_duration_min": 0.0,
            "avg_energy_wh": 0.0,
            "min_energy_wh": 0.0,
            "max_energy_wh": 0.0,
            "total_routes": 0,
            "feasible_count": 0,
            "feasibility_rate_pct": 0.0,
        }
        return {
            "baseline": empty_stats,
            "optimizer": empty_stats,
            "reasons_distribution": {},
            "status_distribution": {},
            "drone_distribution": {},
            "accuracy_metrics": {
                "total_audited_missions": 0,
                "energy_mean_error_wh": 0.0,
                "duration_mean_error_min": 0.0,
            },
            "total_scenarios_evaluated": 0,
        }

    @classmethod
    def export_deliveries_csv(cls, user: User, filters: Optional[Dict[str, Any]] = None) -> str:
        """Generates a sanitized CSV export string for authorized users.

        Sanitizes cell contents against spreadsheet formula injection (=, +, -, @).
        """
        if filters is None:
            filters = {}

        records = cls.get_delivery_monitoring_data(
            user=user,
            status_filter=filters.get("status"),
            priority_filter=filters.get("priority"),
            emergency_type_filter=filters.get("emergency_type"),
            search_query=filters.get("search"),
            sort_by=filters.get("sort_by", "created_desc"),
        )

        output = io.StringIO()
        fieldnames = [
            "Request ID",
            "Requester",
            "Emergency Type",
            "Priority",
            "Lifecycle Status",
            "Payload (kg)",
            "Creation Timestamp",
            "Assigned Drone Code",
            "Drone Hardware Model",
            "Assignment Status",
            "Est. Distance (km)",
            "Est. Duration (min)",
            "Est. Energy (Wh)",
            "Simulation Status",
            "Sim. Progress (%)",
        ]

        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()

        def sanitize(val: Any) -> str:
            s = str(val or "")
            if s.startswith(("=", "+", "-", "@")):
                return "'" + s
            return s

        for r in records:
            writer.writerow({
                "Request ID": sanitize(f"#{r['id']}"),
                "Requester": sanitize(r["requester_name"]),
                "Emergency Type": sanitize(r["emergency_type"]),
                "Priority": sanitize(r["priority"]),
                "Lifecycle Status": sanitize(r["status"]),
                "Payload (kg)": f"{r['payload_weight_kg']:.2f}",
                "Creation Timestamp": sanitize(r["created_at"]),
                "Assigned Drone Code": sanitize(r["drone_code"] or "UNASSIGNED"),
                "Drone Hardware Model": sanitize(r["drone_model"] or "N/A"),
                "Assignment Status": sanitize(r["assignment_status"]),
                "Est. Distance (km)": f"{r['estimated_distance_km']:.2f}" if r["estimated_distance_km"] is not None else "-",
                "Est. Duration (min)": f"{r['estimated_duration_min']:.1f}" if r["estimated_duration_min"] is not None else "-",
                "Est. Energy (Wh)": f"{r['estimated_energy_wh']:.1f}" if r["estimated_energy_wh"] is not None else "-",
                "Simulation Status": sanitize(r["simulation_status"] or "NOT_STARTED"),
                "Sim. Progress (%)": f"{r['progress_percent']:.1f}%",
            })

        return output.getvalue()
