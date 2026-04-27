"""
Gestionnaire WebSocket pour la mise à jour temps réel du dashboard.
"""

import json
import logging
from typing import Set
from fastapi import WebSocket

log = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        self.connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.add(ws)
        log.info(f"Dashboard connecté ({len(self.connections)} connexions actives)")

    def disconnect(self, ws: WebSocket):
        self.connections.discard(ws)
        log.info(f"Dashboard déconnecté ({len(self.connections)} connexions actives)")

    async def broadcast(self, message: dict):
        if not self.connections:
            return
        data = json.dumps(message)
        dead = set()
        for ws in self.connections:
            try:
                await ws.send_text(data)
            except Exception:
                dead.add(ws)
        self.connections -= dead

    async def send_alert(self, alert: dict):
        await self.broadcast({"type": "alert", "data": alert})

    async def send_state_update(self, state: dict):
        await self.broadcast({"type": "resident_update", "data": state})

    async def send_summary(self, summary: dict):
        await self.broadcast({"type": "summary", "data": summary})
