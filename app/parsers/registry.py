from app.parsers.base import FormatHandler


class FormatRegistry:
    """Holds all available format handlers and probes files against them."""

    def __init__(self) -> None:
        self._handlers: dict[str, FormatHandler] = {}

    def register(self, handler: FormatHandler) -> None:
        self._handlers[handler.format_id] = handler

    def probe(self, filename: str, content: bytes) -> FormatHandler | None:
        """Return the first handler whose probe() accepts the file, else None."""
        for handler in self._handlers.values():
            if handler.probe(filename, content):
                return handler
        return None

    def supported_extensions(self) -> list[str]:
        """Sorted, de-duplicated list of filename extensions across all handlers."""
        exts: set[str] = set()
        for handler in self._handlers.values():
            exts.update(handler.extensions)
        return sorted(exts)

    def __len__(self) -> int:
        return len(self._handlers)
