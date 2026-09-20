import aiohttp

from utils.logger import logger


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{bot_token}"

    async def send(self, message: str):
        try:
            connector = aiohttp.TCPConnector(ssl=False)
            async with aiohttp.ClientSession(connector=connector) as session:
                payload = {
                    "chat_id": self.chat_id,
                    "text": message,
                    "parse_mode": "Markdown",
                }
                async with session.post(
                    f"{self.api_url}/sendMessage", json=payload
                ) as resp:
                    if resp.status == 200:
                        logger.info("Telegram message sent")
                    else:
                        text = await resp.text()
                        logger.error(f"Telegram failed: {resp.status} - {text}")
        except Exception as e:
            logger.error(f"Telegram error: {e}")
