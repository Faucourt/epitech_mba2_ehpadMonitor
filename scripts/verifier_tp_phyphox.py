"""Verifie le livrable local et recalcule les controles complementaires."""
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
from lire_phyphox import G, analyser, lire_csv_phyphox, tracer

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/phyphox"
PROCESSED = ROOT / "data/processed/phyphox"


def main():
    records = json.loads((PROCESSED / "qualite.json").read_text(encoding="utf-8"))
    datasets = {}
    checks = []
    for record in records:
        path = RAW / record["fichier"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Empreinte differente : {path.name}")
        df = lire_csv_phyphox(path)
        datasets[path.name] = df
        record.update(analyser(df))
        tracer(df, path.stem, ROOT / "docs/figures/phyphox" / (path.stem + ".png"))
        with (RAW / "meta" / path.stem / "device.csv").open(encoding="utf-8-sig") as f:
            metadata = dict(list(csv.reader(f))[1:])
        limit = float(metadata["accelerometer Range"])
        axes = df[["ax", "ay", "az"]].to_numpy()
        check = {
            "fichier": path.name,
            "proche_limite_99pct_par_axe": (np.abs(axes) >= .99 * limit).sum(axis=0).tolist(),
            "limite_par_axe_ms2": limit,
        }
        with (RAW / "meta" / path.stem / "time.csv").open(encoding="utf-8-sig") as f:
            check["horodatages_originaux"] = list(csv.DictReader(f))
        if "marche" in path.name:
            # Interpolation seulement en memoire ; les CSV restent intacts.
            grid = np.arange(1, 29, .02)
            signal = np.interp(grid, df.t, np.linalg.norm(axes, axis=1) / G)
            signal -= signal.mean()
            freq = np.fft.rfftfreq(len(signal), .02)
            power = abs(np.fft.rfft(signal * np.hanning(len(signal)))) ** 2
            candidates = np.flatnonzero((freq >= .5) & (freq <= 3))
            peak = candidates[np.argmax(power[candidates])]
            check["frequence_dominante_marche_hz"] = float(freq[peak])
            check["methode"] = "Norme, 1-29 s, interpolation 50 Hz, Hann, FFT 0.5-3 Hz; pas un comptage valide des pas."
        checks.append(check)
    with (RAW / "labels.csv").open(encoding="utf-8", newline="") as f:
        labels = list(csv.DictReader(f))
    for label in labels:
        df = datasets[label["fichier"]]
        start, end = float(label["t_debut_s"]), float(label["t_fin_s"])
        if not df.t.iloc[0] <= start < end <= df.t.iloc[-1]:
            raise ValueError(f"Annotation hors enregistrement : {label}")
    if list(RAW.rglob("*.png")):
        raise ValueError("Figure presente dans les donnees brutes")
    (PROCESSED / "qualite.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    (PROCESSED / "controles.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"OK : {len(records)} CSV, empreintes intactes, {len(labels)} annotations bornees, figures regenerees.")


if __name__ == "__main__":
    main()
