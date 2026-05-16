"""Interface abstraite des executors pairing_exec.

Chaque executor (Docker, native SSH) implémente `exec_step` pour exécuter
une `StepDescriptor` donnée et retourner un `StepResult` (exit_code + I/O).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.services.pairing_exec.steps import PairingPayload, StepDescriptor


@dataclass(frozen=True)
class StepResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def is_success(self) -> bool:
        return self.exit_code == 0


class Executor(ABC):
    """Interface contractuelle pour les moteurs d'exécution."""

    @abstractmethod
    async def open(self) -> None:
        """Ouvre la session (connexion Docker ou SSH). Idempotent."""

    @abstractmethod
    async def close(self) -> None:
        """Ferme la session proprement. Idempotent."""

    @abstractmethod
    async def exec_step(
        self,
        step: StepDescriptor,
        payload: PairingPayload,
    ) -> StepResult:
        """Exécute une étape et retourne le résultat. Ne lève PAS sur exit != 0."""
