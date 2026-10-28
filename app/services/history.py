CONTACT_FIELDS = ("email", "phone", "fax", "title")


def diff_fields(
    old: dict, new: dict, fields: tuple[str, ...] = CONTACT_FIELDS
) -> list[tuple[str, str | None, str | None]]:
    """Return [(field_name, old_value, new_value), ...] for fields whose value changed."""
    changes: list[tuple[str, str | None, str | None]] = []
    for field in fields:
        old_value = old.get(field)
        new_value = new.get(field)
        if old_value != new_value:
            changes.append((field, old_value, new_value))
    return changes


def write_history(
    conn, person_id: int, changes: list[tuple[str, str | None, str | None]],
    version: int, source_file: str,
) -> int:
    """Insert one person_history row per changed field. Return the number of rows written."""
    written = 0
    for field, old_value, new_value in changes:
        conn.execute(
            "INSERT INTO person_history "
            "(history_id, person_id, field_name, old_value, new_value, version, source_file) "
            "VALUES (nextval('person_history_seq'), ?, ?, ?, ?, ?, ?)",
            [person_id, field, old_value, new_value, version, source_file],
        )
        written += 1
    return written
