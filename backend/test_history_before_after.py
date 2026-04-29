"""
Test avant/après : compare l'historique simulé vs l'historique InfluxDB réel.
Lance ce script APRÈS que Docker soit démarré et l'injection terminée.

Usage :
  python test_history_before_after.py
"""

import json
import os
import sys

import numpy as np
import redis

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "ehpad_redis_dev_change_me")
INFLUX_HOST = os.getenv("INFLUX_HOST", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "ehpad-super-secret-token")
INFLUX_ORG = os.getenv("INFLUX_ORG", "ehpad")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "residents")
RESIDENT_ID = os.getenv("TEST_RESIDENT", "R005")

SEPARATOR = "-" * 60


def test_avant():
    """Simule ce que retournait history_summary() AVANT (calculé à la volée)."""
    print(f"\n{'='*60}")
    print("AVANT  —  Historique simulé (calculé à la volée)")
    print(f"{'='*60}")

    try:
        from resident_profiles import RESIDENTS_MAP
        from reports import DailyReportService
        from alert_engine import AlertEngine
        from ws_manager import WebSocketManager
        from app.db.redis_client import redis_client as rc

        ws = WebSocketManager()
        ae = AlertEngine(rc, ws)

        svc = DailyReportService(
            redis_client=rc,
            alert_engine=ae,
            residents_map=RESIDENTS_MAP,
            archetypes={},
            effective_resident_profile=lambda rid: RESIDENTS_MAP.get(rid, {}),
            resident_caregiver=lambda rid, s: "soignant_assigné",
            resident_archetype=lambda p: p.get("archetype_id", "ARCH_NUTRITION"),
            influx_query_api=None,  # Pas d'InfluxDB → simulé
            influx_bucket=INFLUX_BUCKET,
        )

        result = svc.history_summary(RESIDENT_ID)
        print(f"Source          : {result.get('source', 'simulé')}")
        print(f"Jours couverts  : {result.get('days')}")
        print(f"Points de données: {result.get('points')}")
        print(f"FC moyenne      : {result.get('avg_vitals', {}).get('heart_rate')} bpm")
        print(f"SpO2 moyenne    : {result.get('avg_vitals', {}).get('spo2')} %")
        print(f"Tendance risque : {result.get('risk_trend')}")
        print(f"Alertes 30j     : {result.get('alerts_count')}")
        print(f"Événements critiques: {len(result.get('critical_events', []))}")
        print(f"\n⚠ Ces données sont RECALCULÉES à chaque appel.")
        print(f"  Le LLM reçoit un contexte identique pour tous les appels.")
        return result
    except Exception as exc:
        print(f"Erreur AVANT : {exc}")
        return {}


def test_apres():
    """Teste ce que retourne history_summary() APRÈS (depuis InfluxDB)."""
    print(f"\n{'='*60}")
    print("APRÈS  —  Historique réel InfluxDB")
    print(f"{'='*60}")

    try:
        from influxdb_client import InfluxDBClient
        from history_injector import get_real_history_summary

        influx = InfluxDBClient(url=INFLUX_HOST, token=INFLUX_TOKEN, org=INFLUX_ORG)
        qa = influx.query_api()

        result = get_real_history_summary(qa, INFLUX_BUCKET, RESIDENT_ID, days=30)

        if result is None:
            print("⚠ Pas encore de données dans InfluxDB.")
            print("  Attends la fin de l'injection au démarrage (~10-30 secondes)")
            print("  puis relance ce test.")
            return {}

        print(f"Source          : {result.get('source')}")
        print(f"Jours couverts  : {result.get('days')}")
        print(f"Points de données: {result.get('points')}")
        print(f"FC moyenne 30j  : {result.get('avg_vitals', {}).get('heart_rate')} bpm")
        print(f"SpO2 moyenne 30j: {result.get('avg_vitals', {}).get('spo2')} %")
        print(f"FC 48h          : {result.get('trends_48h', {}).get('heart_rate')} bpm "
              f"(delta: {result.get('trends_48h', {}).get('heart_rate_delta'):+.1f})")
        print(f"SpO2 48h        : {result.get('trends_48h', {}).get('spo2')} % "
              f"(delta: {result.get('trends_48h', {}).get('spo2_delta'):+.1f})")
        print(f"Tendance FC 48h : {result.get('trends_48h', {}).get('heart_rate_trend')}")
        print(f"Tendance SpO2 48h: {result.get('trends_48h', {}).get('spo2_trend')}")
        print(f"Tendance risque : {result.get('risk_trend')}")
        print(f"Alertes 30j     : {result.get('alerts_count')}")
        print(f"Événements notables: {len(result.get('notable_events', []))}")

        notables = result.get('notable_events', [])
        if notables:
            print(f"\nDerniers événements notables :")
            for ev in notables[-3:]:
                print(f"  {ev.get('time', '')[:10]}  {ev.get('event')}  niveau {ev.get('alert_level')}")

        print(f"\n✓ Ces données viennent d'InfluxDB — VRAIES et persistantes.")
        print(f"  Le LLM reçoit un contexte personnalisé avec tendances réelles.")
        return result
    except Exception as exc:
        print(f"Erreur APRÈS : {exc}")
        import traceback
        traceback.print_exc()
        return {}


def compare(avant, apres):
    if not avant or not apres:
        return
    print(f"\n{'='*60}")
    print("COMPARAISON — Ce que le LLM reçoit maintenant en plus")
    print(f"{'='*60}")

    av = avant.get("avg_vitals", {})
    ap = apres.get("avg_vitals", {})
    t = apres.get("trends_48h", {})

    print(f"\nFC moyenne  : {av.get('heart_rate')} bpm  →  {ap.get('heart_rate')} bpm (30j réel)")
    print(f"SpO2 moyenne: {av.get('spo2')} %     →  {ap.get('spo2')} % (30j réel)")
    print(f"\nNOUVEAU — Tendances 48h (absent avant) :")
    print(f"  FC 48h   : {t.get('heart_rate')} bpm  (delta {t.get('heart_rate_delta'):+.1f})  →  {t.get('heart_rate_trend')}")
    print(f"  SpO2 48h : {t.get('spo2')} %    (delta {t.get('spo2_delta'):+.1f})   →  {t.get('spo2_trend')}")
    print(f"\nNOUVEAU — Événements réels dans le contexte LLM :")
    for ev in apres.get("notable_events", [])[-3:]:
        print(f"  {ev.get('time', '')[:10]}  {ev.get('event')}  niveau {ev.get('alert_level')}")

    print(f"\n→ Le LLM peut maintenant dire :")
    hr_trend = t.get('heart_rate_trend', 'stable')
    if hr_trend == "hausse":
        print(f"  'FC en hausse de {t.get('heart_rate_delta'):+.0f} bpm sur 48h vs moyenne 30j — à surveiller'")
    elif hr_trend == "baisse":
        print(f"  'FC en baisse de {t.get('heart_rate_delta'):+.0f} bpm sur 48h — stabilisation'")
    else:
        print(f"  'FC stable sur 48h par rapport aux 30 derniers jours'")


if __name__ == "__main__":
    avant = test_avant()
    apres = test_apres()
    compare(avant, apres)
    print(f"\n{'='*60}\n")
