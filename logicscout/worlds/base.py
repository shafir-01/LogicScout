"""World base class and registry. PRIVATE: only the sandbox and the referee import this module.

A world is a deterministic simulator with hidden laws. Laws live in `self.laws` (a dict of
parameters) so a hidden change (`shift`) can rewrite them; `reset` restores state but keeps laws.
"""
from __future__ import annotations

import random
from abc import ABC, abstractmethod
from typing import ClassVar

from logicscout.contracts import JSON, Action, Case, Observation, ShiftRecord, StepResult, WorldManual


class World(ABC):
    world_id: ClassVar[str]

    def __init__(self, variant: str = "standard") -> None:
        self.variant = variant
        self.laws: JSON = self.default_laws(variant)
        self.t = 0
        self.rng = random.Random(0)

    # ---- public surface (mirrored by WorldPort) ----------------------------------------
    @classmethod
    @abstractmethod
    def manual(cls) -> WorldManual: ...

    @abstractmethod
    def reset(self, seed: int) -> Observation:
        """Restore initial state for `seed`. Must keep `self.laws` (shifts survive resets)."""

    @abstractmethod
    def observe(self) -> Observation: ...

    @abstractmethod
    def act(self, action: Action) -> StepResult: ...

    # ---- private surface (sandbox admin + referee) -------------------------------------
    @classmethod
    @abstractmethod
    def default_laws(cls, variant: str) -> JSON:
        """Hidden parameters for a variant. `standard` is what the scout meets in the lab."""

    @classmethod
    @abstractmethod
    def variants(cls) -> list[str]:
        """All variant names, `standard` first. Others are held out for the referee."""

    @abstractmethod
    def shift(self, seed: int, kind: str | None = None) -> ShiftRecord:
        """Silently rewrite one or more laws (deterministic in seed; `kind` picks a shift_menu id). Returns what changed."""

    @classmethod
    def shift_menu(cls) -> list[dict]:
        """Hidden changes a human may choose: [{id, label}]. Never shown to the scout."""
        return []

    @abstractmethod
    def success(self, objective_id: str) -> bool:
        """Ground truth: is the objective genuinely met in the current hidden state?"""

    @classmethod
    @abstractmethod
    def truth(cls, laws: JSON) -> list[str]:
        """The hidden laws in plain words, for the post-run debrief."""

    @classmethod
    @abstractmethod
    def referee_cases(cls) -> list[Case]:
        """Held-out cases: seeds outside manual().lab_seeds and/or non-standard variants."""


REGISTRY: dict[str, type[World]] = {}


def register(cls: type[World]) -> type[World]:
    REGISTRY[cls.world_id] = cls
    return cls


def load_all() -> dict[str, type[World]]:
    """Import every world module so @register runs."""
    import importlib
    import pkgutil

    import logicscout.worlds as pkg

    for mod in pkgutil.iter_modules(pkg.__path__):
        if mod.name not in {"base"}:
            importlib.import_module(f"logicscout.worlds.{mod.name}")
    return REGISTRY
