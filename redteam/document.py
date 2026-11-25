"""Loading a PRD, splitting it into sections, and verifying quoted evidence."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
NUMBERED_HEADING_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)]?\s+([A-Z][^.!?]{2,80})$")


@dataclass
class Section:
    title: str
    level: int
    start_line: int  # 1-based
    end_line: int
    text: str


@dataclass
class PRDDocument:
    text: str
    path: str = ""
    lines: list[str] = field(init=False)
    sections: list[Section] = field(init=False)

    def __post_init__(self) -> None:
        self.text = self.text.replace("\r\n", "\n")
        self.lines = self.text.split("\n")
        self.sections = split_sections(self.lines)
        self._norm, self._norm_map = _normalise_with_map(self.text)

    @property
    def title(self) -> str:
        for s in self.sections:
            if s.level == 1:
                return s.title
        first = next((l.strip() for l in self.lines if l.strip()), "Untitled PRD")
        return first.lstrip("# ").strip()[:120]

    def numbered(self) -> str:
        """PRD with line numbers, so the model can anchor quotes."""
        width = len(str(len(self.lines)))
        return "\n".join(f"L{str(i).rjust(width)}| {line}" for i, line in enumerate(self.lines, 1))

    def section_titles(self) -> list[str]:
        return [s.title for s in self.sections]

    def section_for_line(self, line: int) -> str:
        best = ""
        for s in self.sections:
            if s.start_line <= line:
                best = s.title
        return best

    def locate(self, quote: str, threshold: float = 0.85) -> tuple[bool, int | None]:
        """Return (found, 1-based line) for a quote, tolerant of whitespace,
        case, punctuation and small paraphrase drift."""
        q = _normalise(quote)
        if len(q) < 8:
            return False, None
        idx = self._norm.find(q)
        if idx == -1:
            # Anchor on the longest exact overlap, then fuzzy-compare the aligned window.
            m = SequenceMatcher(None, self._norm, q, autojunk=False).find_longest_match(0, len(self._norm), 0, len(q))
            start = max(0, m.a - m.b)
            window = self._norm[start : start + len(q)]
            covered = m.size / len(q)
            if covered < threshold and SequenceMatcher(None, window, q, autojunk=False).ratio() < threshold:
                return False, None
            idx = start
        orig_offset = self._norm_map[min(max(idx, 0), len(self._norm_map) - 1)]
        return True, self.text.count("\n", 0, orig_offset) + 1


def split_sections(lines: list[str]) -> list[Section]:
    marks: list[tuple[int, int, str]] = []
    for i, line in enumerate(lines, 1):
        m = HEADING_RE.match(line)
        if m:
            marks.append((i, len(m.group(1)), m.group(2).strip()))
            continue
        m = NUMBERED_HEADING_RE.match(line)
        if m and len(line) < 90:
            marks.append((i, m.group(1).count(".") + 2, m.group(2).strip()))
    if not marks:
        return [Section("Document", 1, 1, len(lines), "\n".join(lines))]
    sections = []
    for j, (start, level, title) in enumerate(marks):
        end = marks[j + 1][0] - 1 if j + 1 < len(marks) else len(lines)
        sections.append(Section(title, level, start, end, "\n".join(lines[start - 1 : end])))
    return sections


def _normalise(s: str) -> str:
    s = s.lower().replace("’", "'").replace("“", '"').replace("”", '"')
    s = re.sub(r"[^\w\s%$₹.]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _normalise_with_map(text: str) -> tuple[str, list[int]]:
    """Normalise text and keep a map from normalised index -> original index."""
    out: list[str] = []
    mapping: list[int] = []
    prev_space = True
    for i, ch in enumerate(text):
        c = ch.lower().replace("’", "'")
        if not (c.isalnum() or c in "_%$₹." or c.isspace()):
            c = " "
        if c.isspace():
            if prev_space:
                continue
            c, prev_space = " ", True
        else:
            prev_space = False
        out.append(c)
        mapping.append(i)
    return "".join(out).strip(), mapping or [0]


def load_prd(path: str | Path) -> PRDDocument:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in {".md", ".markdown", ".txt", ""}:
        text = p.read_text(encoding="utf-8")
    elif suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError("Reading PDFs needs: pip install pypdf") from e
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(p)).pages)
    elif suffix == ".docx":
        try:
            import docx  # python-docx
        except ImportError as e:
            raise RuntimeError("Reading .docx needs: pip install python-docx") from e
        d = docx.Document(str(p))
        parts = []
        for para in d.paragraphs:
            style = (para.style.name or "").lower()
            if style.startswith("heading"):
                level = "".join(ch for ch in style if ch.isdigit()) or "1"
                parts.append("#" * int(level) + " " + para.text)
            else:
                parts.append(para.text)
        text = "\n".join(parts)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
    if not text.strip():
        raise ValueError(f"{p} appears to be empty")
    return PRDDocument(text=text, path=str(p))
