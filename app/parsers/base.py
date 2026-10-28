from abc import ABC, abstractmethod

from app.models.record import IngestedRecord


class InvalidFormatError(Exception):
    """Raised when a handler cannot parse a file's content into canonical records."""


class UnsupportedFormatError(Exception):
    """Raised when no registered handler recognizes a file."""


class FormatHandler(ABC):
    """Strategy interface: one concrete class per file format."""

    format_id: str = ""
    extensions: tuple[str, ...] = ()

    @abstractmethod
    def probe(self, filename: str, content: bytes) -> bool:
        """Return True if this handler recognizes the file (content + extension)."""

    @abstractmethod
    def parse(self, content: bytes) -> list[IngestedRecord]:
        """Parse raw bytes into canonical records. Raise InvalidFormatError on failure."""
