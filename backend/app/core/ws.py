import logging

logger = logging.getLogger("wheelind.ws")


class ConnectionManager:
    def __init__(self):
        self.active: dict[str, set] = {}

    async def connect(self, user_id: str, ws):
        await ws.accept()
        self.active.setdefault(user_id, set()).add(ws)

    def disconnect(self, user_id: str, ws):
        conns = self.active.get(user_id)
        if conns:
            conns.discard(ws)
            if not conns:
                self.active.pop(user_id, None)

    async def send_to_user(self, user_id: str, message: dict):
        for ws in list(self.active.get(user_id, [])):
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001
                self.disconnect(user_id, ws)


manager = ConnectionManager()
