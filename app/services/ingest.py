from app.parsers.base import UnsupportedFormatError
from app.parsers.registry import FormatRegistry
from app.services.repository import IngestResult, upsert_records


def ingest(conn, registry: FormatRegistry, filename: str, content: bytes) -> IngestResult:
    """Run the full pipeline for one uploaded file: probe -> parse -> upsert.

    Raises UnsupportedFormatError if no handler matches; InvalidFormatError if parsing fails.
    """
    handler = registry.probe(filename, content)
    if handler is None:
        raise UnsupportedFormatError(
            f"Unsupported file format for {filename!r} "
            f"(supported extensions: {registry.supported_extensions()})"
        )
    records = handler.parse(content)
    result = upsert_records(conn, records, source_file=filename)
    result.format = handler.format_id
    return result
