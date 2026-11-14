from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Diagnostic:
    code: str
    path: str
    message: str
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
            **({"details": self.details} if self.details else {}),
        }


class InputContractError(Exception):
    def __init__(self, diagnostics: list[Diagnostic]):
        self.diagnostics = diagnostics
        super().__init__("Input does not match the supported upstream contracts")

