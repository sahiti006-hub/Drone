"""Tests for the reproducible route optimizer evaluation framework."""

import os
import pytest
import pandas as pd
from scripts.run_optimizer_experiments import SCENARIOS, run_experiment_suite, export_results
from scripts.analyze_evaluation_results import analyze, FIGURES_DIR, REPORT_PATH


def test_scenario_catalog_integrity():
    """Verify that the benchmark scenarios cover required categories and constraints."""
    assert len(SCENARIOS) >= 12
    scenario_ids = [s.scenario_id for s in SCENARIOS]
    assert len(scenario_ids) == len(set(scenario_ids)), "Duplicate scenario IDs detected!"

    # Verify presence of short, medium, and long categories
    categories = {s.distance_category for s in SCENARIOS}
    assert "SHORT" in categories
    assert "MEDIUM" in categories
    assert "LONG" in categories

    # Verify presence of both feasible and infeasible scenarios
    feasibility_states = {s.expected_feasibility for s in SCENARIOS}
    assert True in feasibility_states
    assert False in feasibility_states


def test_experiment_runner_deterministic_execution(tmp_path):
    """Verify that run_experiment_suite executes cleanly and exports complete CSV."""
    results = run_experiment_suite(SCENARIOS[:4])  # Test first 4 scenarios
    assert len(results) == 4

    csv_path = export_results(results, str(tmp_path))
    assert os.path.exists(csv_path)

    df = pd.read_csv(csv_path)
    assert len(df) == 4

    # Verify key columns exist
    expected_cols = [
        "scenario_id", "is_feasible",
        "baseline_corridor", "baseline_distance_km", "baseline_energy_wh",
        "optimizer_corridor", "optimizer_distance_km", "optimizer_energy_wh",
        "baseline_objective_score", "optimizer_objective_score",
        "baseline_exec_time_ms", "optimizer_exec_time_ms",
    ]
    for col in expected_cols:
        assert col in df.columns

    # Verify candidate count parity
    assert (df["generated_candidates"] == 4).all()


def test_infeasible_scenarios_rejection():
    """Verify that all stress-test scenarios with hazards reject candidate corridors."""
    infeasible_scenarios = [s for s in SCENARIOS if not s.expected_feasibility]
    assert len(infeasible_scenarios) >= 5

    results = run_experiment_suite(infeasible_scenarios)
    for res in results:
        assert res["is_feasible"] is False
        assert res["feasible_candidates"] == 0
        assert res["rejection_reasons"] != ""


def test_analysis_script_generates_artifacts():
    """Verify that analyze() creates SVG figures and markdown report."""
    analyze()
    assert os.path.exists(REPORT_PATH)
    assert os.path.getsize(REPORT_PATH) > 500

    expected_figures = [
        "distance_vs_energy_tradeoff.svg",
        "feasibility_breakdown.svg",
        "algorithm_execution_latency.svg",
        "objective_score_comparison.svg",
    ]
    for fig in expected_figures:
        fig_path = os.path.join(FIGURES_DIR, fig)
        assert os.path.exists(fig_path)
        assert os.path.getsize(fig_path) > 200
