import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    mqtt_host: str = field(default_factory=lambda: os.getenv("MQTT_HOST", "localhost"))
    mqtt_port: int = field(default_factory=lambda: int(os.getenv("MQTT_PORT", "1883")))
    mqtt_username: str = field(default_factory=lambda: os.getenv("MQTT_USERNAME", ""))
    mqtt_password: str = field(default_factory=lambda: os.getenv("MQTT_PASSWORD", ""))

    redis_host: str = field(default_factory=lambda: os.getenv("REDIS_HOST", "localhost"))
    redis_port: int = field(default_factory=lambda: int(os.getenv("REDIS_PORT", "6379")))
    redis_password: str = field(default_factory=lambda: os.getenv("REDIS_PASSWORD", ""))

    influx_host: str = field(default_factory=lambda: os.getenv("INFLUX_HOST", "http://localhost:8086"))
    influx_token: str = field(default_factory=lambda: os.getenv("INFLUX_TOKEN", "ehpad-super-secret-token"))
    influx_org: str = field(default_factory=lambda: os.getenv("INFLUX_ORG", "ehpad"))
    influx_bucket: str = field(default_factory=lambda: os.getenv("INFLUX_BUCKET", "residents"))

    demo_resident: str = field(default_factory=lambda: os.getenv("DEMO_RESIDENT", "R005"))
    influx_sample_interval_s: float = field(default_factory=lambda: float(os.getenv("INFLUX_SAMPLE_INTERVAL_S", "5")))
    ws_resident_min_interval_s: float = field(default_factory=lambda: float(os.getenv("WS_RESIDENT_MIN_INTERVAL_S", "2")))

    ollama_host: str = field(default_factory=lambda: os.getenv("OLLAMA_HOST", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "meditron:7b"))
    llm_daily_auto_enabled: bool = field(default_factory=lambda: os.getenv("LLM_DAILY_AUTO_ENABLED", "true").lower() not in {"0", "false", "no"})
    llm_daily_ttl_days: int = field(default_factory=lambda: int(os.getenv("LLM_DAILY_TTL_DAYS", "45")))

    famille_admin_token: str = field(default_factory=lambda: os.getenv("FAMILLE_ADMIN_TOKEN", "ADMIN_EHPAD_2024"))
    session_secret: str = field(default_factory=lambda: os.getenv("SESSION_SECRET", "dev-change-me-session-secret"))
    staff_demo_password: str = field(default_factory=lambda: os.getenv("STAFF_DEMO_PASSWORD", "EHPAD2024!"))
    allowed_origins: list[str] = field(default_factory=lambda: _env_list("ALLOWED_ORIGINS", "http://localhost:3002,http://127.0.0.1:3002"))
    https_required: bool = field(default_factory=lambda: _env_bool("HTTPS_REQUIRED", False))
    retention_access_log_days: int = field(default_factory=lambda: int(os.getenv("RETENTION_ACCESS_LOG_DAYS", "365")))
    retention_audit_days: int = field(default_factory=lambda: int(os.getenv("RETENTION_AUDIT_DAYS", "365")))
    patient_data_dir: Path = field(default_factory=lambda: Path(os.getenv("PATIENT_DATA_DIR", "/app/data/patients")))

    vapid_public_key: str = field(default_factory=lambda: os.getenv("VAPID_PUBLIC_KEY", ""))
    vapid_private_key: str = field(default_factory=lambda: os.getenv("VAPID_PRIVATE_KEY", ""))
    vapid_claims_email: str = field(default_factory=lambda: os.getenv("VAPID_CLAIMS_EMAIL", "admin@ehpad.local"))

    @property
    def webpush_enabled(self) -> bool:
        return bool(self.vapid_public_key and self.vapid_private_key)


settings = Settings()
