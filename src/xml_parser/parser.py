"""Stream section-aware text chunks without a dependency on Chroma."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlencode
from xml.etree import ElementTree as ET


class Record(TypedDict):
    id: str
    document: str
    metadata: dict[str, str | int]


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _text(element: ET.Element) -> str:
    """Keep inline tails, paragraph boundaries, tables, and CAML fractions."""
    tag = _tag(element)
    if tag == "Fraction":
        return "/".join(_text(child).strip() for child in element)
    parts = [element.text or ""]
    if tag == "br" or "EnSpace" in element.get("class", "").split():
        parts.append(" ")
    for child in element:
        parts.extend((_text(child), child.tail or ""))
    if tag in {"p", "tr", "h1", "h2", "h3"}:
        parts.append("\n\n")
    elif tag in {"td", "th"}:
        parts.append(" | ")
    return "".join(parts)


def _paragraphs(element: ET.Element) -> list[str]:
    return [
        normalized
        for part in re.split(r"\n\s*\n", _text(element))
        if (normalized := " ".join(part.split()))
    ]


def _chunks(
    paragraphs: list[str], prefix: str, limit: int, measure: Callable[[str], int]
) -> Iterator[str]:
    current = ""
    for paragraph in paragraphs:
        candidate = "\n\n".join(filter(None, (current, paragraph)))
        if measure(prefix + candidate) <= limit:
            current = candidate
            continue
        if current:
            yield prefix + current
            current = ""
        # Oversized paragraphs are split at whitespace where possible. Count
        # the entire candidate, including its citation, with the supplied measure.
        remaining = paragraph
        while measure(prefix + remaining) > limit:
            low, high = 0, len(remaining)
            while low < high:
                middle = (low + high + 1) // 2
                if measure(prefix + remaining[:middle]) <= limit:
                    low = middle
                else:
                    high = middle - 1
            if not low:
                raise ValueError("chunk_size cannot fit the citation and source text")
            boundary = remaining.rfind(" ", 0, low + 1)
            cut = boundary if boundary > 0 else low
            yield prefix + remaining[:cut]
            remaining = remaining[cut:].lstrip()
        current = remaining
    if current:
        yield prefix + current


def iter_records(
    xml_path: str | Path,
    *,
    chunk_size: int = 2000,
    length_function: Callable[[str], int] = len,
) -> Iterator[Record]:
    """Yield ``id``, ``document``, and scalar ``metadata`` dictionaries.

    The default budget is characters, NOT tokens. Supply your embedding model's
    tokenizer as length_function and an appropriate chunk_size for token limits.
    Chunks never cross sections. Paragraph boundaries are preferred; oversized
    paragraphs are split without discarding text. Retrieve sibling chunks by
    parent_id for legal context: a split chunk is not a standalone legal rule.

    IDs include content and an occurrence number because the source can contain
    multiple records with the same section number. Rebuild the collection for a
    new snapshot to avoid retaining obsolete records from earlier imports.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    occurrences: dict[str, int] = defaultdict(int)
    stack: list[ET.Element] = []
    last_updated = ""
    with Path(xml_path).open("rb") as source:
        for event, element in ET.iterparse(source, events=("start", "end")):
            if event == "start":
                stack.append(element)
                if len(stack) == 1:
                    last_updated = element.get("lastUpdated", "")
                continue
            if _tag(element) == "section":
                number = element.get("number", "").strip().rstrip(".")
                if not number:
                    raise ValueError("Section is missing its number")
                content = next((c for c in element if _tag(c) == "contentXml"), None)
                paragraphs = _paragraphs(content) if content is not None else []
                if not paragraphs:
                    raise ValueError(f"Section {number} has no content")
                history = next(
                    (
                        " ".join(_text(c).split())
                        for c in element
                        if _tag(c) == "history"
                    ),
                    "",
                )
                body = "\n\n".join(paragraphs)
                digest = hashlib.sha256((history + "\n" + body).encode()).hexdigest()
                identity = f"RTC:{number}:{digest}"
                occurrence = occurrences[identity]
                occurrences[identity] += 1
                parent_id = f"{identity}:{occurrence}"
                prefix = f"California Revenue and Taxation Code\nSection {number}\n\n"
                if length_function(prefix) >= chunk_size:
                    raise ValueError(f"Section {number}: chunk_size is too small")
                for index, document in enumerate(
                    _chunks(paragraphs, prefix, chunk_size, length_function)
                ):
                    yield {
                        "id": f"{parent_id}:{index}",
                        "document": document,
                        "metadata": {
                            "code": "RTC",
                            "section": number,
                            "parent_id": parent_id,
                            "chunk_index": index,
                            "history": history,
                            "last_updated": last_updated,
                            "source_url": "https://leginfo.legislature.ca.gov/faces/"
                            "codes_displaySection.xhtml?"
                            + urlencode({"lawCode": "RTC", "sectionNum": number + "."}),
                        },
                    }
                if len(stack) > 1:
                    stack[-2].remove(element)
                element.clear()
            stack.pop()
