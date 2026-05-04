import argparse
from pathlib import Path

from grail import __version__
from grail.db.info import get_db_info
from grail.db.init import DEFAULT_DB_PATH, init_db
from grail.project.info import get_project_info
from grail.project.init import init_project


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for the `grail` command."""

    parser = argparse.ArgumentParser(
        prog="grail",
        description="GRAIL: Game Boy Reverse Engineering AI Lab",
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"grail {__version__}",
    )

    subcommands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    add_project_commands(subcommands)
    add_db_commands(subcommands)

    return parser


def add_project_commands(subcommands: argparse._SubParsersAction) -> None:
    """Register commands under `grail project`."""

    project_parser = subcommands.add_parser(
        "project",
        help="Create and inspect GRAIL project configuration",
    )

    project_subcommands = project_parser.add_subparsers(
        dest="project_command",
        required=True,
    )

    # grail project init
    init_parser = project_subcommands.add_parser(
        "init",
        help="Initialize GRAIL in the current disassembly project",
    )

    init_parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Project root. Default: current directory.",
    )

    init_parser.add_argument(
        "--name",
        default=None,
        help="Project name. Default: current directory name.",
    )

    init_parser.add_argument(
        "--platform",
        default="gb",
        help="Target platform. Default: gb.",
    )

    init_parser.add_argument(
        "--assembler",
        default="rgbds",
        help="Assembler used by the project. Default: rgbds.",
    )

    init_parser.add_argument(
        "--asm-root",
        type=Path,
        default=Path(""),
        help="Path to assembly source root, relative to project root. Default: src.",
    )

    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing .grail/project.toml if it already exists.",
    )

    # grail project info
    info_parser = project_subcommands.add_parser(
        "info",
        help="Show information about the active GRAIL project",
    )

    info_parser.add_argument(
        "--root",
        type=Path,
        default=Path("."),
        help="Start path for project discovery. Default: current directory.",
    )


def add_db_commands(subcommands: argparse._SubParsersAction) -> None:
    """Register commands under `grail db`."""

    db_parser = subcommands.add_parser(
        "db",
        help="Manage the GRAIL project database",
    )

    db_subcommands = db_parser.add_subparsers(
        dest="db_command",
        required=True,
    )

    # grail db init
    init_parser = db_subcommands.add_parser(
        "init",
        help="Initialize a GRAIL SQLite project database",
    )

    init_parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to the database file. Default: {DEFAULT_DB_PATH}",
    )

    # grail db info
    info_parser = db_subcommands.add_parser(
        "info",
        help="Show basic information about the GRAIL database",
    )

    info_parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to the database file. Default: {DEFAULT_DB_PATH}",
    )


def main() -> None:
    """Entry point for `grail` terminal command."""

    parser = build_parser()
    args = parser.parse_args()

    if args.command == "project":
        handle_project_command(args)
        return

    if args.command == "db":
        handle_db_command(args)
        return

    parser.error("No command provided.")


def handle_project_command(args: argparse.Namespace) -> None:
    """Handle commands under `grail project`."""

    if args.project_command == "init":
        result = init_project(
            project_root=args.root,
            name=args.name,
            platform=args.platform,
            assembler=args.assembler,
            asm_root=args.asm_root,
            force=args.force,
        )

        print(f"Initialized GRAIL project: {result['name']}")
        print(f"Project root: {result['project_root']}")
        print(f"Config: {result['config_path']}")
        print(f"Database: {result['database_path']}")
        print(f"ASM root: {result['asm_root']}")
        return

    if args.project_command == "info":
        info = get_project_info(args.root)

        print(f"Project: {info['name']}")
        print(f"Root: {info['root']}")
        print(f"Config: {info['config_path']}")
        print(f"Platform: {info['platform']}")
        print(f"Assembler: {info['assembler']}")
        print(f"ASM root: {info['asm_root']}")

        if info["asm_root_exists"]:
            print("ASM root exists: yes")
        else:
            print("ASM root exists: no")

        print(f"Database: {info['database_path']}")

        if info["database_exists"]:
            print("Database exists: yes")
        else:
            print("Database exists: no")

        return

    raise ValueError(f"Unknown project command: {args.project_command}")


def handle_db_command(args: argparse.Namespace) -> None:
    """Handle commands under `grail db`."""

    if args.db_command == "init":
        db_path = init_db(args.db)
        print(f"Initialized GRAIL database at {db_path}")
        return

    if args.db_command == "info":
        info = get_db_info(args.db)

        print(f"GRAIL database: {info['db_path']}")
        print(f"Schema version: {info['schema_version']}")
        print(f"GRAIL version: {info['grail_version']}")
        print(f"Symbols: {info['symbol_count']}")
        print(f"Code refs: {info['code_ref_count']}")
        print(f"Claims: {info['claim_count']}")
        return

    raise ValueError(f"Unknown db command: {args.db_command}")