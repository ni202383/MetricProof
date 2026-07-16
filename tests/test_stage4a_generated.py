"""High-volume generated verification for Stage 4A lexical and performance behavior."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from metricproof.adapters.latex import LocalLatexPaperScanner


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def test_one_thousand_generated_numeric_lexemes_preserve_text_and_offsets(
    tmp_path: Path,
) -> None:
    raw_values: list[str] = []
    for index in range(1, 1001):
        variant = index % 8
        if variant == 0:
            raw = str(index)
        elif variant == 1:
            raw = f"{index}.25"
        elif variant == 2:
            raw = f".{index:04d}"
        elif variant == 3:
            raw = f"-{index}"
        elif variant == 4:
            raw = f"+{index}"
        elif variant == 5:
            raw = f"{index}.2e-3"
        elif variant == 6:
            raw = f"{index}.5%"
        else:
            raw = f"{index}.5\\%"
        raw_values.append(raw)
    text = "".join(f"value {raw}\n" for raw in raw_values)
    _write(tmp_path, "paper/main.tex", text)

    result = LocalLatexPaperScanner().scan(tmp_path, ("paper/main.tex",))

    assert result.complete
    assert [item.raw_text for item in result.candidates] == raw_values
    cursor = 0
    for expected, candidate in zip(raw_values, result.candidates, strict=True):
        expected_start = text.index(expected, cursor)
        assert candidate.location.char_start == expected_start
        assert candidate.location.char_end == expected_start + len(expected)
        assert text[candidate.location.char_start : candidate.location.char_end] == expected
        cursor = expected_start + len(expected)


def test_two_hundred_comment_escape_parity_cases(tmp_path: Path) -> None:
    lines: list[str] = []
    expected: list[str] = []
    for index in range(200):
        backslashes = "\\" * ((index % 6) + 1)
        value = str(10_000 + index)
        lines.append(f"prefix {backslashes}% suffix {value}\n")
        if len(backslashes) % 2 == 1:
            expected.append(value)
    _write(tmp_path, "paper/main.tex", "".join(lines))

    result = LocalLatexPaperScanner().scan(tmp_path, ("paper/main.tex",))

    assert [item.raw_text for item in result.candidates] == expected


def _performance_project(root: Path, file_count: int, numbers_per_file: int) -> int:
    includes: list[str] = []
    expected = 0
    for file_index in range(file_count):
        relative = f"paper/parts/part-{file_index}.tex"
        includes.append(f"\\input{{parts/part-{file_index}}}\n")
        lines = ["\\begin{table}\n"]
        for number_index in range(numbers_per_file):
            value = file_index * numbers_per_file + number_index
            if number_index % 25 == 0:
                lines.append(f"% ignored {value}\n")
            else:
                lines.append(f"row {value}\n")
                expected += 1
        lines.append("\\end{table}\n")
        _write(root, relative, "".join(lines))
    _write(root, "paper/main.tex", "".join(includes))
    return expected


def test_synthetic_multifile_scan_has_no_obvious_quadratic_regression(
    tmp_path: Path,
) -> None:
    small_root = tmp_path / "small"
    large_root = tmp_path / "large"
    small_expected = _performance_project(small_root, 2, 625)
    large_expected = _performance_project(large_root, 8, 625)
    scanner = LocalLatexPaperScanner()

    small_start = perf_counter()
    small = scanner.scan(small_root, ("paper/main.tex",))
    small_elapsed = perf_counter() - small_start

    large_start = perf_counter()
    large = scanner.scan(large_root, ("paper/main.tex",))
    large_elapsed = perf_counter() - large_start

    assert len(small.candidates) == small_expected
    assert len(large.candidates) == large_expected
    assert large_expected >= 4_000
    assert large_elapsed < 10
    assert large_elapsed <= small_elapsed * 12 + 1
