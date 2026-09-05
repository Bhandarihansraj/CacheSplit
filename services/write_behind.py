import asyncio
import logging
from db.database import get_db

logger = logging.getLogger(__name__)

class WriteBehindSync:
    def __init__(self, interval_seconds: int = 10):
        self.interval_seconds = interval_seconds
        self._task = None
        self._running = False

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("WriteBehindSync task started.")

    def stop(self):
        if self._running:
            self._running = False
            if self._task:
                self._task.cancel()
            logger.info("WriteBehindSync task stopped.")

    async def _run_loop(self):
        while self._running:
            try:
                await self._flush_pending_commits()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in WriteBehindSync: {e}")
            
            await asyncio.sleep(self.interval_seconds)

    async def _flush_pending_commits(self):
        try:
            db = get_db()
        except RuntimeError:
            return  # db not initialized yet
            
        async with db.execute("SELECT id, transaction_id, commit_hash FROM commit_log WHERE sync_status = 'pending'") as cursor:
            rows = await cursor.fetchall()
            
        if not rows:
            return

        logger.info(f"WriteBehindSync: Found {len(rows)} pending commits to flush.")
        
        # Mock flushing to external DB
        for row in rows:
            logger.info(f"Flushing commit {row['commit_hash']} (tx: {row['transaction_id']}) to external DB...")
        
        # Update status to flushed
        ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in ids)
        await db.execute(f"UPDATE commit_log SET sync_status = 'flushed' WHERE id IN ({placeholders})", ids)
        await db.commit()
        logger.info(f"WriteBehindSync: Successfully flushed {len(rows)} commits.")

write_behind = WriteBehindSync()
