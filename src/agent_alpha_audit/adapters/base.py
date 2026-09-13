from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import TrialRecord


class AgentAdapter(ABC):
    @abstractmethod
    def parse(self, path: str | Path, run_id: str) -> list[TrialRecord]:
        raise NotImplementedError
