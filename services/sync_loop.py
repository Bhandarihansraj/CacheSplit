"""
CacheSplit v3 — Sync Loop & Cache Expiry
Background task loop that runs every 5 seconds.
"""
import asyncio
import logging
import time
from db.database import get_db

logger = logging.getLogger(__name__)

class SyncLoop:
    def __init__(self):
        self.task = None

    async def _loop(self):
        logger.info("Sync Loop starting...")
        while True:
            try:
                db = get_db()
                now = time.time()
                
                # 1. Clean up expired entities
                try:
                    async with db.execute("DELETE FROM entity_cache WHERE expires_at IS NOT NULL AND expires_at < ?", (now,)) as cursor:
                        if cursor.rowcount > 0:
                            logger.info(f"Sync Loop: Cleaned up {cursor.rowcount} expired entities.")
                    await db.commit()
                except Exception as e:
                    logger.debug(f"Sync Loop: expires_at check failed (maybe column missing): {e}")

                # 2. Simulate eventual consistency
                logger.info("Sync Loop: Checking node versions and pulling missing commits (Simulated).")
                
            except Exception as e:
                logger.error(f"Error in sync loop: {e}")
            
            await asyncio.sleep(5)

    def start(self):
        if self.task is None:
            self.task = asyncio.create_task(self._loop())
            logger.info("Sync loop started.")

    def stop(self):
        if self.task:
            self.task.cancel()
            self.task = None
            logger.info("Sync loop stopped.")

sync_loop = SyncLoop()
