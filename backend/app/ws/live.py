"""Live telemetry over WebSocket: the compact greenhouse state pushed a few times per second."""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()


@router.websocket("/ws/live")
async def live(ws: WebSocket) -> None:
    await ws.accept()
    svc = ws.app.state.service
    period = 1 / ws.app.state.settings.ws_rate_hz
    try:
        while True:
            await ws.send_json(svc.live())
            await asyncio.sleep(period)
    except (WebSocketDisconnect, RuntimeError):
        return
