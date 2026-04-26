"""
실시간 상태/세그먼트 WebSocket.
150ms 주기로 현재 레벨/큐 깊이 + 새로 완성된 발화 카드를 푸시.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import live_session

router = APIRouter()


@router.websocket("/ws/live")
async def ws_live(ws: WebSocket) -> None:
    await ws.accept()
    last_seg_id = 0
    try:
        while True:
            active = live_session.get_active()
            if active is None:
                await ws.send_text(json.dumps({"active": False}))
            else:
                state = active.get_state()
                new_segments = active.get_segments_since(last_seg_id)
                if new_segments:
                    last_seg_id = max(s["id"] for s in new_segments)
                payload = {
                    "active": True,
                    "elapsed_sec": state["elapsed_sec"],
                    "rms_db": state["rms_db"],
                    "audio_queue_depth": state["audio_queue_depth"],
                    "speech_queue_depth": state["speech_queue_depth"],
                    "dropped_blocks": state["dropped_blocks"],
                    "segments_count": state["segments_count"],
                    "new_segments": new_segments,
                }
                await ws.send_text(json.dumps(payload, ensure_ascii=False))
            await asyncio.sleep(0.15)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await ws.close()
        except Exception:
            pass
        return
