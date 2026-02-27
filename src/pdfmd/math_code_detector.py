"""Heuristic detection of mathematical formulas and code blocks in text."""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Math detection
# ---------------------------------------------------------------------------

# Common LaTeX commands found in PDFs
_LATEX_COMMANDS = re.compile(
    r"\\(?:frac|sqrt|sum|prod|int|lim|infty|alpha|beta|gamma|delta|epsilon|"
    r"theta|lambda|mu|sigma|omega|pi|phi|psi|partial|nabla|forall|exists|"
    r"rightarrow|leftarrow|Rightarrow|Leftarrow|leq|geq|neq|approx|equiv|"
    r"subset|supset|cup|cap|wedge|vee|oplus|otimes|cdot|times|div|pm|mp|"
    r"begin\{|end\{|matrix|bmatrix|pmatrix|align|equation)"
)

# Unicode math symbols
_MATH_UNICODE = re.compile(
    r"[\u2200-\u22FF"  # Mathematical Operators
    r"\u2A00-\u2AFF"   # Supplemental Mathematical Operators
    r"\u27C0-\u27EF"   # Miscellaneous Mathematical Symbols-A
    r"\u2980-\u29FF"   # Miscellaneous Mathematical Symbols-B
    r"\u0391-\u03C9"   # Greek letters
    r"\u2190-\u21FF"   # Arrows
    r"∫∑∏√∞≤≥≠≈∂∇∀∃±×÷·]"
)

# Equation-like patterns (e.g., "x = a + b", "f(x) = ...")
_EQUATION_PATTERN = re.compile(
    r"(?:^|\n)\s*[a-zA-Z_]\w*\s*(?:\([^)]*\))?\s*=\s*[^=\n]+(?:\n|$)",
    re.MULTILINE,
)

# Subscript/superscript patterns common in math
_SUB_SUPER = re.compile(r"[a-zA-Z]_\{[^}]+\}|[a-zA-Z]\^\{[^}]+\}")


def detect_math(text: str) -> str:
    """Detect and wrap mathematical expressions in LaTeX delimiters.

    Parameters
    ----------
    text : str
        Input text that may contain mathematical expressions.

    Returns
    -------
    str
        Text with math expressions wrapped in ``$...$`` or ``$$...$$``.
    """
    # If the text already has LaTeX delimiters, leave it
    if re.search(r"(?<!\$)\$(?!\$).*?(?<!\$)\$(?!\$)", text):
        return text
    if "$$" in text:
        return text

    result = text

    # Wrap lines that look like full equations in display math
    lines = result.split("\n")
    processed: list[str] = []

    for line in lines:
        stripped = line.strip()

        # Full-line equation: contains LaTeX commands or heavy math symbols
        latex_matches = len(_LATEX_COMMANDS.findall(stripped))
        math_symbols = len(_MATH_UNICODE.findall(stripped))

        if latex_matches >= 2 or math_symbols >= 3:
            # Wrap in display math
            if not stripped.startswith("$$"):
                processed.append(f"\n$${stripped}$$\n")
            else:
                processed.append(line)
        elif latex_matches >= 1 or math_symbols >= 1:
            # Inline math: wrap individual expressions
            processed.append(_wrap_inline_math(line))
        else:
            processed.append(line)

    return "\n".join(processed)


def _wrap_inline_math(text: str) -> str:
    """Wrap individual math expressions within a line as inline math."""
    # Find LaTeX command sequences and wrap them
    result = _LATEX_COMMANDS.sub(lambda m: f"${m.group(0)}$", text)

    # Find standalone math Unicode and wrap if not already wrapped
    def _wrap_unicode(match: re.Match) -> str:
        char = match.group(0)
        start = match.start()
        # Check if already inside $ delimiters
        prefix = result[:start]
        if prefix.count("$") % 2 == 1:
            return char
        return f"${char}$"

    return result


# ---------------------------------------------------------------------------
# Code detection
# ---------------------------------------------------------------------------

