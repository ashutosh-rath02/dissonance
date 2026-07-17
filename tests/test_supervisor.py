import pytest

from dissonance.supervisor.budget import BudgetTracker
from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.core import Supervisor
from dissonance.supervisor.exceptions import WallClockExceeded


@pytest.fixture
def run_config():
    return RunConfig.load("configs/run.yaml")


def test_run_config_loads_all_stages(run_config):
    assert run_config.run.budget_usd == 5.00
    assert set(run_config.stages) == {
        "planner", "scouts", "screener", "extraction", "hunter", "adjudicator", "synthesis", "judge",
    }
    assert run_config.stages["extraction"].max_retries == 3


def test_budget_tracker_halts_at_warn_fraction(run_config):
    tracker = BudgetTracker.from_run_config(run_config)
    assert not tracker.halted

    tracker.record("extraction", run_config.run.budget_usd * run_config.run.warn_at_fraction)

    assert tracker.halted
    assert tracker.halt_reason is not None
    assert tracker.stages["extraction"].spent_usd == pytest.approx(
        run_config.run.budget_usd * run_config.run.warn_at_fraction
    )


def test_budget_tracker_does_not_halt_below_threshold(run_config):
    tracker = BudgetTracker.from_run_config(run_config)
    tracker.record("planner", 0.01)
    assert not tracker.halted


def test_supervisor_finalize_writes_manifest(run_config, tmp_path):
    supervisor = Supervisor(run_config, pipeline="test-pipeline")
    with supervisor.stage("planner"):
        supervisor.spend("planner", 0.05)
        supervisor.increment("papers_touched", 3)
        supervisor.increment("papers_new", 2)

    manifest = supervisor.finalize(directory=tmp_path)

    assert manifest.status == "ok"
    assert manifest.papers_touched == 3
    assert manifest.papers_new == 2
    assert manifest.cost_usd == pytest.approx(0.05)
    assert (tmp_path / manifest.run_id / "manifest.json").exists()


def test_supervisor_marks_halted_status(run_config, tmp_path):
    supervisor = Supervisor(run_config, pipeline="test-pipeline")
    supervisor.spend("extraction", run_config.run.budget_usd)  # blow well past warn fraction

    manifest = supervisor.finalize(directory=tmp_path)

    assert manifest.status == "halted"
    assert manifest.halt_reason is not None


def test_supervisor_raises_on_wall_clock_cap(run_config, tmp_path):
    run_config.run.wall_clock_cap_seconds = 0
    supervisor = Supervisor(run_config, pipeline="test-pipeline")

    with pytest.raises(WallClockExceeded):
        with supervisor.stage("planner"):
            pass
