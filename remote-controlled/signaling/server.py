import asyncio
import uuid
from aiohttp import web, WSMsgType

from utils.logger import logger
from signaling.protocol import (
    SignalMessage,
    MessageType,
    create_answer_message,
    create_ice_message,
    create_error_message,
    create_ready_message,
)


class SignalingServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080, path: str = "/ws"):
        self.host = host
        self.port = port
        self.path = path
        self.app = web.Application()
        self._setup_routes()
        
        self._controller_ws: web.WebSocketResponse | None = None
        self._controller_id: str | None = None
        self._pending_ice: list[SignalMessage] = []
        self._offer_event: asyncio.Event = asyncio.Event()
        self._offer_sdp: str | None = None

    @web.middleware
    async def _cors_middleware(self, request, handler):
        # Skip CORS for WebSocket upgrade requests
        if request.headers.get("Upgrade", "").lower() == "websocket":
            return await handler(request)
            
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)
        
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    async def _root_handler(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "service": "remote-controlled signaling"})

    def _setup_routes(self):
        self.app.router.add_get(self.path, self._websocket_handler)
        self.app.router.add_post("/offer", self._handle_offer)
        self.app.router.add_post("/answer", self._handle_answer)
        self.app.router.add_post("/ice", self._handle_ice_rest)
        self.app.router.add_get("/health", self._health_check)
        self.app.router.add_get("/", self._root_handler)
        
        # Add CORS middleware
        self.app.middlewares.append(self._cors_middleware)

    async def _health_check(self, request: web.Request) -> web.Response:
        logger.debug(f"Health check from {request.remote}")
        return web.json_response({"status": "ok", "controller_connected": self._controller_ws is not None})

    async def _websocket_handler(self, request: web.Request) -> web.WebSocketResponse:
        logger.info(f"WebSocket upgrade request from {request.remote}")
        ws = web.WebSocketResponse()
        try:
            await ws.prepare(request)
        except Exception as e:
            logger.error(f"WebSocket prepare failed: {e}")
            raise
        
        client_id = str(uuid.uuid4())[:8]
        logger.info(f"WebSocket connected: {client_id}")
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_ws_message(ws, client_id, msg.data)
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"WebSocket error: {ws.exception()}")
        finally:
            if self._controller_ws == ws:
                self._controller_ws = None
                self._controller_id = None
                self._offer_event.clear()
                self._offer_sdp = None
            logger.info(f"WebSocket disconnected: {client_id}")
        
        return ws

    async def _handle_ws_message(self, ws: web.WebSocketResponse, client_id: str, data: str):
        logger.debug(f"Raw WS message from {client_id}: {data[:200]}")
        try:
            message = SignalMessage.from_json(data)
        except Exception as e:
            logger.warning(f"Invalid message from {client_id}: {e}")
            return

        if message.type == MessageType.OFFER:
            await self._handle_offer_ws(ws, client_id, message)
        elif message.type == MessageType.ANSWER:
            await self._handle_answer_ws(client_id, message)
        elif message.type == MessageType.ICE_CANDIDATE:
            logger.info(f"Parsed ICE candidate: {message.payload}")
            await self._handle_ice_ws(client_id, message)
        elif message.type == MessageType.CONTROL:
            await self._handle_control(client_id, message)
        else:
            logger.warning(f"Unknown message type: {message.type}")

    async def _handle_offer_ws(self, ws: web.WebSocketResponse, client_id: str, message: SignalMessage):
        if self._controller_ws and self._controller_ws != ws:
            await ws.send_str(create_error_message("Another controller is connected").to_json())
            return
        
        self._controller_ws = ws
        self._controller_id = client_id
        self._offer_sdp = message.payload["sdp"]
        self._offer_event.set()
        
        await ws.send_str(create_ready_message(client_id).to_json())
        logger.info(f"Controller registered: {client_id}")

    async def _handle_answer_ws(self, client_id: str, message: SignalMessage):
        pass

    async def _handle_ice_ws(self, client_id: str, message: SignalMessage):
        if self._controller_ws is None:
            return
        logger.debug(f"Received ICE from {client_id}: {message.payload}")
        self._pending_ice.append(message)

    async def _handle_control(self, client_id: str, message: SignalMessage):
        pass

    async def _handle_offer(self, request: web.Request) -> web.Response:
        try:
            data = await request.json()
            sdp = data.get("sdp")
            if not sdp:
                return web.json_response({"error": "Missing sdp"}, status=400)
            
            self._offer_sdp = sdp
            self._offer_event.set()
            return web.json_response({"status": "ok"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def _handle_answer(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def _handle_ice_rest(self, request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    async def wait_for_offer(self, timeout: float = 30.0) -> str | None:
        try:
            await asyncio.wait_for(self._offer_event.wait(), timeout=timeout)
            return self._offer_sdp
        except asyncio.TimeoutError:
            return None

    def get_pending_ice(self) -> list[SignalMessage]:
        ice = self._pending_ice.copy()
        self._pending_ice.clear()
        logger.debug(f"Returning {len(ice)} pending ICE candidates")
        for msg in ice:
            logger.debug(f"  ICE payload: {msg.payload}")
        return ice

    def has_controller(self) -> bool:
        return self._controller_ws is not None and not self._controller_ws.closed

    def reset_state(self):
        self._pending_ice.clear()
        self._offer_sdp = None
        self._offer_event.clear()

    async def send_answer(self, sdp: str):
        if self._controller_ws and not self._controller_ws.closed:
            await self._controller_ws.send_str(create_answer_message(sdp, self._controller_id).to_json())

    async def send_ice_candidate(self, candidate: str, sdp_mid: str, sdp_mline_index: int):
        if self._controller_ws and not self._controller_ws.closed:
            await self._controller_ws.send_str(
                create_ice_message(candidate, sdp_mid, sdp_mline_index, self._controller_id).to_json()
            )

    async def send_control(self, action: str, data: dict):
        if self._controller_ws and not self._controller_ws.closed:
            from signaling.protocol import create_control_message
            await self._controller_ws.send_str(create_control_message(action, data, self._controller_id).to_json())

    async def start(self):
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, self.host, self.port)
        await site.start()
        logger.info(f"Signaling server started on http://{self.host}:{self.port}{self.path}")

    async def stop(self):
        if self._controller_ws:
            await self._controller_ws.close()
        if hasattr(self, 'runner'):
            await self.runner.cleanup()