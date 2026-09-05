import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
import asyncpg

from .interface import CommitStore


@dataclass
class Commit:
    commit_hash: str
    entity_id: str
    version_number: int
    data: Dict[str, Any]


class PostgresCommitStore(CommitStore):
    """
    Postgres adapter for CommitStore using asyncpg for connection pooling.
    """

    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    async def write(self, commit: Commit) -> str:
        """
        Write a commit to the store idempotently.
        """
        query = """
            INSERT INTO commits (commit_hash, entity_id, version_number, data)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (commit_hash) DO NOTHING
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                query,
                commit.commit_hash,
                commit.entity_id,
                commit.version_number,
                json.dumps(commit.data)
            )
        return commit.commit_hash

    async def read(self, commit_hash: str) -> Optional[Commit]:
        """
        Read a commit by its hash.
        """
        query = """
            SELECT commit_hash, entity_id, version_number, data
            FROM commits
            WHERE commit_hash = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, commit_hash)
            if row:
                return Commit(
                    commit_hash=row['commit_hash'],
                    entity_id=row['entity_id'],
                    version_number=row['version_number'],
                    data=json.loads(row['data']) if isinstance(row['data'], str) else row['data']
                )
        return None

    async def list_history(self, entity_id: str) -> List[Commit]:
        """
        List the commit history for an entity, ordered by version_number ASC.
        """
        query = """
            SELECT commit_hash, entity_id, version_number, data
            FROM commits
            WHERE entity_id = $1
            ORDER BY version_number ASC
        """
        commits = []
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query, entity_id)
            for row in rows:
                commits.append(
                    Commit(
                        commit_hash=row['commit_hash'],
                        entity_id=row['entity_id'],
                        version_number=row['version_number'],
                        data=json.loads(row['data']) if isinstance(row['data'], str) else row['data']
                    )
                )
        return commits
