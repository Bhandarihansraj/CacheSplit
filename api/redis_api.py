"""
api/redis_api.py
FastAPI router exposing unified Redis command execution, key inspection,
TTL expiration management, memory eviction configuration, and store monitoring for CacheSplit.
"""
from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from core.redis_store import (
    EvictionPolicy,
    OOMError,
    RedisError,
    RedisStore,
    RedisType,
    WrongTypeError,
    redis_store,
)

router = APIRouter(prefix="/api/redis", tags=["redis"])


class CommandRequest(BaseModel):
    cmd: str = Field(..., description="Redis command name, e.g. SET, GET, EXPIRE, TTL, HSET, LPUSH, SADD, ZADD")
    args: List[Any] = Field(default_factory=list, description="Arguments for the Redis command")


class ExpireRequest(BaseModel):
    key: str = Field(..., description="Key to set TTL on")
    seconds: float = Field(..., gt=0, description="Expiration time in seconds")


class EvictionConfigRequest(BaseModel):
    max_keys: Optional[int] = Field(default=None, description="Maximum number of keys in store (null for unlimited)")
    policy: Optional[str] = Field(default=None, description="Eviction policy (allkeys-lru, volatile-lru, allkeys-lfu, volatile-lfu, volatile-ttl, noeviction, allkeys-random)")


