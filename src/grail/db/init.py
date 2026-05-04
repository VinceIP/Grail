from importlib.resources import files
from pathlib import Path

from grail import __version__
from grail.db.connection import connect

DEFAULT_DB_PATH = Path(".grail/project.grail.db")

def init_db(db_path: str | Path = DEFAULT_DB_PATH) -> Path:
    """Create or update a GRAIL project database.

    Parameters
    ----------
    db_path:
        Path to SQLite database.

    Returns
    -------
    Path
        Resolved Path of the database file.
    """

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema_text = files("grail.db").joinpath("schema.sql").read_text()

    conn = connect(db_path)

    try:
        with conn:
            conn.executescript(schema_text)
            conn.execute(
                """
                INSERT OR REPLACE INTO metadata (key, value)
                VALUES (?, ?)
                """,
                ("grail_version", __version__)
            )

            conn.execute(
                """
                INSERT OR REPLACE INTO metadata (key, value)
                VALUES (?, ?)
                """,
                ("schema_version", "1")
            )
    
    finally:
        conn.close()

    return db_path