"""Rebuild the local link index from saved browser work and verified downloads."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import zipfile
from checkpoint_wokwi import atomic_text, checkpoint, publication_lock

ROOT = Path(__file__).resolve().parent
URL = re.compile(r"https://wokwi\.com/projects/[0-9]+")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    originals = read_json(ROOT / "pages.json")
    publications = {}
    logs = [ROOT / "online-progress.json", *sorted(ROOT.glob("*-publication-progress.json"))]
    for path in logs:
        if not path.exists():
            continue
        log = read_json(path)
        for record in log.get("projects", []):
            link = record.get("corrected_url", "")
            if record.get("saved") and URL.fullmatch(link):
                publications[record["entity"]] = record

    rows = []
    seen_urls = {}
    for original in originals:
        entity = original["entity"]
        publication = publications.get(entity, {})
        link = publication.get("corrected_url")
        if link:
            if link in seen_urls:
                raise ValueError(f"Shared project URL for {entity} and {seen_urls[link]}")
            seen_urls[link] = entity
        row = dict(original, page_corrigee=link, status="saved_unverified" if link else "not_started")
        report_path = ROOT / "verified" / f"{entity}-full-comparison.json"
        if link and report_path.exists():
            report = read_json(report_path)
            archive = Path(report["archive_copy"])
            with zipfile.ZipFile(archive) as downloaded:
                metadata = downloaded.read("wokwi-project.txt").decode("utf-8-sig")
            source_urls = URL.findall(metadata)
            if report.get("status") == "passed" and source_urls and source_urls[0] == link:
                row.update(status="verified", verification_report=str(report_path),
                           all_files_byte_identical=report["exact_count"] == report["expected_file_count"])
        proof_path = ROOT / f"{entity}-browser-simulation.json"
        row["simulation_observed"] = False
        if proof_path.exists():
            proof = read_json(proof_path)
            devices = proof.get("devices", [])
            row["simulation_observed"] = bool(
                row["status"] == "verified"
                and (proof.get("ready") or proof.get("ready_header_observed"))
                and len(devices) == original["capteurs"]
                and all(name.startswith(entity + "-") for name in devices)
            )
        rows.append(row)

    result = {"updated_at": datetime.now(timezone.utc).isoformat(), "projects": rows}
    atomic_text(ROOT / "pages-corrigees.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    verified = [row for row in rows if row["status"] == "verified"]
    lines = ["PROJETS WOKWI CORRIGÉS", f"{len(verified)} / {len(rows)} sauvegardés et vérifiés par téléchargement.", ""]
    for row in verified:
        validation = "simulation observée" if row["simulation_observed"] else "fichiers vérifiés"
        lines.append(f"{row['entity']} — {row['capteurs']} capteurs — {validation}")
        lines.append(row["page_corrigee"])
        lines.append("")
    atomic_text(ROOT / "LIENS-WOKWI.txt", "\n".join(lines))
    backup = checkpoint(result)
    print(json.dumps({"total": len(rows), "saved": len(publications), "verified": len(verified),
                      "simulation_observed": sum(row["simulation_observed"] for row in rows),
                      "backup": backup["backup"]}))


if __name__ == "__main__":
    with publication_lock():
        main()
