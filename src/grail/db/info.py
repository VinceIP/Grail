from pathlib import Path

from grail.db.connection import connect

def get_db_info(db_path: str | Path) -> dict:
    """Get information about a GRAIL database.
    
    Parameters
    ----------
    db_path : str | Path
        Path to the SQLite database file.

    Returns
    -------
    dict
        Information about the given database.
    """

    db_path = Path(db_path)

    conn = connect(db_path)

    try:
        metadata = _get_metadata(conn)

        return {
            "db_path": str(db_path),
            "schema_version": metadata.get("schema_version", "unknown"),
            "grail_version": metadata.get("grail_version", "unknown"),
            "symbol_count": _count_rows(conn, "symbols"),
            "code_ref_count": _count_rows(conn, "code_refs"),
            "claim_count": _count_rows(conn, "claims"),
        }
    
    finally:
        conn.close()

def _get_metadata(conn) -> dict[str,str]:
    """Read all key/value pairs from a GRAIL metadata table."""

    rows = conn.execute(
        """
        SELECT key, value FROM metadata ORDER BY key
        """
    ).fetchall()

    metadata = {}

    for row in rows:
        metadata[row["key"]] = row["value"]

    return metadata

def _count_rows(conn, table_name: str) -> int:
    """Count rows in thr given table."""

    row = conn.execute(
        f"""
        SELECT COUNT(*) AS count FROM {table_name}
        """
    ).fetchone()

    return int(row["count"])