"""High-volume generated verification for Stage 4B1 table parsing."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from metricproof.adapters.latex import LocalLatexPaperScanner


def _generated_tables(table_count: int, rows_per_table: int, columns: int) -> str:
    chunks: list[str] = []
    value = 1
    specification = "c" * columns
    for table_index in range(table_count):
        chunks.extend(
            (
                "\\begin{table}\n",
                f"\\caption{{Generated table {table_index + 1}}}\n",
                f"\\begin{{tabular}}{{{specification}}}\n",
                "\\toprule\n",
            )
        )
        for row_index in range(rows_per_table):
            cells: list[str] = []
            for column_index in range(columns):
                raw = f"{value}.25"
                if (row_index + column_index) % 3 == 0:
                    cells.append(f"\\textbf{{{raw}}}")
                elif (row_index + column_index) % 3 == 1:
                    cells.append(f"\\underline{{{raw}}}")
                else:
                    cells.append(raw)
                value += 1
            chunks.append(" & ".join(cells) + " \\\\\n")
        chunks.extend(("\\bottomrule\n", "\\end{tabular}\n", "\\end{table}\n"))
    return "".join(chunks)


def _scan_generated(root: Path, table_count: int, rows: int, columns: int):
    text = _generated_tables(table_count, rows, columns)
    source = root / "paper" / "main.tex"
    source.parent.mkdir(parents=True)
    source.write_text(text, encoding="utf-8", newline="")
    started = perf_counter()
    result = LocalLatexPaperScanner().scan(root, ("paper/main.tex",))
    return result, perf_counter() - started


def test_thousands_of_table_cells_scale_without_duplicate_candidates(tmp_path: Path) -> None:
    small, small_elapsed = _scan_generated(tmp_path / "small", 10, 10, 5)
    large, large_elapsed = _scan_generated(tmp_path / "large", 50, 20, 5)

    assert small.complete
    assert large.complete
    assert small.statistics.table_count == 10
    assert large.statistics.table_count == 50
    assert sum(len(table.rows) for table in large.tables) == 1_000
    assert sum(len(row.cells) for table in large.tables for row in table.rows) == 5_000
    assert len(large.candidates) == 5_050
    references = [
        reference.candidate
        for table in large.tables
        for row in table.rows
        for cell in row.cells
        for reference in cell.numeric_references
    ]
    table_candidates = [
        candidate for candidate in large.candidates if not candidate.raw_text.isdigit()
    ]
    assert references == table_candidates
    assert len({id(candidate) for candidate in references}) == 5_000
    assert large_elapsed < 10
    assert large_elapsed <= small_elapsed * 25 + 1
