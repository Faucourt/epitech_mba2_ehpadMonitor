"""Reference hardware, never inferred measurements. Shared by export and validation."""
CATALOG = {
    "mpu6050": {"model": "MPU-6050", "bus": "I2C 0x68", "native": "wokwi-mpu6050", "fields": {"accel_g": "g", "gyro_dps": "deg/s", "impact": "bool"}},
    "max30102": {"model": "MAX30102", "bus": "I2C 0x57", "chip": "max30102", "fields": {"heart_rate": "bpm", "spo2": "%", "ir_raw": "count", "red_raw": "count"}},
    "tmp117": {"model": "TMP117", "bus": "I2C 0x48", "chip": "tmp117", "fields": {"contact_temperature_c": "°C"}},
    "sos": {"model": "Bouton SOS NO", "bus": "GPIO 27 pull-up", "native": "wokwi-pushbutton", "fields": {"sos_pressed": "bool"}},
    "pir": {"model": "HC-SR501", "bus": "GPIO 27", "native": "wokwi-pir-motion-sensor", "fields": {"motion": "bool"}},
    "door": {"model": "Contact sec NC / reed", "bus": "GPIO 27 pull-up", "native": "wokwi-slide-switch", "fields": {"door_open": "bool"}},
    "hx711": {"model": "HX711 + cellule de charge", "bus": "DOUT 26 / SCK 25", "native": "wokwi-hx711", "fields": {"load_raw": "count", "load_kg": "kg"}},
    "radar": {"model": "HLK-LD2410 OUT", "bus": "GPIO 27", "chip": "digital-presence", "fields": {"presence": "bool"}, "limit": "Sortie présence seulement : ne prouve ni chute ni immobilité au sol."},
    "scd41": {"model": "SCD41", "bus": "I2C 0x62", "chip": "scd41", "fields": {"co2_ppm": "ppm", "temperature_c": "°C", "humidity_pct": "%"}},
    "dht22": {"model": "DHT22", "bus": "GPIO 27", "native": "wokwi-dht22", "fields": {"temperature_c": "°C", "humidity_pct": "%"}},
    "sgp30": {"model": "SGP30", "bus": "I2C 0x58", "chip": "sgp30", "fields": {"tvoc_ppb": "ppb", "eco2_ppm": "ppm"}, "limit": "eCO2 estimé distinct du CO2 mesuré ; aucun VOC index inventé."},
    "mq2": {"model": "MQ-2", "bus": "ADC1 GPIO 34", "native": "wokwi-gas-sensor", "fields": {"gas_adc": "count"}, "limit": "Signal brut, préchauffage et calibration requis ; ni fumée ppm ni CO ppm déduits."},
    "ze07co": {"model": "ZE07-CO", "bus": "UART RX16 TX17 9600", "chip": "ze07co", "fields": {"co_ppm": "ppm"}},
    "sound": {"model": "DFRobot SEN0232", "bus": "ADC1 GPIO 34", "chip": "sound-level", "fields": {"sound_db": "dBA", "sound_mv": "mV"}, "limit": "Conversion constructeur 50 dBA/V ; vérifier référence ADC et étalonnage."},
    "sgp40": {"model": "SGP40 + algorithme Sensirion", "bus": "I2C 0x59", "chip": "sgp40", "fields": {"voc_raw": "ticks", "voc_index": "index"}, "limit": "Apprentissage à 1 Hz ; index indisponible pendant le démarrage. Compensation nominale 25 °C / 50 % HR."},
    "ecg": {"model": "AD8232", "bus": "ADC1 GPIO34, LO+32 LO-33", "chip": "analog-signal", "fields": {"ecg_mv": "mV", "leads_off": "bool"}, "limit": "Échantillon brut seulement ; aucune classification sinus/FA."},
    "respiration": {"model": "Ceinture analogique conditionnée 0–3,3 V", "bus": "ADC1 GPIO 34", "chip": "analog-signal", "fields": {"respiration_mv": "mV", "respiratory_rate": "breaths/min"}, "limit": "Estimation par franchissements avec hystérésis ; capteur et seuils à calibrer."},
    "amg8833": {"model": "AMG8833", "bus": "I2C 0x69", "chip": "amg8833", "fields": {"thermal_pixels_c": "°C[64]", "thermal_max_c": "°C"}},
    "gps": {"model": "GNSS NMEA 0183 (NEO-6M)", "bus": "UART RX16 TX17 9600", "chip": "gps-nmea", "fields": {"latitude": "deg", "longitude": "deg", "gps_fix": "bool"}},
    "rfid": {"model": "MFRC522", "bus": "SPI SCK18 MISO19 MOSI23 SS5 RST22", "native": "wokwi-mfrc522", "fields": {"tag_uid": "hex"}},
    "ble": {"model": "ESP32 BLE scanner", "bus": "Radio BLE / injection I2C Wokwi", "chip": "ble-fixture", "fields": {"ble_address": "MAC", "ble_rssi_dbm": "dBm"}, "limit": "Wokwi ne simule pas la radio BLE. Adaptateur de test I2C ; compilation matérielle utilise BLEDevice."},
    "nibp": {"model": "PAR NIBP2010 / NIBP2020 UP sans SpO2", "bus": "UART RX16 TX17 4800 ; START27 / STOP26", "chip": "par-nibp", "fields": {"blood_pressure_sys": "mmHg", "blood_pressure_dia": "mmHg"}, "limit": "Protocole constructeur rev. 2.12. Un cycle adulte manuel par bouton. Interface physique TTL 5 V à adapter vers 3,3 V (ou transceiver RS232 selon variante). Pneumatique et matériel non validés par Wokwi."},
}

WEARABLE = ["mpu6050", "max30102", "tmp117", "sos", "ecg", "respiration", "nibp"]
ALIASES = {
    "wearable": WEARABLE, "pir": ["pir"], "sdb_pir": ["pir"],
    "radar": ["radar"], "radar_mmwave": ["radar"], "matelas": ["hx711"],
    "porte": ["door"], "rfid": ["rfid"], "badge": ["rfid"], "rfid_sortie": ["rfid"],
    "ir": ["pir"], "presence": ["pir"], "gps_bracelet": ["gps"],
    "sol_intelligent": ["hx711"], "sol_capteur": ["hx711"], "sol": ["hx711"],
    "co2": ["scd41"], "son": ["sound"], "camera_thermique": ["amg8833"],
    "ambiant": ["dht22", "sgp40"], "fumee": ["mq2"], "temperature": ["dht22"],
    "co": ["ze07co"], "ble_beacon": ["ble"],
}
SOFTWARE = {"dashboard", "alertes_5_niveaux", "dashboard_central", "surveillance_etage", "alerte_fugue"}
