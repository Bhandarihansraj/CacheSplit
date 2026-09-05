import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
import json

from adapters.postgres_adapter import PostgresCommitStore, Commit


@pytest.fixture
def mock_pool():
    pool = MagicMock()
    conn = AsyncMock()
    
    # Setup the context manager for acquire()
    pool.acquire.return_value.__aenter__.return_value = conn
    
    return pool, conn


@pytest.mark.asyncio
async def test_write_idempotent(mock_pool):
    pool, conn = mock_pool
    store = PostgresCommitStore(pool=pool)
    
    commit = Commit(
        commit_hash="hash123",
        entity_id="entity1",
        version_number=1,
        data={"key": "value"}
    )
    
    result = await store.write(commit)
    
    assert result == "hash123"
    conn.execute.assert_called_once_with(
        """
            INSERT INTO commits (commit_hash, entity_id, version_number, data)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (commit_hash) DO NOTHING
        """,
        "hash123",
        "entity1",
        1,
        json.dumps({"key": "value"})
    )


@pytest.mark.asyncio
async def test_read(mock_pool):
    pool, conn = mock_pool
    store = PostgresCommitStore(pool=pool)
    
    conn.fetchrow.return_value = {
        'commit_hash': 'hash123',
        'entity_id': 'entity1',
        'version_number': 1,
        'data': '{"key": "value"}'
    }
    
    result = await store.read("hash123")
    
    assert result is not None
    assert result.commit_hash == "hash123"
    assert result.entity_id == "entity1"
    assert result.version_number == 1
    assert result.data == {"key": "value"}
    
    conn.fetchrow.assert_called_once()


@pytest.mark.asyncio
async def test_list_history(mock_pool):
    pool, conn = mock_pool
    store = PostgresCommitStore(pool=pool)
    
    conn.fetch.return_value = [
        {
            'commit_hash': 'hash123',
            'entity_id': 'entity1',
            'version_number': 1,
            'data': '{"key": "value"}'
        },
        {
            'commit_hash': 'hash124',
            'entity_id': 'entity1',
            'version_number': 2,
            'data': '{"key": "value2"}'
        }
    ]
    
    commits = await store.list_history("entity1")
    
    assert len(commits) == 2
    assert commits[0].commit_hash == "hash123"
    assert commits[0].version_number == 1
    assert commits[1].commit_hash == "hash124"
    assert commits[1].version_number == 2
    
    conn.fetch.assert_called_once()
