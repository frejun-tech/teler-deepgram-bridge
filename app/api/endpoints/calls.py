import json
import asyncio
import logging
import time

import websockets
from fastapi import (APIRouter, HTTPException, WebSocket, status)
from fastapi.responses import JSONResponse
from fastapi.websockets import WebSocketDisconnect, WebSocketState
from pydantic import BaseModel

from app.core.config import settings
from app.utils.teler_to_deepgram import teler_to_deepgram
from app.utils.deepgram_to_teler import deepgram_to_teler
from app.utils.teler_client import TelerClient

logger = logging.getLogger(__name__)
router = APIRouter()

class CallFlowRequest(BaseModel):
    call_id: str
    account_id: str
    from_number: str
    to_number: str

class CallRequest(BaseModel):
    from_number: str
    to_number: str

@router.get("/")
async def root():
    return {"message": "Welcome to the Teler-deepgram bridge"}

@router.post("/flow", status_code=status.HTTP_200_OK, include_in_schema=False)
async def stream_flow(payload: CallFlowRequest):
    """
    Return stream flow as JSON Response containing websocket url to connect
    """
    ws_url = f"wss://{settings.SERVER_DOMAIN}/api/v1/calls/media-stream"
    stream_flow = {
        "action": "stream",
        "ws_url": ws_url,
        "chunk_size": 800,
        "sample_rate": "8k",  
        "record": True
    }
    return JSONResponse(stream_flow)

@router.post("/initiate-call", status_code=status.HTTP_200_OK)
async def initiate_call(call_request: CallRequest):
    """
    Initiate a call using Teler SDK.
    """
    try:
        if not settings.DEEPGRAM_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="deepgram_API_KEY not configured"
            )
        teler_client = TelerClient(api_key=settings.TELER_API_KEY)
        call = await teler_client.create_call(
            from_number=call_request.from_number,
            to_number=call_request.to_number,
            flow_url=f"https://{settings.SERVER_DOMAIN}/api/v1/calls/flow",
            status_callback_url=f"https://{settings.SERVER_DOMAIN}/api/v1/webhooks/receiver",
            record=True,
        )
        logger.info(f"Call created: {call}")
        return JSONResponse(content={"success": True, "call_id": call.id})
    except Exception as e:
        logger.error(f"Failed to create call: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, 
            detail="Call creation failed."
        )

@router.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    """
    Handle received and sent audio chunks, Teler -> Deepgram, Deepgram -> Teler
    """
    await websocket.accept()
    logger.info("Web Socket Connected")

    deepgram_ws = None  

    try:
        if not settings.DEEPGRAM_API_KEY:
            await websocket.close(code=1008, reason="DEEPGRAM API KEY not configured")
            return

        async with websockets.connect(
            settings.DEEPGRAM_WS_URL,
            additional_headers={"Authorization": f"Token {settings.DEEPGRAM_API_KEY}"}
        ) as deepgram_ws:
            logger.info("[media-stream] Successfully connected to Deepgram WebSocket")

            last_keepalive_time = time.time()

            agent_settings = {
                "type": "Settings",
                "audio": {
                    "input": {"encoding": "linear16", "sample_rate": 8000},
                    "output": {"encoding": "linear16", "sample_rate":8000, "container": "none"}
                },
                "agent": {
                    "language": "en",
                    "speak": {"provider": {"type": "deepgram", "model": "aura-2-odysseus-en"}},
                    "listen": {"provider": {"type": "deepgram", "model": "nova-3"}},
                    "think": {
                        "provider": {"type": "google", "model": "gemini-2.5-flash"},
                        "prompt": "#Role\nYou are a general-purpose virtual assistant speaking to users over the phone..."
                    },
                    "greeting": "Hello! How may I help you?"
                }
            }

            await deepgram_ws.send(json.dumps(agent_settings))

            while True:
                response_data = json.loads(await deepgram_ws.recv())
                logger.debug(f"[media-stream][deepgram] Deepgram response: {json.dumps(response_data, indent=2)}")

                if response_data.get('type') == 'SettingsApplied':
                    logger.info(f"[media-stream][deepgram] Settings Applied")
                    break
                
                elif response_data.get('type') == 'Error':
                    logger.info(f"[media-stream][deepgram] Error from Deepgram: {response_data}")
                else:
                    logger.info(f"[media-stream][deepgram] Received event: {response_data.get('type')}")

            if time.time() - last_keepalive_time > 8:
                await deepgram_ws.send(json.dumps({"type": "KeepAlive"}))
                last_keepalive_time = time.time()

            recv_task = asyncio.create_task(
                teler_to_deepgram(deepgram_ws, websocket), 
                name="teler_to_deepgram"
            )
            send_task = asyncio.create_task(
                deepgram_to_teler(deepgram_ws, websocket),
                name="deepgram_to_teler"
            )

            try:
                done, pending = await asyncio.wait(
                    [recv_task, send_task],
                    return_when=asyncio.FIRST_COMPLETED  
                )

                for task in done:
                    if task.exception():
                        logger.error(f"Task {task.get_name()} failed: {task.exception()}")
                    else:
                        logger.debug(f"Task {task.get_name()} completed successfully")

                for task in pending:
                    logger.debug(f"Canceling task {task.get_name()}")
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            except Exception as e:
                logger.error(f"Error in task handling: {type(e).__name__}: {e}")


    except WebSocketDisconnect:
        logger.info("[media-stream] Teler WebSocket disconnected — closing Deepgram connection...")
        if deepgram_ws and not deepgram_ws.closed:
            await deepgram_ws.close()
            logger.info("[media-stream] Deepgram connection closed after Teler disconnect")

    except websockets.exceptions.InvalidStatusCode as e:
        logger.error(f"[media-stream] WebSocket connection failed with status {e.status_code}: {e}")
        if e.status_code == 403:
            logger.error("[media-stream] Invalid API key or permission issue.")
    except Exception as e:
        logger.error(f"[media-stream] Top-level error: {type(e).__name__}: {e}")
    finally:
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close()
        logger.info("[media-stream] Connection closed.")