# Programming language patterns
_CODE_PATTERNS = [
    # Function/class definitions
    re.compile(r"^\s*(?:def|class|function|func|fn|pub fn|async fn)\s+\w+", re.MULTILINE),
    # Import statements
    re.compile(r"^\s*(?:import|from|require|include|use|using)\s+", re.MULTILINE),
    # Common syntax
    re.compile(r"^\s*(?:if|else|elif|while|for|return|var|let|const|int|float|string)\s+", re.MULTILINE),
    # Brackets and semicolons typical of code
    re.compile(r"[{};]\s*$", re.MULTILINE),
    # Comment patterns
    re.compile(r"^\s*(?://|#|/\*|\*\s)", re.MULTILINE),
    # Assignment with types
    re.compile(r"\w+\s*:\s*\w+\s*=", re.MULTILINE),
    # Arrow functions, method chains
    re.compile(r"(?:=>|->|\.\w+\()", re.MULTILINE),
]

# Language detection heuristics
_LANGUAGE_HINTS = {
    "python": [
        re.compile(r"\bdef\s+\w+\s*\("),
        re.compile(r"\bclass\s+\w+\s*[:(]"),
        re.compile(r"\bimport\s+\w+"),
        re.compile(r"\bself\.\w+"),
    ],
    "javascript": [
        re.compile(r"\bfunction\s+\w+\s*\("),
        re.compile(r"\bconst\s+\w+\s*="),
        re.compile(r"\b(?:let|var)\s+\w+"),
        re.compile(r"=>\s*[{(]"),
    ],
    "java": [
        re.compile(r"\bpublic\s+(?:class|static|void)"),
        re.compile(r"\bSystem\.out\.print"),
        re.compile(r"\bnew\s+\w+\s*\("),
    ],
    "rust": [
        re.compile(r"\bfn\s+\w+\s*\("),
        re.compile(r"\blet\s+(?:mut\s+)?\w+"),
        re.compile(r"\bimpl\s+\w+"),
    ],
    "sql": [
        re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP)\b", re.IGNORECASE),
        re.compile(r"\bFROM\s+\w+", re.IGNORECASE),
        re.compile(r"\bWHERE\s+", re.IGNORECASE),
    ],
}


def detect_code_blocks(text: str) -> str:
    """Detect code blocks in text and wrap them in fenced code blocks.

    Parameters
    ----------
    text : str
        Input text that may contain code snippets.

    Returns
    -------
    str
        Text with code blocks wrapped in ``` fences.
    """
    lines = text.split("\n")
    result: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this starts a code-like block
        if _is_code_line(line):
            code_lines = [line]
            j = i + 1

            # Collect consecutive code-like lines
            while j < len(lines):
                next_line = lines[j]
                # Allow blank lines within code blocks
                if not next_line.strip():
                    # Look ahead to see if code continues
                    if j + 1 < len(lines) and _is_code_line(lines[j + 1]):
                        code_lines.append(next_line)
                        j += 1
                        continue
                    break
                elif _is_code_line(next_line):
                    code_lines.append(next_line)
                    j += 1
                else:
                    break

            # Only wrap as code if we have at least 2 consecutive code lines
            if len(code_lines) >= 2:
                code_text = "\n".join(code_lines)
                language = _guess_language(code_text)
                result.append(f"```{language}")
                result.extend(code_lines)
                result.append("```")
                i = j
                continue

        result.append(line)
        i += 1

    return "\n".join(result)


def _is_code_line(line: str) -> bool:
    """Heuristically determine if a line looks like code."""
    stripped = line.strip()
    if not stripped:
        return False

    score = 0
    for pattern in _CODE_PATTERNS:
        if pattern.search(stripped):
            score += 1

    # Indentation is a strong signal
    if line.startswith("    ") or line.startswith("\t"):
        score += 1

    return score >= 2


def _guess_language(code: str) -> str:
    """Guess the programming language of a code block."""
    scores: dict[str, int] = {}

    for lang, patterns in _LANGUAGE_HINTS.items():
        score = sum(1 for p in patterns if p.search(code))
        if score > 0:
            scores[lang] = score

    if scores:
        return max(scores, key=scores.get)  # type: ignore[arg-type]
    return ""
