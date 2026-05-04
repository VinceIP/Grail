from pathlib import Path

from grail.db.init import init_db
from grail.project.config import(
    DEFAULT_DB_NAME,
    GRAIL_DIR_NAME,
    default_project_paths,
    write_project_config
)

def init_project(
    project_root: str | Path = ".",
    name: str | None = None,
    platform: str = "gb",
    assembler: str = "rgbds",
    asm_root: str | Path = "src",
    force: bool = False,
) -> dict:
    """Initialize GRAIL inside a disassembly project folder.
        Creates `.grail/project.toml` and `./grail/project.grail.db`
    """

    project_root = Path(project_root).resolve()

    if name is None:
        name = project_root.name

    config_path, database_path = default_project_paths(project_root)
    relative_database_path = Path(GRAIL_DIR_NAME) / DEFAULT_DB_NAME

    write_project_config(
        project_root=project_root,
        name=name,
        platform=platform,
        assembler=assembler,
        asm_root=asm_root,
        database_path=relative_database_path,
        force=force,
    )

    init_db(database_path)

    return {
        "project_root": project_root,
        "config_path": config_path,
        "database_path": database_path,
        "name": name,
        "platform": platform,
        "assembler": assembler,
        "asm_root": Path(asm_root),
    }