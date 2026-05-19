"""Abstract DocumentRenderer."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Mapping


class DocumentRenderer(ABC):
    @abstractmethod
    def render(
        self,
        slot_values: Mapping[str, str],
        output_path: Path,
        confidence: Mapping[str, str] | None = None,
    ) -> None:
        """Substitute slot values into the template and write to output_path.

        Implementations are responsible for:
          - Reading the template
          - Replacing all `{{slot_key}}` placeholders
          - Visually marking low-confidence values (e.g. red font),
            using `confidence` map of slot_key -> 'high'|'medium'|'low'.
        """
        ...
