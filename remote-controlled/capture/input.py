import asyncio
import json
from pynput import mouse, keyboard

from utils.logger import logger


class InputHandler:
    def __init__(self):
        self.mouse_controller = mouse.Controller()
        self.keyboard_controller = keyboard.Controller()
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self, queue: asyncio.Queue):
        self._queue = queue
        self._running = True
        self._task = asyncio.create_task(self._process_loop())
        logger.info("Input handler started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Input handler stopped")

    async def _process_loop(self):
        while self._running:
            try:
                message = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                await self._handle_message(message)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Input handling error: {e}")

    async def _handle_message(self, message: dict):
        action = message.get("action")
        data = message.get("data", {})
        
        try:
            screen_width, screen_height = self._get_screen_size()
            
            if action == "mousemove":
                rel_x = data.get("x", 0)
                rel_y = data.get("y", 0)
                x = int(rel_x * screen_width)
                y = int(rel_y * screen_height)
                self.mouse_controller.position = (x, y)
            
            elif action == "mousedown":
                button = data.get("button", "left")
                btn = mouse.Button.left if button == "left" else mouse.Button.right
                rel_x = data.get("x", 0)
                rel_y = data.get("y", 0)
                x = int(rel_x * screen_width)
                y = int(rel_y * screen_height)
                self.mouse_controller.position = (x, y)
                self.mouse_controller.press(btn)
            
            elif action == "mouseup":
                button = data.get("button", "left")
                btn = mouse.Button.left if button == "left" else mouse.Button.right
                rel_x = data.get("x", 0)
                rel_y = data.get("y", 0)
                x = int(rel_x * screen_width)
                y = int(rel_y * screen_height)
                self.mouse_controller.position = (x, y)
                self.mouse_controller.release(btn)
            
            elif action == "mousewheel":
                dx = data.get("dx", 0)
                dy = data.get("dy", 0)
                self.mouse_controller.scroll(dx, dy)
            
            elif action == "keydown":
                key = data.get("key")
                if key:
                    self._press_key(key)
            
            elif action == "keyup":
                key = data.get("key")
                if key:
                    self._release_key(key)
            
            elif action == "keypress":
                key = data.get("key")
                if key:
                    self._press_key(key)
                    self._release_key(key)
            
            else:
                logger.warning(f"Unknown input action: {action}")
        
        except Exception as e:
            logger.error(f"Failed to handle input {action}: {e}")

    def _press_key(self, key_str: str):
        key = self._parse_key(key_str)
        if key:
            self.keyboard_controller.press(key)

    def _release_key(self, key_str: str):
        key = self._parse_key(key_str)
        if key:
            self.keyboard_controller.release(key)

    def _get_screen_size(self):
        import ctypes
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

    def _parse_key(self, key_str: str):
        special_keys = {
            "enter": keyboard.Key.enter,
            "escape": keyboard.Key.esc,
            "tab": keyboard.Key.tab,
            "space": keyboard.Key.space,
            "backspace": keyboard.Key.backspace,
            "delete": keyboard.Key.delete,
            "up": keyboard.Key.up,
            "down": keyboard.Key.down,
            "left": keyboard.Key.left,
            "right": keyboard.Key.right,
            "shift": keyboard.Key.shift,
            "ctrl": keyboard.Key.ctrl,
            "alt": keyboard.Key.alt,
            "cmd": keyboard.Key.cmd,
            "win": keyboard.Key.cmd,
            "f1": keyboard.Key.f1,
            "f2": keyboard.Key.f2,
            "f3": keyboard.Key.f3,
            "f4": keyboard.Key.f4,
            "f5": keyboard.Key.f5,
            "f6": keyboard.Key.f6,
            "f7": keyboard.Key.f7,
            "f8": keyboard.Key.f8,
            "f9": keyboard.Key.f9,
            "f10": keyboard.Key.f10,
            "f11": keyboard.Key.f11,
            "f12": keyboard.Key.f12,
            "home": keyboard.Key.home,
            "end": keyboard.Key.end,
            "pageup": keyboard.Key.page_up,
            "pagedown": keyboard.Key.page_down,
            "insert": keyboard.Key.insert,
            "capslock": keyboard.Key.caps_lock,
            "numlock": keyboard.Key.num_lock,
            "scrolllock": keyboard.Key.scroll_lock,
        }
        
        key_lower = key_str.lower()
        if key_lower in special_keys:
            return special_keys[key_lower]
        
        if len(key_str) == 1:
            return key_str
        
        return None