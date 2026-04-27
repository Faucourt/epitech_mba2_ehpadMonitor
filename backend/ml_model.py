"""
Modèle ML de prédiction de malaise.
Prédit le risque de malaise dans les 30-60 min à venir.
Entraîné sur données synthétiques, mis à jour en continu avec les données réelles.
"""

import numpy as np
import logging
import os
import joblib
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    accuracy_score, roc_auc_score, f1_score,
    confusion_matrix, recall_score, precision_score
)
from collections import deque

log = logging.getLogger(__name__)
MODEL_PATH = "/app/ml_model.joblib"


def generate_training_data(n_samples=5000):
    """Génère des données synthétiques réalistes pour l'entraînement initial."""
    np.random.seed(42)
    X, y = [], []

    for _ in range(n_samples):
        # Paramètres de base normaux
        hr = np.random.normal(72, 10)
        spo2 = np.random.normal(96, 2)
        bp = np.random.normal(135, 20)
        temp = np.random.normal(36.7, 0.4)
        last_mv = np.random.exponential(600)
        hr_trend = np.random.normal(0, 2)     # variation FC sur 10 min
        spo2_trend = np.random.normal(0, 0.5)
        age_factor = np.random.uniform(0.5, 1.0)
        risk_factor = np.random.uniform(0, 1)

        # Label : malaise probable si combinaison de signaux précoces
        malaise_prob = 0.0
        if spo2 < 94: malaise_prob += 0.3
        if hr > 100:  malaise_prob += 0.2
        if hr < 50:   malaise_prob += 0.25
        if bp > 170:  malaise_prob += 0.2
        if bp < 85:   malaise_prob += 0.3
        if temp > 38.5: malaise_prob += 0.15
        if last_mv > 3600: malaise_prob += 0.2
        if hr_trend > 5: malaise_prob += 0.15
        if spo2_trend < -1: malaise_prob += 0.2
        malaise_prob *= (0.5 + 0.5 * risk_factor) * (0.5 + 0.5 * age_factor)

        label = 1 if malaise_prob > 0.4 else 0

        X.append([hr, spo2, bp, temp, last_mv, hr_trend, spo2_trend, age_factor, risk_factor])
        y.append(label)

    return np.array(X), np.array(y)


class MalaisePredictor:
    """Modèle ML pour prédire le risque de malaise."""

    FEATURE_NAMES = [
        "heart_rate", "spo2", "blood_pressure_sys", "temperature",
        "last_movement_ago_s", "hr_trend_10m", "spo2_trend_10m",
        "age_factor", "risk_factor"
    ]

    def __init__(self):
        self.model = None
        self.metrics: dict = {}
        self.history: dict[str, deque] = {}  # resident_id → dernières 10 mesures
        self._load_or_train()

    def _load_or_train(self):
        if os.path.exists(MODEL_PATH):
            try:
                self.model = joblib.load(MODEL_PATH)
                log.info("Modèle ML chargé depuis le disque")
                return
            except Exception as e:
                log.warning(f"Erreur chargement modèle: {e}, réentraînement...")

        log.info("Entraînement du modèle ML initial...")
        X, y = generate_training_data()
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        self.model = Pipeline([
            ("scaler", StandardScaler()),
            ("clf", GradientBoostingClassifier(
                n_estimators=100,
                learning_rate=0.1,
                max_depth=4,
                random_state=42
            ))
        ])
        self.model.fit(X_train, y_train)
        joblib.dump(self.model, MODEL_PATH)

        y_pred = self.model.predict(X_test)
        y_proba = self.model.predict_proba(X_test)[:, 1]

        tn, fp, fn, tp = confusion_matrix(y_test, y_pred).ravel()
        sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0.0  # recall classe 1
        specificity = tn / (tn + fp) if (tn + fp) > 0 else 0.0  # recall classe 0

        clf = self.model.named_steps["clf"]
        feature_importance = {
            name: round(float(imp), 4)
            for name, imp in zip(self.FEATURE_NAMES, clf.feature_importances_)
        }

        self.metrics = {
            "accuracy": round(float(accuracy_score(y_test, y_pred)), 4),
            "auc": round(float(roc_auc_score(y_test, y_proba)), 4),
            "f1": round(float(f1_score(y_test, y_pred)), 4),
            "precision": round(float(precision_score(y_test, y_pred)), 4),
            "sensitivity": round(float(sensitivity), 4),
            "specificity": round(float(specificity), 4),
            "train_samples": len(X_train),
            "test_samples": len(X_test),
            "positive_rate": round(float(y.mean()), 4),
            "confusion_matrix": {"tn": int(tn), "fp": int(fp), "fn": int(fn), "tp": int(tp)},
            "feature_importance": feature_importance,
            "algorithm": "GradientBoostingClassifier",
            "features": self.FEATURE_NAMES,
            # Note: split aléatoire (non temporel) — acceptable pour données synthétiques i.i.d.
            # En production, utiliser un split temporel pour éviter le data leakage.
            "split_note": "random split on synthetic i.i.d. data — use temporal split on real data",
        }
        log.info(
            f"Modèle entraîné — accuracy={self.metrics['accuracy']:.1%} "
            f"AUC={self.metrics['auc']:.3f} F1={self.metrics['f1']:.3f} "
            f"sensitivity={self.metrics['sensitivity']:.1%} specificity={self.metrics['specificity']:.1%}"
        )

    def _get_trends(self, resident_id: str, current: dict) -> tuple:
        """Calcule les tendances sur les 10 dernières mesures."""
        if resident_id not in self.history:
            self.history[resident_id] = deque(maxlen=10)

        hist = self.history[resident_id]
        hist.append(current)

        if len(hist) < 3:
            return 0.0, 0.0

        hrs = [h["heart_rate"] for h in hist]
        spo2s = [h["spo2"] for h in hist]

        # Tendance linéaire simple
        x = np.arange(len(hrs))
        hr_trend = float(np.polyfit(x, hrs, 1)[0]) if len(hrs) > 1 else 0.0
        spo2_trend = float(np.polyfit(x, spo2s, 1)[0]) if len(spo2s) > 1 else 0.0

        return hr_trend, spo2_trend

    def predict(self, resident_id: str, vitals: dict, movement: dict,
                age: int, base_risk: float) -> float:
        """
        Retourne un score de risque entre 0.0 et 1.0.
        0.0 = aucun risque, 1.0 = malaise imminent.
        """
        v = vitals
        hr = v.get("heart_rate", 72)
        spo2 = v.get("spo2", 96)
        bp = v.get("blood_pressure_sys", 130)
        temp = v.get("temperature", 36.7)
        last_mv = movement.get("last_movement_ago_s", 0)

        hr_trend, spo2_trend = self._get_trends(resident_id, {
            "heart_rate": hr, "spo2": spo2
        })

        age_factor = min(1.0, (age - 60) / 40) if age > 60 else 0.0

        features = np.array([[
            hr, spo2, bp, temp, last_mv,
            hr_trend, spo2_trend,
            age_factor, base_risk
        ]])

        try:
            proba = self.model.predict_proba(features)[0][1]
            return float(proba)
        except Exception as e:
            log.error(f"Erreur prédiction ML: {e}")
            return 0.0
