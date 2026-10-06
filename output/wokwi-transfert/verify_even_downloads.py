"""One-shot verification of newly downloaded resident Wokwi archives.

Default group is even; use --group other-residents for the second resident batch.
Writes only that group's verification-progress.json and verified/ artifacts.
Never edits online-progress.json and never operates a browser.
"""

from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parent
DOWNLOADS = Path("C:/Users/lebre/Downloads")
GROUPS = {
    "even": [f"R{index:03d}" for index in range(4, 25, 2)],
    "other-residents": ["R011", "R013", "R015", "R017", "R019", "R021", "R023", "R003", "R005", "R007", "R025"],
    "zone": ["entree", "hors_ehpad", "infirmerie_rdc", "pharmacie_admin", "couloir_principal", "salle_commune", "patio", "jardin", "salle_activites", "salle_manger", "office_cuisine", "couloir_aile_rdc", "escalier", "ascenseur", "poste_infirmier_etage", "kinesitherapie", "salle_repos", "couloir_aile_a_etage", "couloir_aile_b_etage", "palier_etage"],
}


def publication_records(value, entities):
    records = {}
    if isinstance(value, dict):
        if value.get("entity") in entities:
            records[value["entity"]] = value
        for child in value.values():
            records.update(publication_records(child, entities))
    elif isinstance(value, list):
        for child in value:
            records.update(publication_records(child, entities))
    return records


def main(group="even"):
    entities = GROUPS[group]
    summary_path = ROOT / f"{group}-verification-progress.json"
    previous = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    records = {item["entity"]: item for item in previous.get("projects", [])}
    publication_path = ROOT / f"{group}-publication-progress.json"
    publications = {}
    if publication_path.exists():
        for attempt in range(2):
            try:
                publications = publication_records(json.loads(publication_path.read_text(encoding="utf-8-sig")), entities)
                break
            except (ValueError, OSError):
                if attempt == 0:
                    time.sleep(0.2)
                else:
                    print(json.dumps({"status": "publisher_file_being_written", "new_results": []}))
                    return  # Retry on the next invocation; do not report incomplete state.
    changes = []
    for entity in entities:
        publication = publications.get(entity, {})
        reported_url = publication.get("corrected_url") or publication.get("project_url") or publication.get("url")
        if not reported_url:
            continue
        candidates = sorted(DOWNLOADS.glob(f"*{entity}*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
        archive = None
        metadata_url = None
        for candidate in candidates:
            try:
                with zipfile.ZipFile(candidate) as z:
                    if "wokwi-project.txt" not in z.namelist():
                        continue
                    urls = re.findall(r"https://wokwi\.com/projects/\d+", z.read("wokwi-project.txt").decode("utf-8-sig"))
                    if len(set(urls)) == 1 and urls[0] == reported_url:
                        archive, metadata_url = candidate, urls[0]
                        break
            except (OSError, ValueError, UnicodeError, zipfile.BadZipFile):
                continue
        if archive is None:
            continue
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if records.get(entity, {}).get("zip_sha256") == digest:
            continue
        completed = subprocess.run(
            [sys.executable, str(ROOT / "verify_wokwi_zip.py"), "--entity", entity, "--zip", str(archive), "--allow-crlf-normalization"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )
        if completed.returncode == 2:
            changes.append({"entity": entity, "status": "input_error", "verifier_output": completed.stderr.strip()})
            continue
        report_path = ROOT / "verified" / f"{entity}-full-comparison.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        metadata_matches_publication = metadata_url == reported_url if reported_url else None
        status = report["status"]
        if metadata_matches_publication is False:
            status = "publication_url_mismatch"
        record = {
            "entity": entity,
            "status": status,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "downloaded_project_url": metadata_url,
            "publisher_project_url": reported_url,
            "metadata_matches_publication": metadata_matches_publication,
            "saved_sources_verified": report["status"] == "passed" and metadata_url is not None,
            "simulation_status": "not_checked",
            "zip_sha256": digest,
            "zip_path": report["archive_copy"],
            "report_path": str(report_path),
            "files_verified": report["expected_file_count"],
            "all_exact": report["all_exact"],
            "normalized_equal": report["normalized_equal"],
            "normalized_files": [item["name"] for item in report["files"] if item["status"] == "accepted_crlf_normalization"],
            "missing_files": report["missing_files"],
            "unexpected_files": report["unexpected_files"],
            "mismatched_files": report["mismatched_files"],
        }
        records[entity] = record
        changes.append({key: record[key] for key in ("entity", "status", "downloaded_project_url", "files_verified", "all_exact", "normalized_equal", "missing_files", "unexpected_files", "mismatched_files")})
    passed = [entity for entity in entities if records.get(entity, {}).get("status") == "passed"]
    summary = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Saved source contents only; no new simulation verification",
        "expected_entities": entities,
        "verified_count": len(passed),
        "pending_entities": [entity for entity in entities if entity not in passed],
        "projects": [records[entity] for entity in entities if entity in records],
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"group": group, "verified_count": len(passed), "pending_count": len(entities) - len(passed), "new_results": changes}, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=sorted(GROUPS), default="even")
    main(parser.parse_args().group)
