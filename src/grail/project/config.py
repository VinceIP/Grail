from dataclasses import dataclass
from pathlib import Path
import tomllib

GRAIL_DIR_NAME = ".grail"
PROJECT_CONFIG_NAME = "project.toml"
DEFAULT_DB_NAME = "project.grail.db"

@dataclass(frozen=True)
class ProjectConfig:
    """Loaded information about a GRAIL project."""

    root: Path
    config_path: Path
    name: str
    platform: str
    assembler: str
    asm_root: Path
    database_path: Path

def default_project_paths(project_root: Path) -> tuple[Path, Path]:
    """Return default config and database paths for a project."""

    grail_dir = project_root / GRAIL_DIR_NAME
    config_path = grail_dir / PROJECT_CONFIG_NAME
    database_path = grail_dir / DEFAULT_DB_NAME

    return config_path, database_path

def find_project_root(start_path: str | Path = ".") -> Path | None:
    """Search upward from start_path until a GRAIL project is found."""

    current = Path(start_path).resolve()

    if current.is_file():
        current = current.parent

    for path in [current, *current.parents]:
        config_path = path / GRAIL_DIR_NAME / PROJECT_CONFIG_NAME
        if config_path.exists():
            return path
    
    return None

def load_project_config(project_root: str | Path = ".") -> ProjectConfig:
    """Load `.grail/project.toml` from a GRAIL project."""

    found_root = find_project_root(project_root)

    if found_root is None:
        raise FileNotFoundError(
            "No GRAIL project found. Try running 'grail project init' from the root of your disassembly project."
        )
    
    config_path = found_root / GRAIL_DIR_NAME / PROJECT_CONFIG_NAME

    with config_path.open("rb") as file:
        data = tomllib.load(file)

    project_data = data.get("project", {})
    paths_data = data.get("paths", {})

    asm_root = found_root / paths_data.get("asm_root", "src")
    database_path = found_root / paths_data.get(
        "database",
        f"{GRAIL_DIR_NAME}/{DEFAULT_DB_NAME}"
    )

    return ProjectConfig(
        root=found_root,
        config_path=config_path,
        name=project_data.get("name", found_root.name),
        platform=project_data.get("platform", "gb"),
        assembler=project_data.get("assembler", "rgbds"),
        asm_root=asm_root,
        database_path=database_path
    )

def write_project_config(
        project_root: str | Path,
        name: str,
        platform: str,
        assembler: str,
        asm_root: str | Path,
        database_path: str | Path,
        force: bool = False
) -> Path:
    """Create `.grail/project.toml`"""

    project_root = Path(project_root).resolve()
    config_path, _default_db_path = default_project_paths(project_root)

    if config_path.exists() and not force:
        raise FileExistsError(
            f"GRAIL project already exists at {config_path}. "
            "Use --force to overwrite existing config."
        )
    
    config_path.parent.mkdir(parents=True, exist_ok=True)

    asm_root=Path(asm_root)
    database_path=Path(database_path)

    config_text = f"""# GRAIL project configuration

[project]
name = "{name}" # The working name of this project
platform = "{platform}" # The platform targeted for assembly (Game Boy 'gb', Game Boy Color 'gbc')
assembler = "{assembler}" # The assembler used to link and build a ROM file (typically rgbds)

[paths]
asm_root = "{asm_root.as_posix()}" # where disassembled .asm files should be
database = "{database_path.as_posix()}" # path to the project's knowledge database
    
    """

    config_path.write_text(config_text, encoding="utf-8")

    print(f"Wrote new project configuration to {config_path}.")

    return config_path
