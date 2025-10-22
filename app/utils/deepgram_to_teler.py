import json
import base64
import logging
from fastapi import WebSocket
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

async def deepgram_to_teler(deepgram_ws, websocket: WebSocket):
    """
    Receive 8 kHz PCM Linear16 from Deepgram and forward to Teler as base64-encoded audio chunks.
    """
    audio_buffer = b""
    chunk_id = 0
    CHUNK_BUFFER_SIZE = 8000

    try:
        async for message in deepgram_ws:
            try:
                if isinstance(message, bytes):
                    audio_buffer += message
                    logger.debug(f"[deepgram] Received {len(message)} bytes, buffer={len(audio_buffer)}")

                    if len(audio_buffer) >= CHUNK_BUFFER_SIZE:
                        audio_b64 = base64.b64encode(audio_buffer).decode("utf-8")

                        await websocket.send_json({
                            "type": "audio",
                            "audio_b64": audio_b64,
                            "chunk_id": chunk_id
                        })
                        logger.debug(f"[deepgram] Sent chunk {chunk_id} ({len(audio_buffer)} bytes)")
                        chunk_id += 1

                        audio_buffer = b""

                else:
                    try:
                        message_json = json.loads(message)
                    except json.JSONDecodeError:
                        logger.warning(f"Non-JSON message: {message}")
                        continue

                    msg_type = message_json.get("type")
                    if msg_type == "UserStartedSpeaking":
                        audio_buffer = b""
                        await websocket.send_json({"type": "clear"})
                    elif msg_type == "ConversationText":
                        role = message_json.get("role")
                        content = message_json.get("content")
                        logger.debug(f"{role.capitalize()} Conversation: {content}")
                    elif msg_type == "Warning":
                        logger.debug(f"Agent Warning: {message_json.get('description')}")
                    elif msg_type == "Error":
                        logger.error(f"Deepgram Error: {message_json}")
                    else:
                        logger.debug(f"Message: {message_json}")

            except Exception as e:
                logger.error(f"[deepgram] Error processing message: {type(e).__name__}: {e}")

    except ConnectionClosed:
        logger.info("Deepgram WebSocket disconnected")
    finally:
        if audio_buffer:
            audio_b64 = base64.b64encode(audio_buffer).decode("utf-8")
            await websocket.send_json({
                "type": "audio",
                "audio_b64": audio_b64,
                "chunk_id": chunk_id
            })
            logger.debug(f"[deepgram] Sent final chunk {chunk_id} ({len(audio_buffer)} bytes)")
            audio_buffer =  b""

        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close()
        try:
            await deepgram_ws.close()
        except Exception as e:
            logger.error(f"Error closing Deepgram WebSocket: {type(e).__name__}: {e}")
        logger.info("deepgram_to_teler task ended")
