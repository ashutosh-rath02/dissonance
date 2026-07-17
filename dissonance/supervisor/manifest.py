from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Manifest(BaseModel):
    """Every run writes one of these. This is the demo (plan.md §4)."""

    run_id: str
    pipeline: str
    started_at: datetime
    finished_at: datetime | None = None
    papers_touched: int = 0
    papers_new: int = 0
    claims_added: int = 0
    conflicts_adjudicated: int = 0
    cost_usd: float = 0.0
    stage_costs: dict[str, dict[str, float]] = Field(default_factory=dict)
    loops_to_resolution: dict[str, int] = Field(default_factory=dict)
    status: Literal["ok", "halted", "failed"] = "ok"
    halt_reason: str | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def wall_clock_seconds(self) -> float:
        if self.finished_at is None:
            return (datetime.now(timezone.utc) - self.started_at).total_seconds()
        return (self.finished_at - self.started_at).total_seconds()

    def write(self, directory: Path = Path("runs")) -> Path:
        run_dir = directory / self.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        out_path = run_dir / "manifest.json"
        out_path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        return out_path

    def print_table(self) -> None:
        # Notes/assertions are copied verbatim from paper text (plan.md's
        # span-verification design), which can contain non-ASCII math symbols
        # etc. Windows consoles default stdout to cp1252, not utf-8; without
        # this, printing one crashes the whole run right after the work is
        # already done and committed.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")

        print(f"\n=== manifest: {self.pipeline} ({self.run_id}) ===")
        print(f"status:              {self.status}" + (f"  ({self.halt_reason})" if self.halt_reason else ""))
        print(f"wall clock:          {self.wall_clock_seconds:.2f}s")
        print(f"papers touched/new:  {self.papers_touched}/{self.papers_new}")
        print(f"claims added:        {self.claims_added}")
        print(f"conflicts adjud.:    {self.conflicts_adjudicated}")
        print(f"cost:                ${self.cost_usd:.4f}")
        if self.stage_costs:
            print("stage costs:")
            for stage, report in self.stage_costs.items():
                print(f"  - {stage:<12} ${report['spent_usd']:.4f} / ${report['budget_usd']:.2f} budget")
        if self.loops_to_resolution:
            print(f"loops-to-resolution histogram: {self.loops_to_resolution}")
        for note in self.notes:
            print(f"note: {note}")
        print()
