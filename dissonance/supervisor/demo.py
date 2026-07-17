"""Supervisor stub wrapping a no-op pipeline. `python -m dissonance.supervisor.demo`

Proves the supervisor works end-to-end (budgets, stage timing, manifest) before
any real pipeline stage exists.
"""

from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.core import Supervisor


def main() -> None:
    run_config = RunConfig.load("configs/run.yaml")
    supervisor = Supervisor(run_config, pipeline="noop-demo")

    with supervisor.stage("planner"):
        supervisor.spend("planner", 0.0)
        supervisor.note("no-op: planner did nothing")

    with supervisor.stage("scouts"):
        supervisor.increment("papers_touched", 0)
        supervisor.note("no-op: scouts fetched nothing")

    manifest = supervisor.finalize()
    manifest.print_table()


if __name__ == "__main__":
    main()
