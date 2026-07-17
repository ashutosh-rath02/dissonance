from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from dissonance.supervisor.budget import BudgetTracker
from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.exceptions import WallClockExceeded
from dissonance.supervisor.manifest import Manifest


class Supervisor:
    """Cross-cutting: budgets, loop caps, kill-switch, manifest, tracing.

    Nothing runs outside the supervisor (plan.md §3.1). A pipeline stage wraps
    its work in `with supervisor.stage("extraction"): ...` and reports spend
    via `supervisor.spend(...)`. The supervisor decides when to halt; it never
    silently keeps going past budget or wall-clock caps.
    """

    def __init__(self, run_config: RunConfig, pipeline: str, run_id: str | None = None):
        self.run_config = run_config
        self.pipeline = pipeline
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.budget = BudgetTracker.from_run_config(run_config)
        self.started_at = datetime.now(timezone.utc)
        self._monotonic_start = time.monotonic()
        self._counts = {"papers_touched": 0, "papers_new": 0, "claims_added": 0, "conflicts_adjudicated": 0}
        self._loops_to_resolution: dict[str, int] = {}
        self._notes: list[str] = []
        self._status: str = "ok"

    def check_wall_clock(self) -> None:
        elapsed = time.monotonic() - self._monotonic_start
        if elapsed > self.run_config.run.wall_clock_cap_seconds:
            raise WallClockExceeded(
                f"wall clock cap {self.run_config.run.wall_clock_cap_seconds}s exceeded ({elapsed:.1f}s elapsed)"
            )

    @contextmanager
    def stage(self, name: str):
        self.check_wall_clock()
        t0 = time.monotonic()
        try:
            yield self
        finally:
            self._notes.append(f"stage '{name}' took {time.monotonic() - t0:.2f}s")

    def spend(self, stage: str, usd: float) -> None:
        self.budget.record(stage, usd)
        if self.budget.halted:
            self._status = "halted"

    def increment(self, key: str, n: int = 1) -> None:
        self._counts[key] = self._counts.get(key, 0) + n

    def record_loops_to_resolution(self, loops: int) -> None:
        bucket = str(loops)
        self._loops_to_resolution[bucket] = self._loops_to_resolution.get(bucket, 0) + 1

    def note(self, text: str) -> None:
        self._notes.append(text)

    def finalize(self, status: str | None = None, directory: Path = Path("runs")) -> Manifest:
        manifest = Manifest(
            run_id=self.run_id,
            pipeline=self.pipeline,
            started_at=self.started_at,
            finished_at=datetime.now(timezone.utc),
            cost_usd=round(self.budget.total_spent_usd, 6),
            stage_costs=self.budget.report(),
            loops_to_resolution=self._loops_to_resolution,
            status=status or self._status,
            halt_reason=self.budget.halt_reason,
            notes=self._notes,
            **self._counts,
        )
        manifest.write(directory)
        return manifest
