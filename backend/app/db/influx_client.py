from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS

from app.core.config import settings


influx = InfluxDBClient(
    url=settings.influx_host,
    token=settings.influx_token,
    org=settings.influx_org,
)
write_api = influx.write_api(write_options=SYNCHRONOUS)
query_api = influx.query_api()
