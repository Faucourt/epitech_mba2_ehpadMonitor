"""
Benchmark de scalabilite pour la soutenance.

Usage conseille depuis Docker Compose:
  docker compose run --rm --no-deps backend python benchmark_scalability.py --target-mps 120 --duration-s 60
  docker compose run --rm --no-deps backend python benchmark_scalability.py --target-mps 300 --duration-s 60 --residents 50

Le script publie des messages MQTT au format du simulateur, interroge l'API et
sort une preuve JSON: debit envoye, debit observe par le backend, latence API
p95/p99 et fraicheur des etats residents.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
import time
from datetime import datetime, timezone
from typing import Any

import httpx
import paho.mqtt.client as mqtt


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, math.ceil((pct / 100) * len(ordered)) - 1))
    return round(ordered[idx], 2)


def make_state(resident_index: int, sequence: int) -> dict[str, Any]:
    rid = f"R{resident_index:03d}"
    phase = (sequence + resident_index) % 17
    hr = 72 + (phase % 5)
    spo2 = 96.5 - ((phase % 3) * 0.2)
    bp_sys = 128 + (phase % 7)
    bp_dia = 74 + (phase % 4)
    timestamp = utc_now()
    room = 100 + resident_index
    floor = 0 if resident_index <= 12 else 1
    zone = f"ch{room}"
    return {
        "resident_id": rid,
        "name": f"Resident Benchmark {resident_index:03d}",
        "room": str(room),
        "floor": floor,
        "zone": zone,
        "current_zone": zone,
        "target_zone": zone,
        "position": {"x": float(resident_index % 10), "z": float(resident_index // 10), "floor": floor},
        "activity": "benchmark_scalability",
        "timestamp": timestamp,
        "timestamp_real": timestamp,
        "benchmark_run": True,
        "sensor_events": {
            "wearable": {"status": "active", "quality_pct": 98, "battery_pct": 91}
        },
        "sensor_health": [
            {
                "id": f"{rid}-wearable",
                "type": "wearable",
                "status": "active",
                "quality_pct": 98,
                "battery_pct": 91,
                "updated_at": timestamp,
            }
        ],
        "vitals": {
            "heart_rate": hr,
            "spo2": round(spo2, 1),
            "blood_pressure_sys": bp_sys,
            "blood_pressure_dia": bp_dia,
            "temperature": 36.7,
            "respiratory_rate": 16,
            "ecg_rhythm": "sinus",
        },
        "movement": {
            "accel_magnitude": round(random.uniform(0.02, 0.09), 3),
            "gyro_magnitude_dps": round(random.uniform(0.5, 3.0), 1),
            "altitude_drop_cm": 0,
            "is_fall_detected": False,
            "ambient_fall_confirmed": False,
            "last_movement_ago_s": random.randint(5, 90),
            "is_sleeping": False,
            "sos_pressed": False,
        },
        "life_profile": {"period": "benchmark", "label": "Benchmark charge"},
        "routine_context": {"period": "benchmark", "label": "Benchmark charge"},
        "routine_label": "Benchmark charge",
        "time_of_day": 1.0,
        "time_label": "benchmark",
        "care_level": "benchmark",
        "meal_mode": "standard",
        "caregiver": "chef_garde",
    }


def timed_get(client: httpx.Client, url: str, latencies_ms: list[float]) -> dict[str, Any] | None:
    started = time.perf_counter()
    try:
        response = client.get(url)
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies_ms.append(elapsed_ms)
        response.raise_for_status()
        return response.json()
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies_ms.append(elapsed_ms)
        return None


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    api_latencies_ms: list[float] = []
    api_client = httpx.Client(base_url=args.api_url, timeout=args.api_timeout_s)

    before = timed_get(api_client, "/api/ops/scalability", api_latencies_ms) or {}

    mqtt_client = mqtt.Client(client_id=f"ehpad-benchmark-{int(time.time())}", clean_session=True)
    mqtt_client.username_pw_set(args.mqtt_username, args.mqtt_password)
    mqtt_client.connect(args.mqtt_host, args.mqtt_port, keepalive=30)
    mqtt_client.loop_start()

    sent = 0
    publish_errors = 0
    api_samples: list[dict[str, Any]] = []
    started = time.perf_counter()
    next_tick = started
    next_api_probe = started
    sequence = 0

    try:
        while True:
            now = time.perf_counter()
            elapsed = now - started
            if elapsed >= args.duration_s:
                break

            expected_sent = int(elapsed * args.target_mps)
            batch = max(0, expected_sent - sent)
            for _ in range(batch):
                sequence += 1
                resident_index = ((sequence - 1) % args.residents) + 1
                state = make_state(resident_index, sequence)
                topic = f"ehpad/residents/{state['resident_id']}/vitals"
                info = mqtt_client.publish(topic, json.dumps(state), qos=args.qos)
                if info.rc == mqtt.MQTT_ERR_SUCCESS:
                    sent += 1
                else:
                    publish_errors += 1

            if now >= next_api_probe:
                sample = timed_get(api_client, "/api/ops/scalability", api_latencies_ms)
                if sample:
                    api_samples.append(sample)
                timed_get(api_client, "/health", api_latencies_ms)
                timed_get(api_client, "/api/residents", api_latencies_ms)
                next_api_probe = now + args.api_probe_interval_s

            next_tick += 0.01
            time.sleep(max(0.001, next_tick - time.perf_counter()))
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()

    time.sleep(args.settle_s)
    after = timed_get(api_client, "/api/ops/scalability", api_latencies_ms) or {}
    api_client.close()

    duration_real = time.perf_counter() - started
    before_total = ((before.get("mqtt") or {}).get("messages_total") or 0)
    after_total = ((after.get("mqtt") or {}).get("messages_total") or 0)
    observed_delta = max(0, after_total - before_total)

    return {
        "benchmark": {
            "target_messages_per_second": args.target_mps,
            "duration_s": args.duration_s,
            "residents": args.residents,
            "qos": args.qos,
            "sent_messages": sent,
            "publish_errors": publish_errors,
            "actual_sent_messages_per_second": round(sent / max(duration_real, 0.001), 2),
            "backend_observed_delta_messages": observed_delta,
            "backend_observed_messages_per_second": round(observed_delta / max(duration_real, 0.001), 2),
        },
        "api_latency_ms": {
            "samples": len(api_latencies_ms),
            "avg": round(statistics.mean(api_latencies_ms), 2) if api_latencies_ms else None,
            "p95": percentile(api_latencies_ms, 95),
            "p99": percentile(api_latencies_ms, 99),
            "max": round(max(api_latencies_ms), 2) if api_latencies_ms else None,
        },
        "backend_before": before,
        "backend_after": after,
        "interpretation": {
            "ok_for_jury": (
                publish_errors == 0
                and observed_delta >= int(sent * 0.90)
                and (percentile(api_latencies_ms, 95) or 999999) < args.max_p95_ms
            ),
            "criteria": [
                "publish_errors == 0",
                "backend_observed_delta >= 90% des messages envoyes",
                f"api_latency_p95 < {args.max_p95_ms} ms",
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark MQTT/API EHPAD")
    parser.add_argument("--target-mps", type=int, default=120, help="messages MQTT par seconde a envoyer")
    parser.add_argument("--duration-s", type=int, default=60, help="duree du test")
    parser.add_argument("--residents", type=int, default=25, help="nombre de residents virtuels")
    parser.add_argument("--qos", type=int, choices=[0, 1, 2], default=1, help="QoS MQTT")
    parser.add_argument("--mqtt-host", default="mosquitto")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-username", default="simulator")
    parser.add_argument("--mqtt-password", default="simulator_demo_pwd")
    parser.add_argument("--api-url", default="http://backend:8000")
    parser.add_argument("--api-timeout-s", type=float, default=5.0)
    parser.add_argument("--api-probe-interval-s", type=float, default=1.0)
    parser.add_argument("--settle-s", type=float, default=2.0, help="attente apres publication avant mesure finale")
    parser.add_argument("--max-p95-ms", type=float, default=500.0)
    args = parser.parse_args()

    result = run_benchmark(args)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
