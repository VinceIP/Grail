from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from grail.db.connection import connect
from grail.project.config import load_project_config

# Regex for identifying symbols.
GLOBAL_LABEL_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_.$@?#]*)::?\s*(?:;.*)?$"
)

LOCAL_LABEL_RE = re.compile(
    r"^(?P<name>\.[A-Za-z_][A-Za-z0-9_.$@?#]*)::?\s*(?:;.*)?$"
)

EQU_RE = re.compile(
    r"^(?:DEF\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_.$@?#]*)\s+EQU\s+(?P<value>[^;]+)"
)

MACRO_RE = re.compile(
    r"^(?P<name>[A-Za-z_][A-Za-z0-9_.$@?#]*)\s+MACRO\b"
)


@dataclass
class IndexedSymbol:
    """A symbol indexed from assembly source."""

    name: str
    symbol_type: str
    file_path: str
    line_start: int
    line_end: int | None = None


@dataclass
class IndexSummary:
    """Small result obj returned after indexing."""

    asm_files_seen: int = 0
    symbols_seen: int = 0
    symbols_inserted_or_updated: int = 0


def index_project(start_path: str | Path = ".", assume_yes: bool = False) -> IndexSummary:
    """Index the active GRAIL project's assembly files."""

    config = load_project_config(start_path)

    if not config.asm_root.exists():
        raise FileNotFoundError(f"ASM root does not exist: {config.asm_root}")

    asm_files = list(find_asm_files(config.asm_root))

    if not assume_yes:
        _confirm_index(
            project_name=config.name,
            asm_root=config.asm_root,
            database_path=config.database_path,
            asm_file_count=len(asm_files),
        )

    all_symbols: list[IndexedSymbol] = []

    for asm_file in asm_files:
        symbols = parse_symbols_from_file(
            asm_file=asm_file,
            project_root=config.root,
        )
        all_symbols.extend(symbols)

    written_count = write_symbols_to_db(
        db_path=config.database_path,
        symbols=all_symbols,
    )

    return IndexSummary(
        asm_files_seen=len(asm_files),
        symbols_seen=len(all_symbols),
        symbols_inserted_or_updated=written_count,
    )


def find_asm_files(asm_root: Path) -> Iterable[Path]:
    """Yield all `.asm` files in asm_root."""

    yield from sorted(asm_root.rglob("*.asm"))


def parse_symbols_from_file(asm_file: Path, project_root: Path) -> list[IndexedSymbol]:
    """Parse symbols from one RGBDS assembly file."""

    lines = asm_file.read_text(encoding="utf-8").splitlines()

    relative_file_path = asm_file.relative_to(project_root).as_posix()

    symbols: list[IndexedSymbol] = []
    top_level_symbol_indexes: list[int] = []

    current_global_name: str | None = None

    for index, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()

        # Skip empty lines and pure comments.
        if not line or line.startswith(";"):
            continue

        macro_match = MACRO_RE.match(line)
        if macro_match:
            name = macro_match.group("name")

            symbols.append(
                IndexedSymbol(
                    name=name,
                    symbol_type="macro",
                    file_path=relative_file_path,
                    line_start=index,
                    line_end=index,
                )
            )
            continue

        equ_match = EQU_RE.match(line)
        if equ_match:
            name = equ_match.group("name")
            value = equ_match.group("value").strip()

            symbols.append(
                IndexedSymbol(
                    name=name,
                    symbol_type=classify_constant(name, value),
                    file_path=relative_file_path,
                    line_start=index,
                    line_end=index,
                )
            )
            continue

        local_match = LOCAL_LABEL_RE.match(line)
        if local_match:
            local_name = local_match.group("name")

            if current_global_name is not None:
                qualified_name = f"{current_global_name}{local_name}"
            else:
                # If a file starts with a local label somehow, keep it visible.
                qualified_name = local_name

            symbols.append(
                IndexedSymbol(
                    name=qualified_name,
                    symbol_type="local_label",
                    file_path=relative_file_path,
                    line_start=index,
                    line_end=index,
                )
            )
            continue

        global_match = GLOBAL_LABEL_RE.match(line)
        if global_match:
            name = global_match.group("name")
            symbol_type = classify_global_label(name)

            symbol = IndexedSymbol(
                name=name,
                symbol_type=symbol_type,
                file_path=relative_file_path,
                line_start=index,
            )

            symbols.append(symbol)

            if symbol_type == "local_label":
                symbol.line_end = index
            else:
                current_global_name = name
                top_level_symbol_indexes.append(len(symbols) - 1)

            continue

    set_top_level_line_ends(
        symbols=symbols,
        top_level_symbol_indexes=top_level_symbol_indexes,
        file_line_count=len(lines),
    )

    return symbols


