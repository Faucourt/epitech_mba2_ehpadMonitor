r"""Verify a Wokwi download against the prepared web source files.

Examples (PowerShell):
  python .\output\wokwi-transfert\verify_wokwi_zip.py --entity R002 --zip 'C:\Users\lebre\Downloads\project.zip'
  python .\output\wokwi-transfert\verify_wokwi_zip.py --entity R001 --zip 'project.zip' --allow-r001-original-esp-left

Exit 0: all expected files accepted; 1: comparison failed; 2: invalid input.
No browser or network access. Reports and archive copies stay beside this script
under verified/. All source bytes must match exactly unless CRLF normalization
or the R001 diagram exception is explicitly enabled. Native wokwi-project.txt
metadata is reported as an extra
archive file, but is not an unexpected source file.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import zipfile


ROOT = Path(__file__).resolve().parent
NATIVE_METADATA = {"wokwi-project.txt"}
MAX_ARCHIVE_UNCOMPRESSED = 32 * 1024 * 1024


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def byte_info(data: bytes) -> dict:
    return {"bytes": len(data), "sha256": sha256(data)}


def diagram_without_esp_left(data: bytes) -> tuple[dict, float]:
    diagram = json.loads(data.decode("utf-8-sig"))
    if not isinstance(diagram, dict) or not isinstance(diagram.get("parts"), list):
        raise ValueError("Invalid diagram structure")
    diagram = deepcopy(diagram)
    esp = [part for part in diagram["parts"] if isinstance(part, dict) and part.get("id") == "esp"]
    if len(esp) != 1 or "left" not in esp[0]:
        raise ValueError("Expected exactly one esp part with left position")
    position = esp[0].pop("left")
    if isinstance(position, bool) or not isinstance(position, (int, float)):
        raise ValueError("Invalid esp.left position")
    return diagram, position


def accepts_original_r001_diagram(downloaded: bytes, expected: bytes, original: bytes) -> tuple[bool, dict]:
    """Only formatting and the original esp.left value may differ."""
    try:
        current_shape, current_left = diagram_without_esp_left(downloaded)
        expected_shape, expected_left = diagram_without_esp_left(expected)
        original_shape, original_left = diagram_without_esp_left(original)
    except (ValueError, TypeError, KeyError, UnicodeError):
        return False, {"reason": "invalid_diagram_json"}
    accepted = current_shape == expected_shape == original_shape and current_left == original_left
    return accepted, {
        "reason": "original_esp_left_preserved" if accepted else "diagram_has_other_changes",
        "expected_esp_left": expected_left,
        "original_esp_left": original_left,
        "downloaded_esp_left": current_left,
    }


def read_archive(path: Path) -> tuple[dict[str, bytes], list[str]]:
    with zipfile.ZipFile(path) as archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if sum(info.file_size for info in members) > MAX_ARCHIVE_UNCOMPRESSED:
            raise ValueError("Archive exceeds the 32 MiB uncompressed verification limit")
        counts: dict[str, int] = {}
        contents = {}
        for info in members:
            counts[info.filename] = counts.get(info.filename, 0) + 1
            contents[info.filename] = archive.read(info)
        duplicates = sorted(name for name, count in counts.items() if count > 1)
        return contents, duplicates


def compare(expected: dict[str, bytes], downloaded: dict[str, bytes], duplicates: list[str], original_diagram: bytes | None = None, allow_crlf_normalization: bool = False) -> dict:
    missing = sorted(set(expected) - set(downloaded))
    extra = sorted(set(downloaded) - set(expected))
    unexpected = [name for name in extra if name not in NATIVE_METADATA]
    comparisons = []
    for name in sorted(expected):
        record = {"name": name, "expected": byte_info(expected[name]), "downloaded": None, "accepted": False, "exact_equal": False, "normalized_equal": False}
        if name not in downloaded:
            record["status"] = "missing"
        else:
            record["downloaded"] = byte_info(downloaded[name])
            record["exact_equal"] = expected[name] == downloaded[name]
            record["normalized_equal"] = expected[name].replace(b"\r\n", b"\n") == downloaded[name].replace(b"\r\n", b"\n")
            record["status"] = "exact" if expected[name] == downloaded[name] else "mismatch"
            record["accepted"] = record["status"] == "exact"
            if record["status"] == "mismatch" and allow_crlf_normalization and record["normalized_equal"]:
                record["status"] = "accepted_crlf_normalization"
                record["accepted"] = True
            if record["status"] == "mismatch" and name == "diagram.json" and original_diagram is not None:
                accepted, explanation = accepts_original_r001_diagram(downloaded[name], expected[name], original_diagram)
                record["diagram_exception"] = explanation
                if accepted:
                    record["accepted"] = True
                    record["status"] = "accepted_original_esp_left"
        comparisons.append(record)
    extra_records = [
        {"name": name, **byte_info(downloaded[name]), "classification": "native_wokwi_metadata" if name in NATIVE_METADATA else "unexpected_file"}
        for name in extra
    ]
    mismatches = [record["name"] for record in comparisons if record["status"] == "mismatch"]
    passed = not missing and not unexpected and not duplicates and all(record["accepted"] for record in comparisons)
    return {
        "status": "passed" if passed else "failed",
        "expected_file_count": len(expected),
        "downloaded_file_count": len(downloaded),
        "exact_count": sum(record["status"] == "exact" for record in comparisons),
        "all_exact": all(record["exact_equal"] for record in comparisons),
        "normalized_equal": all(record["normalized_equal"] for record in comparisons),
        "crlf_normalized_count": sum(record["status"] == "accepted_crlf_normalization" for record in comparisons),
        "accepted_exception_count": sum(record["status"] == "accepted_original_esp_left" for record in comparisons),
        "missing_files": missing,
        "extra_files": extra_records,
        "unexpected_files": unexpected,
        "duplicate_archive_entries": duplicates,
        "mismatched_files": mismatches,
        "files": comparisons,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--entity", required=True, help="Entity listed in pages.json, e.g. R001 or entree")
    parser.add_argument("--zip", required=True, type=Path, dest="archive", help="Downloaded ZIP to verify")
    parser.add_argument("--allow-crlf-normalization", action="store_true", help="Accept differences consisting only of CRLF versus LF line endings")
    parser.add_argument("--allow-r001-original-esp-left", action="store_true", help="Allow only R001's original diagram and esp.left displacement")
    parser.add_argument("--r001-original-zip", type=Path, help="Original R001 backup; otherwise locate it in backups/")
    args = parser.parse_args()

    try:
        entities = {item["entity"] for item in json.loads((ROOT / "pages.json").read_text(encoding="utf-8-sig"))}
        if args.entity not in entities:
            raise ValueError("Entity is not listed in pages.json")
        if (args.allow_r001_original_esp_left or args.r001_original_zip) and args.entity != "R001":
            raise ValueError("The original esp.left exception is restricted to R001")
        if args.r001_original_zip and not args.allow_r001_original_esp_left:
            raise ValueError("--r001-original-zip requires --allow-r001-original-esp-left")
        stage = ROOT / "upload" / args.entity
        if not stage.is_dir():
            raise ValueError("Missing prepared entity folder")
        expected = {path.name: path.read_bytes() for path in sorted(stage.iterdir()) if path.is_file()}
        if not expected or "device_config.h" not in expected or "diagram.json" not in expected:
            raise ValueError("Prepared entity folder is incomplete")
        archive_path = args.archive.resolve(strict=True)
        downloaded, duplicates = read_archive(archive_path)
        original_diagram = None
        original_path = None
        if args.allow_r001_original_esp_left:
            matches = [args.r001_original_zip] if args.r001_original_zip else list((ROOT / "backups").glob("EHPAD collectif *R001.zip"))
            if len(matches) != 1:
                raise ValueError("Expected exactly one original R001 backup; specify --r001-original-zip")
            original_path = matches[0].resolve(strict=True)
            original_files, original_duplicates = read_archive(original_path)
            if original_duplicates or "diagram.json" not in original_files:
                raise ValueError("Original R001 backup is ambiguous or lacks diagram.json")
            original_diagram = original_files["diagram.json"]

        result = compare(expected, downloaded, duplicates, original_diagram, args.allow_crlf_normalization)
        archive_digest = sha256(archive_path.read_bytes())
        output = ROOT / "verified"
        output.mkdir(exist_ok=True)
        copy_path = output / f"{args.entity}-download-{archive_digest[:12]}.zip"
        if copy_path.exists():
            if sha256(copy_path.read_bytes()) != archive_digest:
                raise ValueError("Existing archive copy has a conflicting hash")
        else:
            shutil.copyfile(archive_path, copy_path)
        report = {
            "schema_version": 1,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "entity": args.entity,
            "staging_folder": str(stage),
            "downloaded_zip": str(archive_path),
            "archive_copy": str(copy_path),
            "zip_sha256": archive_digest,
            "policy": {
                "source_files": "exact_bytes_or_crlf_normalization" if args.allow_crlf_normalization else "exact_bytes",
                "crlf_normalization_allowed": args.allow_crlf_normalization,
                "r001_original_esp_left_allowed": args.allow_r001_original_esp_left,
                "original_diagram_backup": str(original_path) if original_path else None,
                "recognized_native_metadata": sorted(NATIVE_METADATA),
            },
            **result,
        }
        report_path = output / f"{args.entity}-full-comparison.json"
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        summary = {key: report[key] for key in ("entity", "status", "expected_file_count", "exact_count", "all_exact", "normalized_equal", "crlf_normalized_count", "accepted_exception_count", "missing_files", "unexpected_files", "duplicate_archive_entries", "mismatched_files")}
        summary["report"] = str(report_path)
        print(json.dumps(summary, ensure_ascii=True))
        return 0 if result["status"] == "passed" else 1
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
        print(json.dumps({"status": "input_error", "message": str(error)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
