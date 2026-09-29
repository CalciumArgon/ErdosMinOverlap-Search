"""Tests for the lenient EVOLVE-BLOCK extraction fallback (marker-less model output)."""

from simpletes.utils.code_extract import EvolveBlockContext, extract_code_detailed

PREFIX = "# EVOLVE-BLOCK-START\n"
SUFFIX = "# EVOLVE-BLOCK-END\n\n\ndef run_code():\n    return construct_h()\n"

INIT_PROGRAM = (
    PREFIX
    + "import numpy as np\n\ndef construct_h():\n    return 0.5\n\n"
    + SUFFIX
)


def _context():
    ctx = EvolveBlockContext.from_program(INIT_PROGRAM)
    assert ctx.has_markers
    return ctx


def test_markers_present_still_extracted():
    ctx = _context()
    out = "```python\n# EVOLVE-BLOCK-START\nimport numpy as np\n\ndef construct_h():\n    return 0.25\n# EVOLVE-BLOCK-END\n```"
    code, reason = extract_code_detailed(out, ctx)
    assert reason == "evolve_block_merged", reason
    assert "return 0.25" in code
    assert PREFIX.strip() in code and SUFFIX.strip() in code


def test_lenient_fallback_last_python_block():
    ctx = _context()
    out = (
        "Some reasoning prose first.\n\n"
        "```python\nimport numpy as np\ndef construct_h():\n    return 0.9\n```\n"
        "More prose.\n\n"
        "```python\nfrom fractions import Fraction\ndef construct_h():\n    return [Fraction(1, 2)] * 7\n```\n"
    )
    code, reason = extract_code_detailed(out, ctx)
    assert reason == "evolve_block_merged_lenient", reason
    # last python block is the chosen evolved content
    assert "Fraction(1, 2)" in code
    assert PREFIX.strip() in code and SUFFIX.strip() in code


def test_lenient_fallback_raw_code():
    ctx = _context()
    out = "import numpy as np\n\ndef construct_h():\n    return 0.6\n"
    code, reason = extract_code_detailed(out, ctx)
    assert reason == "evolve_block_merged_lenient", reason
    assert "return 0.6" in code
    assert PREFIX.strip() in code and SUFFIX.strip() in code


def test_no_code_still_rejected():
    ctx = _context()
    out = "I cannot solve this problem right now."
    code, reason = extract_code_detailed(out, ctx)
    assert code is None
    assert reason == "missing_evolve_block_markers", reason


def test_non_python_block_not_chosen_when_python_present():
    ctx = _context()
    out = (
        "```\nsome generic text\n```\n"
        "```python\nimport numpy as np\ndef construct_h():\n    return 0.3\n```\n"
    )
    code, reason = extract_code_detailed(out, ctx)
    assert reason == "evolve_block_merged_lenient", reason
    assert "return 0.3" in code
