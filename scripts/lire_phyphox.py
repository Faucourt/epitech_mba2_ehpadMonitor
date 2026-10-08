"""Analyse pedagogique de CSV phyphox; ne modifie jamais les fichiers bruts."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

G = 9.80665
SEUIL_CHUTE_G = 2.5


def lire_csv_phyphox(chemin):
    source = pd.read_csv(chemin, sep=None, engine="python")
    if source.shape[1] < 4:
        raise ValueError("Au moins quatre colonnes attendues : temps, x, y, z")
    df = source.iloc[:, :4].copy()
    df.columns = ["t", "ax", "ay", "az"]
    for col in df:
        df[col] = pd.to_numeric(df[col].astype(str).str.replace(",", ".", regex=False), errors="raise")
    if len(df) < 2 or not np.isfinite(df.to_numpy()).all():
        raise ValueError("Donnees insuffisantes ou non finies")
    if (df.t.diff().dropna() <= 0).any():
        raise ValueError("Temps non strictement croissants")
    return df


def analyser(df):
    norme = np.linalg.norm(df[["ax", "ay", "az"]], axis=1) / G
    return {
        "duree_s": round(float(df.t.iloc[-1] - df.t.iloc[0]), 3),
        "nb_echantillons": len(df),
        "frequence_hz": round(float(1 / df.t.diff().median()), 2),
        "norme_mediane_g": round(float(np.median(norme)), 4),
        "norme_min_g": round(float(norme.min()), 4),
        "norme_max_g": round(float(norme.max()), 4),
        "t_pic_s": round(float(df.t.iloc[norme.argmax()]), 4),
        "echantillons_au_dessus_du_seuil": int((norme > SEUIL_CHUTE_G).sum()),
    }


def tracer(df, titre, sortie):
    fig, (haut, bas) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for axe in ["ax", "ay", "az"]:
        haut.plot(df.t, df[axe], label=axe, linewidth=0.7)
    haut.set(title=titre, ylabel="Acceleration (m/s2)")
    haut.legend()
    bas.plot(df.t, np.linalg.norm(df[["ax", "ay", "az"]], axis=1) / G, color="black", linewidth=0.7)
    bas.axhline(SEUIL_CHUTE_G, color="red", linestyle="--", label="Seuil 2.5 g")
    bas.set(xlabel="Temps depuis le debut de la mesure (s)", ylabel="Norme (g)")
    bas.legend()
    fig.tight_layout()
    sortie.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(sortie, dpi=140)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--sortie", type=Path, default=Path(__file__).resolve().parents[1] / "docs/figures/phyphox")
    args = parser.parse_args()
    data = lire_csv_phyphox(args.csv)
    print(json.dumps(analyser(data), ensure_ascii=False, indent=2))
    tracer(data, args.csv.stem, args.sortie / (args.csv.stem + ".png"))
