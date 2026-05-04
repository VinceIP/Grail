from pathlib import Path
import sqlite3

def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection to a GRAIL SQLite database.

    Parameters
    ----------
    db_path : str | Path
      Path to the SQLite database file.

      
    Returns
    -------
    slite3.Connection
        An open SQLite connection.
    """

    db_path = Path(db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    return conn