# Chunk Report

## Summary
- **Total chunks**: 354
- **Source files**: 9
- **JSONL validity**: Passed (one valid JSON object per line, no trailing commas)
- **All required metadata fields present**: Yes
- **No empty text chunks**: Confirmed

## Chunks Per Source File
| Source File | Manual Page | Chunk Count |
|---|---|---|
| gbz80.7.md | gbz80(7) | 122 |
| rgbasm.1.md | rgbasm(1) | 29 |
| rgbasm.5.md | rgbasm(5) | 90 |
| rgbds.5.md | rgbds(5) | 31 |
| rgbds.7.md | rgbds(7) | 3 |
| rgbfix.1.md | rgbfix(1) | 20 |
| rgbgfx.1.md | rgbgfx(1) | 35 |
| rgblink.1.md | rgblink(1) | 17 |
| rgblink.5.md | rgblink(5) | 7 |

## Chunk Type Distribution
| Type | Count | Description |
|---|---|---|
| overview | 112 | General section descriptions, SYNOPSIS, DESCRIPTION |
| instruction | 103 | Individual CPU instruction reference entries |
| option | 50 | Command-line option descriptions (ARGUMENTS sections) |
| reference_table | 34 | Instruction family overviews, format tables, function lists |
| warning | 16 | Diagnostics, bugs, warnings |
| syntax | 11 | Language syntax rules and symbol interpolation |
| see_also | 9 | Cross-references to other manual pages |
| history | 9 | Version history notes |
| example | 6 | Usage examples |
| directive | 4 | Assembler directive documentation |

## Chunk Size Distribution
| Range | Count |
|---|---|
| <20 words | 70 |
| 20-100 words | 177 |
| 100-300 words | 100 |
| 300-600 words | 7 |
| >600 words | 0 |

- **Min**: 2 words
- **Max**: 398 words
- **Median**: 45 words
- **Mean**: 79 words

## Sections That Were Hard to Chunk

1. **rgbasm.5.md - Symbol interpolation** (7 sub-chunks, many <20 words): The original section has numerous short code examples and edge cases separated by blank lines. Splitting by paragraphs produced several very small chunks that each contain a single example or rule. These are kept because they contain exact syntax patterns important for retrieval.

2. **rgbasm.5.md - Fixed-point expressions** (7 sub-chunks): Similar pattern of short operator descriptions split into individual chunks. Each chunk covers one fixed-point operator (*, /, etc.).

3. **gbz80.7.md - Instruction family overviews** (e.g., "Carry flag instructions", "Miscellaneous instructions"): These are index sections listing instruction links with minimal descriptive text (2-6 words). Kept as reference_table type for navigation context but contain very little standalone content.

4. **rgbasm.1.md / rgbgfx.1.md / rgblink.1.md - ARGUMENTS/OPTIONS**: These CLI docs have no sub-headings within the options section, only paragraph breaks between option descriptions. Splitting by paragraphs works but produces chunks all sharing the same heading path ("ARGUMENTS").

5. **rgbasm.5.md - Invoking macros** (8 sub-chunks) and **Automatically repeating blocks of code** (6 sub-chunks): Long sections with many short examples that split into numerous small chunks.

## Suspected Conversion Problems in the Markdown

1. **Synopsis keyword noise**: Synopsis sections contain command-line usage patterns like `name[=value]` and `-v ...` inside backticks, which produce keywords like `[=value` and `...`. These are harmless for retrieval but slightly noisy.

2. **Escaped brackets in gbz80 headings**: Instruction reference headings like `### [ADC A,[HL]](#ADC_A,_HL_)` contain nested brackets that required special handling. The cleaned heading paths correctly show `ADC A,[HL]` with escaped brackets representing assembly syntax, not markdown artifacts.

3. **No #### sub-headings in CLI docs**: rgbasm.1.md, rgbfix.1.md, rgblink.1.md, and rgbgfx.1.md only use ## headings with no ### or #### sub-headings for individual options. This means option-level chunking relies entirely on paragraph breaks rather than heading hierarchy.

## Terms to Test With Retrieval Queries

### Tool-specific queries
- "rgbfix checksum validation" → should find rgbfix header checksum chunks
- "rgbgfx tile data 2bpp palette" → should find rgbgfx conversion chunks
- "rgbasm define symbol -D" → should find rgbasm CLI option chunks
- "rgblink SECTION bank ORG ALIGN" → should find section placement chunks

### Instruction queries (gbz80)
- "ldh instruction gameboy" → should find LDH instruction reference
- "rst opcode cycles" → should find RST instruction chunk
- "sla hl bit shift" → should find SLA [HL] instruction
- "daa decimal adjustment" → should find DAA instruction
- "cp compare flags" → should find CP instruction family

### Syntax queries (rgbasm.5)
- "local label scope rgbasm" → should find label scoping rules
- "EQUS string interpolation braces" → should find symbol interpolation chunks
- "SECTION ROMX bank number" → should find section definition syntax
- "INCBIN binary include" → should find binary data inclusion chunk

### Hardware references
- "$FF47 BGP palette register" → should find rgbgfx palette chunks
- "VRAM WRAM HRAM OAM memory map" → should find section type definitions

### Cross-reference queries
- "rgbds object file format RGB9" → should find rgbds.5 header chunk
- "linker script bank specification" → should find rgblink.5 chunks
