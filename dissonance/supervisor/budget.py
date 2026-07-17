from __future__ import annotations

from dataclasses import dataclass, field

from dissonance.supervisor.config import RunConfig


@dataclass
class StageSpend:
    stage: str
    budget_usd: float
    spent_usd: float = 0.0

    @property
    def over_budget(self) -> bool:
        return self.budget_usd > 0 and self.spent_usd > self.budget_usd


@dataclass
class BudgetTracker:
    """Per-stage sub-budgets plus a run-level ceiling.

    The run halts gracefully (flag, not exception) once total spend crosses
    ``warn_at_fraction`` of the run budget -- callers check ``halted`` between
    work units and stop pulling new ones. See plan.md §4 "Supervisor invariants".
    """

    run_budget_usd: float
    warn_at_fraction: float
    stages: dict[str, StageSpend] = field(default_factory=dict)
    halted: bool = False
    halt_reason: str | None = None

    @classmethod
    def from_run_config(cls, run_config: RunConfig) -> "BudgetTracker":
        stages = {
            name: StageSpend(stage=name, budget_usd=cfg.budget_usd)
            for name, cfg in run_config.stages.items()
        }
        return cls(
            run_budget_usd=run_config.run.budget_usd,
            warn_at_fraction=run_config.run.warn_at_fraction,
            stages=stages,
        )

    def record(self, stage: str, usd: float) -> None:
        s = self.stages.setdefault(stage, StageSpend(stage=stage, budget_usd=0.0))
        s.spent_usd += usd
        if not self.halted and self.total_spent_usd >= self.run_budget_usd * self.warn_at_fraction:
            self.halted = True
            self.halt_reason = (
                f"run spend ${self.total_spent_usd:.4f} reached "
                f"{self.warn_at_fraction:.0%} of ${self.run_budget_usd:.2f} budget"
            )

    @property
    def total_spent_usd(self) -> float:
        return sum(s.spent_usd for s in self.stages.values())

    def report(self) -> dict[str, dict[str, float]]:
        return {
            name: {"budget_usd": s.budget_usd, "spent_usd": round(s.spent_usd, 6)}
            for name, s in self.stages.items()
        }