@router.post("/command")
def execute_redis_command(req: CommandRequest) -> Dict[str, Any]:
    """
    Execute a dynamic Redis-style command against the in-memory RedisStore.
    Supports: SET, GET, INCR, DECR, MSET, MGET, APPEND, STRLEN,
              HSET, HMSET, HGET, HGETALL, HDEL, HEXISTS, HKEYS, HVALS, HLEN, HINCRBY,
              LPUSH, RPUSH, LPOP, RPOP, LRANGE, LLEN, LINDEX, LTRIM,
              SADD, SMEMBERS, SREM, SISMEMBER, SCARD, SINTER, SUNION, SDIFF,
              ZADD, ZRANGE, ZREVRANGE, ZRANGEBYSCORE, ZRANK, ZREVRANK, ZSCORE, ZREM, ZCARD, ZCOUNT,
              EXPIRE, PEXPIRE, EXPIREAT, PEXPIREAT, TTL, PTTL, PERSIST,
              DEL, EXISTS, TYPE, KEYS, FLUSHDB, DBSIZE.
    """
    cmd = req.cmd.strip().upper()
    args = req.args

    try:
        # ── Strings ──────────────────────────────────────────────────────────
        if cmd == "SET":
            if len(args) < 2:
                raise RedisError("ERR wrong number of arguments for 'set' command")
            key, val = str(args[0]), args[1]
            nx = False
            xx = False
            ex: Optional[float] = None
            px: Optional[int] = None

            # Parse optional arguments: [NX|XX] [EX seconds|PX milliseconds]
            i = 2
            while i < len(args):
                opt = str(args[i]).upper()
                if opt == "NX":
                    nx = True
                elif opt == "XX":
                    xx = True
                elif opt == "EX" and i + 1 < len(args):
                    ex = float(args[i + 1])
                    i += 1
                elif opt == "PX" and i + 1 < len(args):
                    px = int(args[i + 1])
                    i += 1
                i += 1

            res = redis_store.set(key, val, nx=nx, xx=xx, ex=ex, px=px)
            return {"ok": True, "command": cmd, "result": "OK" if res else None}

        elif cmd == "GET":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'get' command")
            res = redis_store.get(str(args[0]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd in ("INCR", "INCRBY"):
            if len(args) < 1:
                raise RedisError(f"ERR wrong number of arguments for '{cmd.lower()}' command")
            key = str(args[0])
            delta = int(args[1]) if len(args) > 1 else 1
            res = redis_store.incr(key, delta)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd in ("DECR", "DECRBY"):
            if len(args) < 1:
                raise RedisError(f"ERR wrong number of arguments for '{cmd.lower()}' command")
            key = str(args[0])
            delta = int(args[1]) if len(args) > 1 else 1
            res = redis_store.decr(key, delta)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "MSET":
            if len(args) % 2 != 0 or len(args) == 0:
                raise RedisError("ERR wrong number of arguments for 'mset' command")
            mapping = {str(args[i]): args[i + 1] for i in range(0, len(args), 2)}
            redis_store.mset(mapping)
            return {"ok": True, "command": cmd, "result": "OK"}

        elif cmd == "MGET":
            if len(args) == 0:
                raise RedisError("ERR wrong number of arguments for 'mget' command")
            keys = [str(a) for a in args]
            res = redis_store.mget(*keys)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "APPEND":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'append' command")
            res = redis_store.append(str(args[0]), str(args[1]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "STRLEN":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'strlen' command")
            res = redis_store.strlen(str(args[0]))
            return {"ok": True, "command": cmd, "result": res}

        # ── TTL & Expiration ──────────────────────────────────────────────────
        elif cmd == "EXPIRE":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'expire' command")
            res = 1 if redis_store.expire(str(args[0]), float(args[1])) else 0
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "PEXPIRE":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'pexpire' command")
            res = 1 if redis_store.pexpire(str(args[0]), int(args[1])) else 0
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "EXPIREAT":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'expireat' command")
            res = 1 if redis_store.expireat(str(args[0]), float(args[1])) else 0
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "PEXPIREAT":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'pexpireat' command")
            res = 1 if redis_store.pexpireat(str(args[0]), int(args[1])) else 0
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "TTL":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'ttl' command")
            res = redis_store.ttl(str(args[0]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "PTTL":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'pttl' command")
            res = redis_store.pttl(str(args[0]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "PERSIST":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'persist' command")
            res = 1 if redis_store.persist(str(args[0])) else 0
            return {"ok": True, "command": cmd, "result": res}

        # ── Hashes ───────────────────────────────────────────────────────────
        elif cmd in ("HSET", "HMSET"):
            if len(args) < 3 or (len(args) - 1) % 2 != 0:
                raise RedisError(f"ERR wrong number of arguments for '{cmd.lower()}' command")
            key = str(args[0])
            mapping = {str(args[i]): args[i + 1] for i in range(1, len(args), 2)}
            if len(mapping) == 1:
                f, v = next(iter(mapping.items()))
                res = redis_store.hset(key, f, v)
            else:
                redis_store.hmset(key, mapping)
                res = len(mapping)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "HGET":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'hget' command")
            res = redis_store.hget(str(args[0]), str(args[1]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "HGETALL":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'hgetall' command")
            res = redis_store.hgetall(str(args[0]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "HDEL":
            if len(args) < 2:
                raise RedisError("ERR wrong number of arguments for 'hdel' command")
            key = str(args[0])
            fields = [str(a) for a in args[1:]]
            res = redis_store.hdel(key, *fields)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "HEXISTS":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'hexists' command")
            res = 1 if redis_store.hexists(str(args[0]), str(args[1])) else 0
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "HKEYS":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'hkeys' command")
            res = redis_store.hkeys(str(args[0]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "HVALS":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'hvals' command")
            res = redis_store.hvals(str(args[0]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "HLEN":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'hlen' command")
            res = redis_store.hlen(str(args[0]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "HINCRBY":
            if len(args) != 3:
                raise RedisError("ERR wrong number of arguments for 'hincrby' command")
            key, field, delta = str(args[0]), str(args[1]), int(args[2])
            res = redis_store.hincrby(key, field, delta)
            return {"ok": True, "command": cmd, "result": res}

        # ── Lists ────────────────────────────────────────────────────────────
        elif cmd == "LPUSH":
            if len(args) < 2:
                raise RedisError("ERR wrong number of arguments for 'lpush' command")
            key = str(args[0])
            vals = args[1:]
            res = redis_store.lpush(key, *vals)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "RPUSH":
            if len(args) < 2:
                raise RedisError("ERR wrong number of arguments for 'rpush' command")
            key = str(args[0])
            vals = args[1:]
            res = redis_store.rpush(key, *vals)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "LPOP":
            if len(args) < 1:
                raise RedisError("ERR wrong number of arguments for 'lpop' command")
            key = str(args[0])
            count = int(args[1]) if len(args) > 1 else 1
            res = redis_store.lpop(key, count)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "RPOP":
            if len(args) < 1:
                raise RedisError("ERR wrong number of arguments for 'rpop' command")
            key = str(args[0])
            count = int(args[1]) if len(args) > 1 else 1
            res = redis_store.rpop(key, count)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "LRANGE":
            if len(args) != 3:
                raise RedisError("ERR wrong number of arguments for 'lrange' command")
            key, start, stop = str(args[0]), int(args[1]), int(args[2])
            res = redis_store.lrange(key, start, stop)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "LLEN":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'llen' command")
            res = redis_store.llen(str(args[0]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "LINDEX":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'lindex' command")
            res = redis_store.lindex(str(args[0]), int(args[1]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "LTRIM":
            if len(args) != 3:
                raise RedisError("ERR wrong number of arguments for 'ltrim' command")
            redis_store.ltrim(str(args[0]), int(args[1]), int(args[2]))
            return {"ok": True, "command": cmd, "result": "OK"}

        # ── Sets ─────────────────────────────────────────────────────────────
        elif cmd == "SADD":
            if len(args) < 2:
                raise RedisError("ERR wrong number of arguments for 'sadd' command")
            key = str(args[0])
            members = args[1:]
            res = redis_store.sadd(key, *members)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "SMEMBERS":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'smembers' command")
            res = list(redis_store.smembers(str(args[0])))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "SREM":
            if len(args) < 2:
                raise RedisError("ERR wrong number of arguments for 'srem' command")
            key = str(args[0])
            members = args[1:]
            res = redis_store.srem(key, *members)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "SISMEMBER":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'sismember' command")
            res = 1 if redis_store.sismember(str(args[0]), args[1]) else 0
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "SCARD":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'scard' command")
            res = redis_store.scard(str(args[0]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "SINTER":
            if len(args) < 1:
                raise RedisError("ERR wrong number of arguments for 'sinter' command")
            keys = [str(a) for a in args]
            res = list(redis_store.sinter(*keys))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "SUNION":
            if len(args) < 1:
                raise RedisError("ERR wrong number of arguments for 'sunion' command")
            keys = [str(a) for a in args]
            res = list(redis_store.sunion(*keys))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "SDIFF":
            if len(args) < 1:
                raise RedisError("ERR wrong number of arguments for 'sdiff' command")
            first = str(args[0])
            others = [str(a) for a in args[1:]]
            res = list(redis_store.sdiff(first, *others))
            return {"ok": True, "command": cmd, "result": res}

        # ── Sorted Sets (ZSets) ──────────────────────────────────────────────
        elif cmd == "ZADD":
            if len(args) < 3 or (len(args) - 1) % 2 != 0:
                raise RedisError("ERR wrong number of arguments for 'zadd' command")
            key = str(args[0])
            mapping = {}
            for i in range(1, len(args), 2):
                score = float(args[i])
                member = str(args[i + 1])
                mapping[member] = score
            res = redis_store.zadd(key, mapping)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "ZRANGE":
            if len(args) < 3:
                raise RedisError("ERR wrong number of arguments for 'zrange' command")
            key, start, stop = str(args[0]), int(args[1]), int(args[2])
            withscores = bool(len(args) > 3 and str(args[3]).upper() == "WITHSCORES")
            res = redis_store.zrange(key, start, stop, withscores=withscores)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "ZREVRANGE":
            if len(args) < 3:
                raise RedisError("ERR wrong number of arguments for 'zrevrange' command")
            key, start, stop = str(args[0]), int(args[1]), int(args[2])
            withscores = bool(len(args) > 3 and str(args[3]).upper() == "WITHSCORES")
            res = redis_store.zrevrange(key, start, stop, withscores=withscores)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "ZRANGEBYSCORE":
            if len(args) < 3:
                raise RedisError("ERR wrong number of arguments for 'zrangebyscore' command")
            key = str(args[0])
            min_s = float("-inf") if str(args[1]) == "-inf" else float(args[1])
            max_s = float("inf") if str(args[2]) == "+inf" else float(args[2])
            withscores = bool(len(args) > 3 and str(args[3]).upper() == "WITHSCORES")
            res = redis_store.zrangebyscore(key, min_s, max_s, withscores=withscores)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "ZRANK":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'zrank' command")
            res = redis_store.zrank(str(args[0]), args[1])
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "ZREVRANK":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'zrevrank' command")
            res = redis_store.zrevrank(str(args[0]), args[1])
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "ZSCORE":
            if len(args) != 2:
                raise RedisError("ERR wrong number of arguments for 'zscore' command")
            res = redis_store.zscore(str(args[0]), args[1])
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "ZREM":
            if len(args) < 2:
                raise RedisError("ERR wrong number of arguments for 'zrem' command")
            key = str(args[0])
            members = args[1:]
            res = redis_store.zrem(key, *members)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "ZCARD":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'zcard' command")
            res = redis_store.zcard(str(args[0]))
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "ZCOUNT":
            if len(args) != 3:
                raise RedisError("ERR wrong number of arguments for 'zcount' command")
            key, min_s, max_s = str(args[0]), float(args[1]), float(args[2])
            res = redis_store.zcount(key, min_s, max_s)
            return {"ok": True, "command": cmd, "result": res}

        # ── Generic Keys ─────────────────────────────────────────────────────
        elif cmd == "DEL":
            if len(args) < 1:
                raise RedisError("ERR wrong number of arguments for 'del' command")
            keys = [str(a) for a in args]
            res = redis_store.delete(*keys)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "EXISTS":
            if len(args) < 1:
                raise RedisError("ERR wrong number of arguments for 'exists' command")
            keys = [str(a) for a in args]
            res = redis_store.exists(*keys)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "TYPE":
            if len(args) != 1:
                raise RedisError("ERR wrong number of arguments for 'type' command")
            res = redis_store.type(str(args[0])).value
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "KEYS":
            pattern = str(args[0]) if len(args) > 0 else "*"
            res = redis_store.keys(pattern)
            return {"ok": True, "command": cmd, "result": res}

        elif cmd == "FLUSHDB":
            redis_store.flushdb()
            return {"ok": True, "command": cmd, "result": "OK"}

        elif cmd == "DBSIZE":
            res = redis_store.dbsize()
            return {"ok": True, "command": cmd, "result": res}

        else:
            raise RedisError(f"ERR unknown command '{cmd}'")

    except WrongTypeError as e:
        return {"ok": False, "command": cmd, "error": str(e), "error_type": "WRONGTYPE"}
    except OOMError as e:
        return {"ok": False, "command": cmd, "error": str(e), "error_type": "OOM"}
    except RedisError as e:
        return {"ok": False, "command": cmd, "error": str(e), "error_type": "ERR"}
    except Exception as e:
        return {"ok": False, "command": cmd, "error": f"ERR {str(e)}", "error_type": "INTERNAL"}


@router.post("/expire")
def set_key_expiration(req: ExpireRequest) -> Dict[str, Any]:
    """Set Time-To-Live expiration on a key."""
    success = redis_store.expire(req.key, req.seconds)
    return {"key": req.key, "seconds": req.seconds, "success": success}


@router.get("/ttl/{key}")
def get_key_ttl(key: str) -> Dict[str, Any]:
    """Get remaining TTL in seconds and milliseconds."""
    ttl_sec = redis_store.ttl(key)
    ttl_ms = redis_store.pttl(key)
    return {
        "key": key,
        "ttl_seconds": ttl_sec,
        "ttl_milliseconds": ttl_ms,
        "has_ttl": ttl_sec >= 0,
        "is_persistent": ttl_sec == -1,
        "not_found": ttl_sec == -2,
    }


@router.post("/persist/{key}")
def persist_key(key: str) -> Dict[str, Any]:
    """Remove TTL on a key, making it persistent."""
    success = redis_store.persist(key)
    return {"key": key, "persisted": success}


@router.post("/config/eviction")
def configure_eviction(req: EvictionConfigRequest) -> Dict[str, Any]:
    """Configure maximum keys ceiling and memory eviction policy."""
    try:
        redis_store.configure_eviction(max_keys=req.max_keys, policy=req.policy)
        return {
            "ok": True,
            "max_keys": redis_store._max_keys,
            "eviction_policy": redis_store._eviction_policy.value,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/keys")
def list_keys(pattern: str = Query("*", description="Glob pattern matching keys")) -> Dict[str, Any]:
    """Retrieve keys matching a pattern with their type, size, and TTL."""
    matched_keys = redis_store.keys(pattern)
    key_details = []
    for k in matched_keys:
        k_type = redis_store.type(k)
        size = 0
        if k_type == RedisType.STRING:
            size = redis_store.strlen(k)
        elif k_type == RedisType.HASH:
            size = redis_store.hlen(k)
        elif k_type == RedisType.LIST:
            size = redis_store.llen(k)
        elif k_type == RedisType.SET:
            size = redis_store.scard(k)
        elif k_type == RedisType.ZSET:
            size = redis_store.zcard(k)

        key_details.append({
            "key": k,
            "type": k_type.value,
            "size": size,
            "ttl": redis_store.ttl(k),
        })

    return {
        "pattern": pattern,
        "count": len(key_details),
        "keys": key_details,
    }


@router.get("/get/{key}")
def inspect_key(key: str) -> Dict[str, Any]:
    """Inspect complete value, structure, and type of any key."""
    k_type = redis_store.type(key)
    if k_type == RedisType.NONE:
        raise HTTPException(status_code=404, detail=f"Key '{key}' not found or expired")

    value: Any = None
    size = 0
    if k_type == RedisType.STRING:
        value = redis_store.get(key)
        size = len(str(value)) if value else 0
    elif k_type == RedisType.HASH:
        value = redis_store.hgetall(key)
        size = len(value)
    elif k_type == RedisType.LIST:
        value = redis_store.lrange(key, 0, -1)
        size = len(value)
    elif k_type == RedisType.SET:
        value = list(redis_store.smembers(key))
        size = len(value)
    elif k_type == RedisType.ZSET:
        value = redis_store.zrange(key, 0, -1, withscores=True)
        size = len(value)

    return {
        "key": key,
        "type": k_type.value,
        "size": size,
        "ttl": redis_store.ttl(key),
        "value": value,
    }


@router.delete("/delete/{key}")
def delete_key(key: str) -> Dict[str, Any]:
    """Delete a key."""
    deleted = redis_store.delete(key)
    return {"key": key, "deleted": deleted > 0}


@router.post("/flush")
def flush_database() -> Dict[str, Any]:
    """Flush all keys from the Redis store."""
    redis_store.flushdb()
    return {"ok": True, "message": "Database flushed successfully"}


@router.get("/stats")
def get_redis_stats() -> Dict[str, Any]:
    """Get operational statistics and metrics for the Redis store."""
    return redis_store.stats()