def set_top_level_line_ends(
    symbols: list[IndexedSymbol],
    top_level_symbol_indexes: list[int],
    file_line_count: int,
) -> None:
    """Fill in line_end for top-level symbols."""

    for position, symbol_index in enumerate(top_level_symbol_indexes):
        symbol = symbols[symbol_index]

        if position + 1 < len(top_level_symbol_indexes):
            next_symbol = symbols[top_level_symbol_indexes[position + 1]]
            symbol.line_end = next_symbol.line_start - 1
        else:
            symbol.line_end = file_line_count


def classify_global_label(name: str) -> str:
    """Return a rough guess symbol type for a global label.

    Initial classification of a symbol type may be incorrect and reclassified
    through reverse engineering.
    """

    lower_name = name.lower()

    # mgbdis can generate labels like jr_000_0605 for conditional branch
    # targets. Even though they look like global labels, they usually represent
    # internal branch points inside the current routine.
    if lower_name.startswith("jr_"):
        return "local_label"

    # Searching for symbol names likely generated by mgbdis for disassembled code.
    if lower_name.startswith("call_"):
        # Since a Call probably returns, we can initially assume its code is
        # meant to be a function candidate, especially if it is reusable code.
        return "function_candidate"

    if lower_name.startswith("jump_"):
        # General indicator for a block of code. Could be a branch path, loop
        # target, state-machine target, etc.
        return "code_label"

    if lower_name.startswith("rst_"):
        return "rst_vector"

    # mgbdis labels these automatically.
    if lower_name in (
        "vblankinterrupt",
        "lcdcinterrupt",
        "timeroverflowinterrupt",
        "serialtransfercompleteinterrupt",
        "joypadtransitioninterrupt",
    ):
        return "interrupt_vector"

    return "unknown"


def classify_constant(name: str, value: str) -> str:
    """Classify an EQU/DEF constant."""

    if name.startswith("r") and looks_like_hardware_address(value):
        return "hardware_register"

    return "constant"


def looks_like_hardware_address(value: str) -> bool:
    """Return True if value appears to be a Game Boy hardware register address."""

    value = value.lower().strip()

    if not value.startswith("$"):
        return False

    if value == "$ffff":  # Interrupt enable register.
        return True

    try:
        number = int(value[1:], 16)
    except ValueError:
        return False

    return 0xFF00 <= number <= 0xFF7F  # I/O register range.


def write_symbols_to_db(db_path: Path, symbols: list[IndexedSymbol]) -> int:
    """Write indexed symbols into SQLite."""

    conn = connect(db_path)

    try:
        with conn:
            for symbol in symbols:
                conn.execute(
                    """
                    INSERT INTO symbols (
                        name,
                        type,
                        file_path,
                        line_start,
                        line_end,
                        symbol_status
                    )
                    VALUES (?, ?, ?, ?, ?, 'indexed')
                    ON CONFLICT(name) DO UPDATE SET
                        type = CASE
                            WHEN symbols.type IN (
                                'unknown',
                                'function_candidate',
                                'code_label',
                                'data_label',
                                'local_label'
                            )
                            THEN excluded.type
                            ELSE symbols.type
                        END,
                        file_path = excluded.file_path,
                        line_start = excluded.line_start,
                        line_end = excluded.line_end
                    """,
                    (
                        symbol.name,
                        symbol.symbol_type,
                        symbol.file_path,
                        symbol.line_start,
                        symbol.line_end,
                    ),
                )

        return len(symbols)

    finally:
        conn.close()


def _confirm_index(
    project_name: str,
    asm_root: Path,
    database_path: Path,
    asm_file_count: int,
) -> None:
    """Ask the user before indexing."""

    print(f"Project: {project_name}")
    print(f"ASM root: {asm_root}")
    print(f"Database: {database_path}")
    print(f"ASM files found: {asm_file_count}")
    print()
    print("This will index assembly symbols into the GRAIL database.")
    print("Existing human notes, claims, and verification status will not be overwritten.")
    print()

    answer = input("Continue? [y/N] ").strip().lower()

    if answer not in {"y", "yes"}:
        raise SystemExit("Index cancelled.")