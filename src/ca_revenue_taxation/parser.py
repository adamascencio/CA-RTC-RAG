#!/usr/bin/env python3
"""Download and extract the California Revenue and Taxation Code.

Adapted from johnakelly-yahoo-com/california-codes/update_ca_codes.py.
Only the active Revenue and Taxation Code (RTC) is written.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from html import unescape
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = SCRIPT_DIR / "data" / "CA Code - Revenue and Taxation Code.txt"
RTC_CODE = "RTC"


def get_download_url() -> str:
    """Return the official ZIP for the current two-year legislative session."""
    year = datetime.now().year
    session_year = year if year % 2 else year - 1
    return f"https://downloads.leginfo.legislature.ca.gov/pubinfo_{session_year}.zip"


def strip_backticks(value: str) -> str:
    if value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def parse_tsv(filepath: Path, field_names: list[str]) -> list[dict[str, str]]:
    """Read a tab-delimited bulk table whose values are backtick-enclosed."""
    rows = []
    with filepath.open("r", encoding="utf-8", errors="replace") as source:
        for line in source:
            line = line.rstrip("\n\r")
            if not line:
                continue
            parts = line.split("\t")
            rows.append(
                {
                    name: strip_backticks(parts[i]) if i < len(parts) else ""
                    for i, name in enumerate(field_names)
                }
            )
    return rows


def xml_to_text(xml_content: str) -> str:
    """Convert CAML XML section content to readable plain text."""
    if not xml_content:
        return ""
    text = re.sub(r"<caml:Content[^>]*>|</caml:Content>", "", xml_content)
    text = re.sub(r'<span\s+class="EnSpace"\s*/?\s*>', " ", text)
    text = re.sub(r"</p>\s*<p>", "\n\n", text)
    text = re.sub(r"<p>", "", text)
    text = re.sub(r"</p>", "", text)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</?(?:i|b|em|strong)>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def read_lob_file(data_dir: Path, lob_filename: str) -> str:
    """Read a section's .lob file and convert XML to text."""
    path = data_dir / lob_filename
    if not path.exists():
        return ""
    try:
        return xml_to_text(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        print(f"  Warning: could not read {lob_filename}: {exc}")
        return ""


def parse_code(data_dir: Path, output_path: Path) -> None:
    """Parse RTC tables and write one ordered plain-text code file."""
    codes = parse_tsv(data_dir / "CODES_TBL.dat", ["code", "title"])
    code_names = {}
    for row in codes:
        if row["code"] == RTC_CODE:
            title = re.sub(r"\s*-\s*[A-Z]+\s*$", "", row["title"])
            code_names[row["code"]] = title.lstrip("* ").strip()
    if RTC_CODE not in code_names:
        raise RuntimeError("RTC was not present in CODES_TBL.dat")
    code_title = code_names[RTC_CODE]

    toc_fields = [
        "law_code",
        "division",
        "title",
        "part",
        "chapter",
        "article",
        "heading",
        "active_flg",
        "trans_uid",
        "trans_update",
        "node_sequence",
        "node_level",
        "node_position",
        "node_treepath",
        "contains_law_sections",
        "history_note",
        "op_statues",
        "op_chapter",
        "op_section",
    ]
    toc_by_path: dict[str, dict[str, object]] = {}
    for row in parse_tsv(data_dir / "LAW_TOC_TBL.dat", toc_fields):
        if row["law_code"] == RTC_CODE and row["active_flg"] == "Y":
            toc_by_path[row["node_treepath"]] = {
                "heading": row["heading"],
                "node_level": int(float(row["node_level"])) if row["node_level"] else 0,
            }

    section_fields = [
        "id",
        "law_code",
        "section_num",
        "op_statues",
        "op_chapter",
        "op_section",
        "effective_date",
        "law_section_version_id",
        "division",
        "title",
        "part",
        "chapter",
        "article",
        "history",
        "lob_file",
        "active_flg",
        "trans_uid",
        "trans_update",
    ]
    sections = []
    latest_update = ""
    for row in parse_tsv(data_dir / "LAW_SECTION_TBL.dat", section_fields):
        if row["law_code"] != RTC_CODE or row["active_flg"] != "Y":
            continue
        sections.append(row)
        update = row["trans_update"]
        if update and update > latest_update:
            latest_update = update

    toc_sec_fields = [
        "id",
        "law_code",
        "node_treepath",
        "section_num",
        "section_order",
        "title",
        "op_statues",
        "op_chapter",
        "op_section",
        "trans_uid",
        "trans_update",
        "law_section_version_id",
        "seq_num",
    ]
    section_order: dict[str, tuple[str, float, float]] = {}
    for row in parse_tsv(data_dir / "LAW_TOC_SECTIONS_TBL.dat", toc_sec_fields):
        if row["law_code"] != RTC_CODE:
            continue
        version_id = row["law_section_version_id"]
        value = (
            row["node_treepath"],
            float(row["section_order"]) if row["section_order"] else 0,
            float(row["seq_num"]) if row["seq_num"] else 0,
        )
        if version_id not in section_order or value < section_order[version_id]:
            section_order[version_id] = value

    def sort_key(section: dict[str, str]):
        version_id = section["law_section_version_id"]
        if version_id in section_order:
            treepath, order, seq = section_order[version_id]
            path_parts = [float(part) for part in treepath.split(".") if part]
            return (path_parts, order, seq)
        match = re.match(r"(\d+\.?\d*)", section["section_num"] or "")
        number = float(match.group(1)) if match else 99999
        return ([99999], 0, number)

    sections.sort(key=sort_key)
    separator = "\n\n" + "=" * 70 + "\n\n"
    thin_separator = "\n" + "-" * 43 + "\n\n"
    try:
        last_updated = datetime.strptime(latest_update[:10], "%Y-%m-%d").strftime(
            "%B %d, %Y"
        )
    except ValueError:
        last_updated = latest_update or "Unknown"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as output:
        output.write(
            f"{'=' * 70}\n  {code_title}\n  State of California\n{'=' * 70}\n\n"
        )
        output.write("Source: Official California Legislative Information\n")
        output.write("        https://downloads.leginfo.legislature.ca.gov/\n")
        output.write(f"Last Updated by State of California: {last_updated}{separator}")
        written_headings: set[str] = set()
        print(
            f"Processing {RTC_CODE} ({code_title}): {len(sections)} active sections..."
        )
        for section in sections:
            version_id = section["law_section_version_id"]
            if version_id in section_order:
                treepath = section_order[version_id][0]
                parts = treepath.split(".")
                for depth in range(1, len(parts) + 1):
                    parent_path = ".".join(parts[:depth])
                    if (
                        parent_path in written_headings
                        or parent_path not in toc_by_path
                    ):
                        continue
                    entry = toc_by_path[parent_path]
                    heading = str(entry["heading"])
                    level = int(entry["node_level"])
                    if heading:
                        if level <= 1:
                            output.write(separator + heading.upper())
                        elif level == 2:
                            output.write(f"\n\n{heading}")
                        else:
                            output.write(f"\n\n  {heading}")
                        output.write("\n\n")
                    written_headings.add(parent_path)
            content = (
                read_lob_file(data_dir, section["lob_file"].strip())
                if section["lob_file"].strip()
                else ""
            )
            if not content:
                continue
            output.write(f"{section['section_num'].strip()}\n\n{content}")
            history = section["history"].strip()
            if history:
                output.write(f"\n\n(History: {history})")
            output.write(thin_separator)

    size = output_path.stat().st_size
    size_str = f"{size / 1048576:.1f}MB" if size > 1048576 else f"{size / 1024:.0f}KB"
    print(f"Wrote {output_path} ({size_str})")


def download_and_parse(output_path: Path, keep_download: bool = False) -> None:
    download_url = get_download_url()
    tmp_dir = Path(tempfile.mkdtemp(prefix="ca_rtc_"))
    zip_path = tmp_dir / download_url.rsplit("/", 1)[-1]
    try:
        print(f"Downloading {download_url} (the ZIP is several hundred MB)...")
        subprocess.run(["curl", "-fL", "-o", str(zip_path), download_url], check=True)
        print("Extracting RTC tables...")
        subprocess.run(
            [
                "unzip",
                "-o",
                str(zip_path),
                "CODES_TBL.dat",
                "LAW_SECTION_TBL.dat",
                "LAW_TOC_TBL.dat",
                "LAW_TOC_SECTIONS_TBL.dat",
            ],
            cwd=tmp_dir,
            check=True,
            capture_output=True,
        )
        print("Extracting section content files...")
        subprocess.run(
            ["unzip", "-o", str(zip_path), "LAW_SECTION_TBL_*.lob"],
            cwd=tmp_dir,
            check=True,
            capture_output=True,
        )
        lob_count = sum(1 for path in tmp_dir.glob("LAW_SECTION_TBL_*.lob"))
        print(f"Extracted {lob_count} section content files")
        parse_code(tmp_dir, output_path)
    finally:
        if keep_download:
            print(f"Keeping downloaded and extracted files in {tmp_dir}")
        else:
            print("Cleaning up temporary files...")
            shutil.rmtree(tmp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="output text file path"
    )
    parser.add_argument(
        "--keep-download",
        action="store_true",
        help="keep the temporary ZIP and extracted files",
    )
    args = parser.parse_args()
    download_and_parse(args.output.expanduser().resolve(), args.keep_download)


if __name__ == "__main__":
    main()
