from pathlib import Path

from grail.project.config import load_project_config

def get_project_info(start_path: str | Path = ".") -> dict:
    """Return information about the active GRAIL project."""

    config = load_project_config(start_path)

    return {
        "root": config.root,
        "config_path": config.config_path,
        "name": config.name,
        "platform": config.platform,
        "assembler": config.assembler,
        "asm_root": config.asm_root,
        "database_path": config.database_path,
        "database_exists": config.database_path.exists(),
        "asm_root_exists": config.asm_root.exists(),
    }