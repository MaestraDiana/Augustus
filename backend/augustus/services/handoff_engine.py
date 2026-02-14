"""Handoff Protocol Engine — between-session basin parameter updates."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from augustus.models.dataclasses import (
    BasinConfig,
    BasinSnapshot,
    CoActivationEntry,
    EvaluatorOutput,
)
from augustus.models.enums import EmphasisLevel

logger = logging.getLogger(__name__)


@dataclass
class HandoffResult:
    """Result of a handoff protocol execution."""

    updated_basins: list[BasinConfig] = field(default_factory=list)
    emphasis_directive: str = ""
    basin_snapshots: list[BasinSnapshot] = field(default_factory=list)
    co_activation_updates: list[CoActivationEntry] = field(default_factory=list)
    change_rationale: str = ""


class HandoffEngine:
    """Execute between-session calculations on basin parameters."""

    EMPHASIS_THRESHOLDS = [
        (0.80, EmphasisLevel.STRONGLY_FOREGROUNDED),
        (0.60, EmphasisLevel.ACTIVE),
        (0.40, EmphasisLevel.AVAILABLE),
        (0.20, EmphasisLevel.BACKGROUNDED),
        (0.05, EmphasisLevel.LIGHTLY_PRESENT),
    ]

    def execute_handoff(
        self,
        basins: list[BasinConfig],
        evaluator_output: EvaluatorOutput | None,
        self_assessment: dict | None,
        co_activation_entries: list[CoActivationEntry] | None,
    ) -> HandoffResult:
        """Execute full handoff protocol."""
        # Save original alphas for delta computation
        before = [
            BasinConfig(
                name=b.name,
                basin_class=b.basin_class,
                alpha=b.alpha,
                lambda_=b.lambda_,
                eta=b.eta,
                tier=b.tier,
            )
            for b in basins
        ]

        # Step 1: Determine relevance source
        relevance = {}
        source = "none"
        if evaluator_output and evaluator_output.basin_relevance:
            relevance = evaluator_output.basin_relevance
            source = "evaluator"
        elif self_assessment:
            relevance = self_assessment
            source = "self_assessment"
            logger.warning(
                "Using self-assessment for relevance (evaluator unavailable)"
            )

        # Step 2: Apply decay to all basins
        updated = []
        for basin in basins:
            new_alpha = self.apply_decay(basin)

            # Step 3: Apply relevance boost
            rel_score = relevance.get(basin.name, 0.0)
            new_alpha = self.apply_boost(new_alpha, basin.eta, rel_score)

            # Step 4: Clamp
            new_alpha = self.clamp_alpha(new_alpha)

            updated.append(
                BasinConfig(
                    name=basin.name,
                    basin_class=basin.basin_class,
                    alpha=round(new_alpha, 6),
                    lambda_=basin.lambda_,
                    eta=basin.eta,
                    tier=basin.tier,
                )
            )

        # Step 5: Compute snapshots (deltas)
        snapshots = self.compute_basin_deltas(before, updated, relevance)

        # Step 6: Generate emphasis directive
        emphasis = self.generate_emphasis_directive(updated)

        # Build change rationale
        changes = []
        for snap in snapshots:
            direction = "↑" if snap.delta > 0 else "↓" if snap.delta < 0 else "→"
            changes.append(
                f"{snap.basin_name}: {snap.alpha_start:.3f} {direction} {snap.alpha_end:.3f} "
                f"(Δ{snap.delta:+.4f}, rel={snap.relevance_score:.2f})"
            )
        rationale = (
            f"Handoff complete (source: {source}). "
            + ("; ".join(changes) if changes else "No changes.")
        )

        return HandoffResult(
            updated_basins=updated,
            emphasis_directive=emphasis,
            basin_snapshots=snapshots,
            co_activation_updates=co_activation_entries or [],
            change_rationale=rationale,
        )

    def apply_decay(self, basin: BasinConfig) -> float:
        """alpha_new = alpha * lambda"""
        return basin.alpha * basin.lambda_

    def apply_boost(self, alpha: float, eta: float, relevance: float) -> float:
        """alpha_new = alpha + eta * relevance"""
        return alpha + eta * relevance

    def clamp_alpha(self, alpha: float) -> float:
        """Clamp to [0.05, 1.0]."""
        return max(0.05, min(1.0, alpha))

    def get_emphasis_level(self, alpha: float) -> EmphasisLevel:
        """Map alpha to emphasis level using thresholds."""
        for threshold, level in self.EMPHASIS_THRESHOLDS:
            if alpha >= threshold:
                return level
        return EmphasisLevel.LIGHTLY_PRESENT

    def generate_emphasis_directive(self, basins: list[BasinConfig]) -> str:
        """Translate alpha rankings into natural language."""
        if not basins:
            return "No basins configured."

        # Group basins by emphasis level
        groups: dict[EmphasisLevel, list[str]] = {}
        for basin in sorted(basins, key=lambda b: b.alpha, reverse=True):
            level = self.get_emphasis_level(basin.alpha)
            groups.setdefault(level, []).append(basin.name.replace("_", " "))

        # Build natural language directive
        parts = []
        level_descriptions = {
            EmphasisLevel.STRONGLY_FOREGROUNDED: "strongly foregrounded",
            EmphasisLevel.ACTIVE: "active",
            EmphasisLevel.AVAILABLE: "available but not leading",
            EmphasisLevel.BACKGROUNDED: "backgrounded",
            EmphasisLevel.LIGHTLY_PRESENT: "lightly present",
        }

        for level in [
            EmphasisLevel.STRONGLY_FOREGROUNDED,
            EmphasisLevel.ACTIVE,
            EmphasisLevel.AVAILABLE,
            EmphasisLevel.BACKGROUNDED,
            EmphasisLevel.LIGHTLY_PRESENT,
        ]:
            names = groups.get(level, [])
            if not names:
                continue
            desc = level_descriptions[level]
            if len(names) == 1:
                parts.append(f"{names[0].capitalize()} is {desc}.")
            elif len(names) == 2:
                parts.append(f"{names[0].capitalize()} and {names[1]} are {desc}.")
            else:
                listed = ", ".join(names[:-1]) + f", and {names[-1]}"
                parts.append(f"{listed.capitalize()} are {desc}.")

        return " ".join(parts)

    def compute_basin_deltas(
        self, before: list[BasinConfig], after: list[BasinConfig], relevance: dict
    ) -> list[BasinSnapshot]:
        """Compute deltas between before and after states."""
        after_map = {b.name: b for b in after}
        snapshots = []
        for b in before:
            a = after_map.get(b.name)
            if a:
                delta = round(a.alpha - b.alpha, 6)
                snapshots.append(
                    BasinSnapshot(
                        basin_name=b.name,
                        alpha_start=b.alpha,
                        alpha_end=a.alpha,
                        delta=delta,
                        relevance_score=relevance.get(b.name, 0.0),
                    )
                )
        return snapshots
