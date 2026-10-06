"""Persist a resumable Wokwi checkpoint and a checked rolling backup archive."""
from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
BACKUPS = ROOT.parent / "sauvegardes-wokwi"


@contextmanager
def publication_lock():
    with (ROOT / ".checkpoint.lock").open("a+b") as stream:
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


def atomic_text(path, text):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def checkpoint(index=None):
    index = index or read_json(ROOT / "pages-corrigees.json")
    now = datetime.now(timezone.utc).isoformat()
    rows = index["projects"]
    verified = [r for r in rows if r["status"] == "verified"]
    pending = [r for r in rows if r["status"] == "saved_unverified"]
    remaining = [r for r in rows if r["status"] == "not_started"]
    activity_path = ROOT / "reprise-activite.json"
    activity = read_json(activity_path) if activity_path.exists() else {}
    drafts = []
    for path in sorted(ROOT.glob("*-publication-progress.json")):
        log = read_json(path)
        if log.get("draft") or log.get("current_entity"):
            drafts.append({"journal": path.name, "draft": log.get("draft"),
                           "current_entity": log.get("current_entity")})
    state = {"verified": [(r["entity"], r["page_corrigee"]) for r in verified],
             "pending_verification": [(r["entity"], r["page_corrigee"]) for r in pending],
             "not_started": [r["entity"] for r in remaining], "activity": activity,
             "drafts": drafts}
    fingerprint = hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    last_path = ROOT / "REPRISE-WOKWI.json"
    previous = read_json(last_path) if last_path.exists() else {}
    result = {"updated_at_utc": now, "fingerprint": fingerprint, "total": len(rows),
              "saved_count": len(verified) + len(pending), "verified_count": len(verified),
              "state": state, "projects": rows}
    atomic_text(last_path, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    lines = ["REPRISE DU TRANSFERT WOKWI", "Dernière mise à jour UTC : " + now, "",
             "Objectif : terminer les 45 projets (25 résidents, 20 zones, 437 capteurs prévus).",
             "L'utilisateur a demandé de terminer, puis de garder cet historique en cas d'arrêt du PC.",
             f"Enregistrés en ligne : {result['saved_count']}/45. Sources téléchargées et vérifiées : {len(verified)}/45.",
             "Simulations observées : " + ", ".join(r["entity"] for r in rows if r.get("simulation_observed")) + ".", "",
             "A REPRENDRE", "Copies enregistrées dont les corrections ou contrôles restent à terminer : " + (", ".join(r["entity"] for r in pending) or "aucune"),
             "Copies restantes : " + (", ".join(r["entity"] for r in remaining) or "aucune"),
             "Dernier point de travail : " + activity.get("description", "Consulter les journaux de publication."),
             "Ce point décrit le dernier état connu ; après redémarrage, réobserver Chrome avant toute saisie.", "",
             "PROCEDURE POUR LE PROCHAIN AGENT",
             "1. Lire REPRISE-WOKWI.json, pages-corrigees.json et les journaux *-publication-progress.json.",
             "2. Les projets verified sont déjà finis : ne pas les recréer. Utiliser leurs liens ci-dessous.",
             "3. Lire d'abord la phase du journal : une URL avec copy_created=true désigne une copie à réutiliser, même si saved=false et si elle n'est pas encore dans l'index. Terminer les corrections, enregistrer, télécharger son ZIP puis tout contrôler.",
             "4. Un brouillon non enregistré peut avoir disparu : repartir d'une copie sauvegardée et réappliquer les fichiers du dossier upload/<entity>.",
             "5. Achever les résidents, puis suivre zone-publication-plan.json pour les 20 zones.",
             "6. Ne jamais enregistrer la configuration d'une autre entité sur la copie servant de modèle : utiliser Save a copy.",
             "7. Utiliser le contrôle Chrome autorisé, un seul opérateur à la fois. Arrêter les entrées si l'outil signale un arrêt de politique ou du contrôle utilisateur.",
             "8. Vérifier chaque ZIP avec verify_wokwi_zip.py puis actualiser refresh_publication_index.py.",
             "Les écarts CRLF/LF sont admis ; R001 seul conserve son ancien placement ESP32. Aucune autre différence de source n'est admise.",
             "Le ZIP natif doit contenir l'URL correspondant à la copie vérifiée.",
             "Les trois modèles résidents ont été simulés ; les clones sont vérifiés par comparaison des sources, sans prétendre avoir tous été simulés.",
             "La passerelle UART locale reste nécessaire pour envoyer les données au dashboard.", "",
             "FICHIERS UTILES",
             "LIENS-WOKWI.txt : liens des copies vérifiées.",
             "upload/ : les 733 fichiers web corrigés, pour 45 projets, avec manifeste.",
             "45-projets-wokwi-corriges.zip : paquet de sources préparé avant publication.",
             "verified/ : archives téléchargées et rapports de comparaison.",
             "HISTORIQUE-WOKWI.jsonl : jalons horodatés depuis la demande de sauvegarde.",
             "../sauvegardes-wokwi/WOKWI-REPRISE-DERNIERE.zip : sauvegarde locale complète de ce dossier.", "",
             "LIENS ENREGISTRES"]
    for row in rows:
        if row.get("page_corrigee"):
            label = "vérifié" if row["status"] == "verified" else "corrections ou contrôle à terminer"
            lines.append(f"{row['entity']} — {label} — {row['page_corrigee']}")
    atomic_text(ROOT / "REPRISE-WOKWI.txt", "\n".join(lines) + "\n")
    if previous.get("fingerprint") != fingerprint:
        with (ROOT / "HISTORIQUE-WOKWI.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({k: v for k, v in result.items() if k != "projects"}, ensure_ascii=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    BACKUPS.mkdir(parents=True, exist_ok=True)
    destination = BACKUPS / "WOKWI-REPRISE-DERNIERE.zip"
    temporary = BACKUPS / "WOKWI-REPRISE-DERNIERE.zip.tmp"
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith((".tmp", ".lock")):
                archive.write(path, Path("wokwi-transfert") / path.relative_to(ROOT))
    with zipfile.ZipFile(temporary) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError("Corrupt backup member: " + bad)
        archived_state = json.loads(archive.read("wokwi-transfert/REPRISE-WOKWI.json"))
        if archived_state["fingerprint"] != fingerprint:
            raise ValueError("Checkpoint mismatch in backup")
    with temporary.open("r+b") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    atomic_text(BACKUPS / "WOKWI-REPRISE-DERNIERE.sha256", digest + "  " + destination.name + "\n")
    atomic_text(ROOT.parent.parent / "REPRENDRE-WOKWI.txt",
                "Pour reprendre le transfert Wokwi après arrêt du PC, lire :\n"
                + str(ROOT / "REPRISE-WOKWI.txt") + "\n\nSauvegarde locale :\n" + str(destination) + "\n")
    return {"backup": str(destination), "saved": result["saved_count"], "verified": len(verified), "sha256": digest}


if __name__ == "__main__":
    with publication_lock():
        print(json.dumps(checkpoint(), ensure_ascii=False))
