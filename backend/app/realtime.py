"""Process-local compatibility stream until durable events arrive in Phase 10."""

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, case_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.setdefault(case_id, []).append(websocket)

    def disconnect(self, case_id: str, websocket: WebSocket) -> None:
        connections = self.active_connections.get(case_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections:
            self.active_connections.pop(case_id, None)

    async def broadcast_to_case(self, case_id: str, event_type: str, data: dict) -> None:
        for connection in list(self.active_connections.get(case_id, [])):
            try:
                await connection.send_json({"type": event_type, "data": data})
            except Exception:
                self.disconnect(case_id, connection)


ws_manager = ConnectionManager()
