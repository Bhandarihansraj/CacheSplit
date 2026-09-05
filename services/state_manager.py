import asyncio
import json
import logging
from typing import Dict, List
from fastapi import WebSocket

logger = logging.getLogger("state_manager")

class WebSocketStateManager:
    """
    Manages active WebSocket sessions for real-time dashboard updates.
    Broadcasts cache invalidations and node state changes.
    """
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket connected. Total active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"WebSocket disconnected. Total active: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast JSON message to all connected clients."""
        if not self.active_connections:
            return
            
        payload = json.dumps(message)
        failed = []
        for connection in self.active_connections:
            try:
                await connection.send_text(payload)
            except Exception as e:
                logger.warning(f"Error broadcasting to WS client: {e}")
                failed.append(connection)
                
        # Cleanup broken connections
        for conn in failed:
            self.disconnect(conn)

# Singleton
state_manager = WebSocketStateManager()
