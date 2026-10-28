from app.parsers.base import FormatHandler, InvalidFormatError, UnsupportedFormatError
from app.parsers.formats.csv_format_1 import CSVFormatHandler
from app.parsers.formats.xlsx_format_1 import XLSXFormatHandler
from app.parsers.registry import FormatRegistry


def build_default_registry() -> FormatRegistry:
    registry = FormatRegistry()
    registry.register(CSVFormatHandler())
    registry.register(XLSXFormatHandler())
    return registry


__all__ = [
    "FormatRegistry",
    "FormatHandler",
    "InvalidFormatError",
    "UnsupportedFormatError",
    "build_default_registry",
]
