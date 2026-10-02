"""Read-only acquisition endpoints; hardware access uses existing staff sessions."""
from fastapi import HTTPException, Header

def register_hardware_routes(app, store, require_staff):
 def check(source, authorization):
  if source not in {'wokwi','hardware'}:raise HTTPException(400,'Source inconnue')
  if source=='hardware':require_staff(authorization)

 @app.get('/api/hardware/snapshot')
 def snapshot(source: str='wokwi', authorization: str=Header(None)):
  check(source,authorization)
  return store.snapshot(source)

 @app.get('/api/hardware/history/{device_id}')
 def history(device_id: str, source: str='wokwi', authorization: str=Header(None)):
  check(source,authorization)
  if device_id not in store.devices:raise HTTPException(404,'Équipement inconnu')
  return {'device_id':device_id,'source':source,'history':store.device_history(device_id,source)}
