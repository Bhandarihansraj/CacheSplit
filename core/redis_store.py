"""
core/redis_store.py
High-performance, thread-safe in-memory Redis data structures store.
Supports:
  1. Strings (SET, GET, INCR, DECR, MSET, MGET, SETNX, APPEND, STRLEN)
  2. Hashes (HSET, HGET, HGETALL, HDEL, HEXISTS, HKEYS, HVALS, HLEN, HINCRBY)
  3. Lists (LPUSH, RPUSH, LPOP, RPOP, LRANGE, LLEN, LINDEX, LTRIM)
  4. Sets (SADD, SMEMBERS, SREM, SISMEMBER, SCARD, SINTER, SUNION, SDIFF)
  5. Sorted Sets / ZSets (ZADD, ZRANGE, ZREVRANGE, ZRANGEBYSCORE, ZRANK, ZREVRANK, ZSCORE, ZREM, ZCARD, ZCOUNT)
  6. TTL & Key Expiration (EXPIRE, PEXPIRE, EXPIREAT, PEXPIREAT, TTL, PTTL, PERSIST)
  7. Passive On-Access Expiration & Active Sampling Sweep
  8. Configurable Memory Eviction Policies (allkeys-lru, volatile-lru, allkeys-lfu, volatile-lfu, volatile-ttl, noeviction, allkeys-random)
"""
from __future__ import annotations
import fnmatch
import math
import random
import threading
import time
from collections import deque
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union


class RedisType(str, Enum):
    STRING = "string"
    HASH = "hash"
    LIST = "list"
    SET = "set"
    ZSET = "zset"
    NONE = "none"


class EvictionPolicy(str, Enum):
    NOEVICTION = "noeviction"
    ALLKEYS_LRU = "allkeys-lru"
    VOLATILE_LRU = "volatile-lru"
    ALLKEYS_LFU = "allkeys-lfu"
    VOLATILE_LFU = "volatile-lfu"
    VOLATILE_TTL = "volatile-ttl"
    ALLKEYS_RANDOM = "allkeys-random"


class RedisError(Exception):
    """Base exception for Redis store operations."""
    pass


class WrongTypeError(RedisError):
    """WRONGTYPE Operation against a key holding the wrong kind of value."""
    def __init__(self, message: str = "WRONGTYPE Operation against a key holding the wrong kind of value"):
        super().__init__(message)


class OOMError(RedisError):
    """OOM command not allowed when used memory > 'maxmemory'."""
    def __init__(self, message: str = "OOM command not allowed when max_keys limit reached and noeviction policy set"):
        super().__init__(message)


class RedisStore:
    """
    Thread-safe in-memory Redis data structures engine with TTL and LRU/LFU memory eviction.
    """
    def __init__(self, max_keys: Optional[int] = None, eviction_policy: EvictionPolicy = EvictionPolicy.NOEVICTION):
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self._types: Dict[str, RedisType] = {}
        self._created_at: Dict[str, float] = {}
        self._updated_at: Dict[str, float] = {}
        
        # TTL & Expiration
        self._expires_at: Dict[str, float] = {}  # {key: unix_timestamp_float}

        # Access Tracking (LRU / LFU)
        self._last_accessed_at: Dict[str, float] = {}  # {key: unix_timestamp_float}
        self._access_count: Dict[str, int] = {}       # {key: frequency_counter}

        # Eviction Configuration
        self._max_keys: Optional[int] = max_keys
        self._eviction_policy: EvictionPolicy = eviction_policy
        self._evicted_count: int = 0

        # Stats
        self._cmd_count: int = 0
        self._hits: int = 0
        self._misses: int = 0
        self._expired_count: int = 0

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL HELPERS: TTL, LRU/LFU, EVICTION
    # ─────────────────────────────────────────────────────────────────────────
    def _is_expired(self, key: str, now: Optional[float] = None) -> bool:
        """Returns True if key has an expired TTL."""
        if key not in self._expires_at:
            return False
        if now is None:
            now = time.time()
        return now >= self._expires_at[key]

    def _purge_if_expired(self, key: str) -> bool:
        """Lazy passive expiration: purges key if expired and returns True."""
        if self._is_expired(key):
            self._purge_key(key)
            self._expired_count += 1
            return True
        return False

    def _purge_key(self, key: str) -> None:
        """Unconditionally deletes key and all its metadata."""
        self._data.pop(key, None)
        self._types.pop(key, None)
        self._created_at.pop(key, None)
        self._updated_at.pop(key, None)
        self._expires_at.pop(key, None)
        self._last_accessed_at.pop(key, None)
        self._access_count.pop(key, None)

    def _record_access(self, key: str) -> None:
        """Updates LRU timestamp and LFU counter on key access."""
        now = time.time()
        self._last_accessed_at[key] = now
        self._access_count[key] = self._access_count.get(key, 0) + 1

    def _check_type(self, key: str, expected: RedisType) -> None:
        """Enforces Redis type safety; raises WrongTypeError if key holds a different type."""
        self._purge_if_expired(key)
        if key in self._types and self._types[key] != expected:
            raise WrongTypeError()

    def _maybe_evict(self) -> None:
        """
        Evicts a key if current key count >= max_keys based on the configured EvictionPolicy.
        """
        if self._max_keys is None or len(self._data) < self._max_keys:
            return

        # First, run a quick active expiration sweep to reclaim already-dead keys
        self.active_expire_cycle(sample_size=10)
        if len(self._data) < self._max_keys:
            return

        policy = self._eviction_policy

        if policy == EvictionPolicy.NOEVICTION:
            raise OOMError()

        candidate_keys: List[str] = []
        if policy in (EvictionPolicy.VOLATILE_LRU, EvictionPolicy.VOLATILE_LFU, EvictionPolicy.VOLATILE_TTL):
            candidate_keys = list(self._expires_at.keys())
            if not candidate_keys:
                # No volatile keys available to evict
                raise OOMError(f"OOM: no volatile keys available for eviction under {policy.value}")
        else:
            candidate_keys = list(self._data.keys())

        if not candidate_keys:
            return

        victim_key: Optional[str] = None

        if policy in (EvictionPolicy.ALLKEYS_LRU, EvictionPolicy.VOLATILE_LRU):
            # Victim is key with oldest last_accessed_at
            victim_key = min(candidate_keys, key=lambda k: self._last_accessed_at.get(k, 0.0))

        elif policy in (EvictionPolicy.ALLKEYS_LFU, EvictionPolicy.VOLATILE_LFU):
            # Victim is key with lowest access_count
            victim_key = min(candidate_keys, key=lambda k: self._access_count.get(k, 0))

        elif policy == EvictionPolicy.VOLATILE_TTL:
            # Victim is key with closest expiration timestamp
            victim_key = min(candidate_keys, key=lambda k: self._expires_at.get(k, float("inf")))

        elif policy == EvictionPolicy.ALLKEYS_RANDOM:
            victim_key = random.choice(candidate_keys)

        if victim_key:
            self._purge_key(victim_key)
            self._evicted_count += 1

    def active_expire_cycle(self, sample_size: int = 20) -> int:
        """
        Active background sweep: samples random keys with TTL and purges expired ones.
        Returns the number of expired keys purged in this cycle.
        """
        with self._lock:
            if not self._expires_at:
                return 0

            volatile_keys = list(self._expires_at.keys())
            sample = random.sample(volatile_keys, min(len(volatile_keys), sample_size))
            now = time.time()
            purged = 0

            for k in sample:
                if now >= self._expires_at.get(k, float("inf")):
                    self._purge_key(k)
                    self._expired_count += 1
                    purged += 1

            return purged

    # ─────────────────────────────────────────────────────────────────────────
    # CONFIGURATION & SETTINGS
    # ─────────────────────────────────────────────────────────────────────────
    def configure_eviction(
        self,
        max_keys: Optional[int] = None,
        policy: Optional[Union[EvictionPolicy, str]] = None,
    ) -> None:
        """Updates max_keys ceiling and eviction policy."""
        with self._lock:
            if max_keys is not None:
                self._max_keys = max_keys if max_keys > 0 else None
            if policy is not None:
                if isinstance(policy, str):
                    self._eviction_policy = EvictionPolicy(policy.lower())
                else:
                    self._eviction_policy = policy

    # ─────────────────────────────────────────────────────────────────────────
    # 6. TTL & EXPIRATION COMMANDS
    # ─────────────────────────────────────────────────────────────────────────
    def expire(self, key: str, seconds: Union[int, float]) -> bool:
        """EXPIRE key seconds -> sets expiration time in seconds."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return False
            self._expires_at[key] = time.time() + float(seconds)
            return True

    def pexpire(self, key: str, milliseconds: int) -> bool:
        """PEXPIRE key ms -> sets expiration time in milliseconds."""
        return self.expire(key, milliseconds / 1000.0)

    def expireat(self, key: str, timestamp: Union[int, float]) -> bool:
        """EXPIREAT key unix_timestamp -> sets absolute epoch expiration timestamp."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return False
            self._expires_at[key] = float(timestamp)
            return True

    def pexpireat(self, key: str, ms_timestamp: int) -> bool:
        """PEXPIREAT key ms_timestamp -> sets absolute epoch expiration in milliseconds."""
        return self.expireat(key, ms_timestamp / 1000.0)

    def ttl(self, key: str) -> int:
        """
        TTL key -> returns remaining seconds:
          -2: key does not exist
          -1: key exists but has no associated expire
         >=0: remaining TTL in integer seconds
        """
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return -2
            if key not in self._expires_at:
                return -1
            rem = self._expires_at[key] - time.time()
            return max(0, math.ceil(rem))

    def pttl(self, key: str) -> int:
        """
        PTTL key -> returns remaining milliseconds:
          -2: key does not exist
          -1: key exists but has no associated expire
         >=0: remaining TTL in integer milliseconds
        """
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return -2
            if key not in self._expires_at:
                return -1
            rem_ms = (self._expires_at[key] - time.time()) * 1000.0
            return max(0, int(rem_ms))

    def persist(self, key: str) -> bool:
        """PERSIST key -> removes TTL, making key persistent. Returns True if removed."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return False
            if key in self._expires_at:
                del self._expires_at[key]
                return True
            return False

    # ─────────────────────────────────────────────────────────────────────────
    # 1. STRING OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────
    def set(
        self,
        key: str,
        value: Any,
        nx: bool = False,
        xx: bool = False,
        ex: Optional[Union[int, float]] = None,
        px: Optional[int] = None,
    ) -> bool:
        """
        SET key value [NX|XX] [EX seconds|PX milliseconds]
        """
        with self._lock:
            self._cmd_count += 1
            self._purge_if_expired(key)
            now = time.time()
            exists = key in self._data

            if nx and exists:
                return False
            if xx and not exists:
                return False

            if not exists:
                self._maybe_evict()

            self._data[key] = str(value)
            self._types[key] = RedisType.STRING
            if not exists:
                self._created_at[key] = now
            self._updated_at[key] = now
            self._record_access(key)

            # Handle TTL
            if ex is not None:
                self._expires_at[key] = now + float(ex)
            elif px is not None:
                self._expires_at[key] = now + (float(px) / 1000.0)
            else:
                self._expires_at.pop(key, None)

            return True

    def get(self, key: str) -> Optional[str]:
        """GET key -> returns string value or None."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                self._misses += 1
                return None
            self._check_type(key, RedisType.STRING)
            self._hits += 1
            self._record_access(key)
            return str(self._data[key])

    def incr(self, key: str, delta: int = 1) -> int:
        """INCR / INCRBY key delta -> increments integer value."""
        with self._lock:
            self._cmd_count += 1
            self._purge_if_expired(key)
            self._check_type(key, RedisType.STRING)
            exists = key in self._data

            if not exists:
                self._maybe_evict()

            val_str = self._data.get(key, "0")
            try:
                val = int(val_str) + delta
            except ValueError:
                raise RedisError("ERR value is not an integer or out of range")
            
            self._data[key] = str(val)
            self._types[key] = RedisType.STRING
            now = time.time()
            if not exists:
                self._created_at[key] = now
            self._updated_at[key] = now
            self._record_access(key)
            return val

    def decr(self, key: str, delta: int = 1) -> int:
        """DECR / DECRBY key delta -> decrements integer value."""
        return self.incr(key, -delta)

    def mset(self, mapping: Dict[str, Any]) -> bool:
        """MSET key1 val1 key2 val2 ..."""
        with self._lock:
            self._cmd_count += 1
            now = time.time()
            for k, v in mapping.items():
                self._purge_if_expired(k)
                if k not in self._data:
                    self._maybe_evict()
                self._data[k] = str(v)
                self._types[k] = RedisType.STRING
                if k not in self._created_at:
                    self._created_at[k] = now
                self._updated_at[k] = now
                self._record_access(k)
            return True

    def mget(self, *keys: str) -> List[Optional[str]]:
        """MGET key1 key2 ..."""
        with self._lock:
            self._cmd_count += 1
            res = []
            for k in keys:
                if not self._purge_if_expired(k) and k in self._data and self._types.get(k) == RedisType.STRING:
                    res.append(str(self._data[k]))
                    self._hits += 1
                    self._record_access(k)
                else:
                    res.append(None)
                    self._misses += 1
            return res

    def append(self, key: str, value: str) -> int:
        """APPEND key value -> appends to string and returns new length."""
        with self._lock:
            self._cmd_count += 1
            self._purge_if_expired(key)
            self._check_type(key, RedisType.STRING)
            if key not in self._data:
                self._maybe_evict()

            current = str(self._data.get(key, ""))
            new_val = current + str(value)
            self._data[key] = new_val
            self._types[key] = RedisType.STRING
            now = time.time()
            if key not in self._created_at:
                self._created_at[key] = now
            self._updated_at[key] = now
            self._record_access(key)
            return len(new_val)

    def strlen(self, key: str) -> int:
        """STRLEN key -> returns length of string value."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return 0
            self._check_type(key, RedisType.STRING)
            self._record_access(key)
            return len(str(self._data[key]))

    # ─────────────────────────────────────────────────────────────────────────
    # 2. HASH OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────
    def hset(self, key: str, field: str, value: Any) -> int:
        """HSET key field value -> returns 1 if new field, 0 if updated."""
        with self._lock:
            self._cmd_count += 1
            self._purge_if_expired(key)
            self._check_type(key, RedisType.HASH)
            now = time.time()
            if key not in self._data:
                self._maybe_evict()
                self._data[key] = {}
                self._types[key] = RedisType.HASH
                self._created_at[key] = now

            is_new = 1 if str(field) not in self._data[key] else 0
            self._data[key][str(field)] = str(value)
            self._updated_at[key] = now
            self._record_access(key)
            return is_new

    def hmset(self, key: str, mapping: Dict[str, Any]) -> bool:
        """HMSET / HSET key field1 val1 field2 val2 ..."""
        with self._lock:
            self._cmd_count += 1
            self._purge_if_expired(key)
            self._check_type(key, RedisType.HASH)
            now = time.time()
            if key not in self._data:
                self._maybe_evict()
                self._data[key] = {}
                self._types[key] = RedisType.HASH
                self._created_at[key] = now

            for f, v in mapping.items():
                self._data[key][str(f)] = str(v)
            self._updated_at[key] = now
            self._record_access(key)
            return True

    def hget(self, key: str, field: str) -> Optional[str]:
        """HGET key field -> returns field value or None."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                self._misses += 1
                return None
            self._check_type(key, RedisType.HASH)
            val = self._data[key].get(str(field))
            if val is not None:
                self._hits += 1
                self._record_access(key)
            else:
                self._misses += 1
            return val

    def hgetall(self, key: str) -> Dict[str, str]:
        """HGETALL key -> returns copy of entire field dictionary."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                self._misses += 1
                return {}
            self._check_type(key, RedisType.HASH)
            self._hits += 1
            self._record_access(key)
            return dict(self._data[key])

    def hdel(self, key: str, *fields: str) -> int:
        """HDEL key field1 field2 ... -> returns count of removed fields."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return 0
            self._check_type(key, RedisType.HASH)
            removed = 0
            for f in fields:
                if str(f) in self._data[key]:
                    del self._data[key][str(f)]
                    removed += 1
            if removed > 0:
                self._updated_at[key] = time.time()
                self._record_access(key)
            if len(self._data[key]) == 0:
                self._purge_key(key)
            return removed

    def hexists(self, key: str, field: str) -> bool:
        """HEXISTS key field -> returns True if field exists."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return False
            self._check_type(key, RedisType.HASH)
            self._record_access(key)
            return str(field) in self._data[key]

    def hkeys(self, key: str) -> List[str]:
        """HKEYS key -> returns list of fields in hash."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return []
            self._check_type(key, RedisType.HASH)
            self._record_access(key)
            return list(self._data[key].keys())

    def hvals(self, key: str) -> List[str]:
        """HVALS key -> returns list of values in hash."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return []
            self._check_type(key, RedisType.HASH)
            self._record_access(key)
            return list(self._data[key].values())

    def hlen(self, key: str) -> int:
        """HLEN key -> returns number of fields in hash."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return 0
            self._check_type(key, RedisType.HASH)
            self._record_access(key)
            return len(self._data[key])

    def hincrby(self, key: str, field: str, delta: int = 1) -> int:
        """HINCRBY key field delta -> increments integer value of field."""
        with self._lock:
            self._cmd_count += 1
            self._purge_if_expired(key)
            self._check_type(key, RedisType.HASH)
            now = time.time()
            if key not in self._data:
                self._maybe_evict()
                self._data[key] = {}
                self._types[key] = RedisType.HASH
                self._created_at[key] = now

            current_val = self._data[key].get(str(field), "0")
            try:
                new_val = int(current_val) + delta
            except ValueError:
                raise RedisError("ERR hash value is not an integer")
            
            self._data[key][str(field)] = str(new_val)
            self._updated_at[key] = now
            self._record_access(key)
            return new_val

    # ─────────────────────────────────────────────────────────────────────────
    # 3. LIST OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────
    def lpush(self, key: str, *values: Any) -> int:
        """LPUSH key val1 val2 ... -> pushes to the head of list, returns new length."""
        with self._lock:
            self._cmd_count += 1
            self._purge_if_expired(key)
            self._check_type(key, RedisType.LIST)
            now = time.time()
            if key not in self._data:
                self._maybe_evict()
                self._data[key] = deque()
                self._types[key] = RedisType.LIST
                self._created_at[key] = now

            for v in values:
                self._data[key].appendleft(str(v))
            self._updated_at[key] = now
            self._record_access(key)
            return len(self._data[key])

    def rpush(self, key: str, *values: Any) -> int:
        """RPUSH key val1 val2 ... -> pushes to the tail of list, returns new length."""
        with self._lock:
            self._cmd_count += 1
            self._purge_if_expired(key)
            self._check_type(key, RedisType.LIST)
            now = time.time()
            if key not in self._data:
                self._maybe_evict()
                self._data[key] = deque()
                self._types[key] = RedisType.LIST
                self._created_at[key] = now

            for v in values:
                self._data[key].append(str(v))
            self._updated_at[key] = now
            self._record_access(key)
            return len(self._data[key])

    def lpop(self, key: str, count: int = 1) -> Union[Optional[str], List[str]]:
        """LPOP key [count] -> pops element(s) from the head."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return None if count == 1 else []
            self._check_type(key, RedisType.LIST)
            d: deque = self._data[key]
            self._record_access(key)
            
            if count == 1:
                val = d.popleft() if d else None
                if len(d) == 0:
                    self._purge_key(key)
                return val
            else:
                popped = []
                for _ in range(min(count, len(d))):
                    popped.append(d.popleft())
                if len(d) == 0:
                    self._purge_key(key)
                return popped

    def rpop(self, key: str, count: int = 1) -> Union[Optional[str], List[str]]:
        """RPOP key [count] -> pops element(s) from the tail."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return None if count == 1 else []
            self._check_type(key, RedisType.LIST)
            d: deque = self._data[key]
            self._record_access(key)
            
            if count == 1:
                val = d.pop() if d else None
                if len(d) == 0:
                    self._purge_key(key)
                return val
            else:
                popped = []
                for _ in range(min(count, len(d))):
                    popped.append(d.pop())
                if len(d) == 0:
                    self._purge_key(key)
                return popped

    def lrange(self, key: str, start: int, stop: int) -> List[str]:
        """LRANGE key start stop -> returns list elements in index range (0-indexed, inclusive)."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return []
            self._check_type(key, RedisType.LIST)
            self._record_access(key)
            d_list = list(self._data[key])
            n = len(d_list)
            if n == 0:
                return []

            if start < 0:
                start = max(0, n + start)
            if stop < 0:
                stop = n + stop
            else:
                stop = min(n - 1, stop)

            if start > stop or start >= n:
                return []
            return d_list[start : stop + 1]

    def llen(self, key: str) -> int:
        """LLEN key -> returns number of elements in list."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return 0
            self._check_type(key, RedisType.LIST)
            self._record_access(key)
            return len(self._data[key])

    def lindex(self, key: str, index: int) -> Optional[str]:
        """LINDEX key index -> returns element at index."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return None
            self._check_type(key, RedisType.LIST)
            self._record_access(key)
            d_list = list(self._data[key])
            try:
                return d_list[index]
            except IndexError:
                return None

    def ltrim(self, key: str, start: int, stop: int) -> bool:
        """LTRIM key start stop -> trims list to specified range."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return True
            self._check_type(key, RedisType.LIST)
            trimmed = self.lrange(key, start, stop)
            if not trimmed:
                self._purge_key(key)
            else:
                self._data[key] = deque(trimmed)
                self._updated_at[key] = time.time()
                self._record_access(key)
            return True

    # ─────────────────────────────────────────────────────────────────────────
    # 4. SET OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────
    def sadd(self, key: str, *members: Any) -> int:
        """SADD key member1 member2 ... -> returns count of newly added members."""
        with self._lock:
            self._cmd_count += 1
            self._purge_if_expired(key)
            self._check_type(key, RedisType.SET)
            now = time.time()
            if key not in self._data:
                self._maybe_evict()
                self._data[key] = set()
                self._types[key] = RedisType.SET
                self._created_at[key] = now

            added = 0
            for m in members:
                m_str = str(m)
                if m_str not in self._data[key]:
                    self._data[key].add(m_str)
                    added += 1
            if added > 0:
                self._updated_at[key] = now
            self._record_access(key)
            return added

    def smembers(self, key: str) -> Set[str]:
        """SMEMBERS key -> returns set of all members."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return set()
            self._check_type(key, RedisType.SET)
            self._record_access(key)
            return set(self._data[key])

    def srem(self, key: str, *members: Any) -> int:
        """SREM key member1 member2 ... -> returns count of removed members."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return 0
            self._check_type(key, RedisType.SET)
            removed = 0
            for m in members:
                m_str = str(m)
                if m_str in self._data[key]:
                    self._data[key].remove(m_str)
                    removed += 1
            if removed > 0:
                self._updated_at[key] = time.time()
                self._record_access(key)
            if len(self._data[key]) == 0:
                self._purge_key(key)
            return removed

    def sismember(self, key: str, member: Any) -> bool:
        """SISMEMBER key member -> returns True if member is in set."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return False
            self._check_type(key, RedisType.SET)
            self._record_access(key)
            return str(member) in self._data[key]

    def scard(self, key: str) -> int:
        """SCARD key -> returns number of elements in set."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return 0
            self._check_type(key, RedisType.SET)
            self._record_access(key)
            return len(self._data[key])

    def sinter(self, *keys: str) -> Set[str]:
        """SINTER key1 key2 ... -> returns intersection of sets."""
        with self._lock:
            self._cmd_count += 1
            if not keys:
                return set()
            sets = []
            for k in keys:
                if self._purge_if_expired(k) or k not in self._data:
                    return set()
                self._check_type(k, RedisType.SET)
                self._record_access(k)
                sets.append(self._data[k])
            return set.intersection(*sets)

    def sunion(self, *keys: str) -> Set[str]:
        """SUNION key1 key2 ... -> returns union of sets."""
        with self._lock:
            self._cmd_count += 1
            res: Set[str] = set()
            for k in keys:
                if not self._purge_if_expired(k) and k in self._data:
                    self._check_type(k, RedisType.SET)
                    self._record_access(k)
                    res.update(self._data[k])
            return res

    def sdiff(self, first_key: str, *other_keys: str) -> Set[str]:
        """SDIFF key1 key2 ... -> returns difference between first set and all successive sets."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(first_key) or first_key not in self._data:
                return set()
            self._check_type(first_key, RedisType.SET)
            self._record_access(first_key)
            res = set(self._data[first_key])
            for k in other_keys:
                if not self._purge_if_expired(k) and k in self._data:
                    self._check_type(k, RedisType.SET)
                    self._record_access(k)
                    res.difference_update(self._data[k])
            return res

    # ─────────────────────────────────────────────────────────────────────────
    # 5. SORTED SET (ZSET) OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────
    def zadd(self, key: str, mapping: Dict[str, float], nx: bool = False, xx: bool = False) -> int:
        """
        ZADD key score member [score member ...]
        mapping: {member: score}
        """
        with self._lock:
            self._cmd_count += 1
            self._purge_if_expired(key)
            self._check_type(key, RedisType.ZSET)
            now = time.time()
            if key not in self._data:
                self._maybe_evict()
                self._data[key] = {}  # {member: float_score}
                self._types[key] = RedisType.ZSET
                self._created_at[key] = now

            added = 0
            for member, score in mapping.items():
                m_str = str(member)
                score_flt = float(score)
                exists = m_str in self._data[key]

                if nx and exists:
                    continue
                if xx and not exists:
                    continue

                if not exists:
                    added += 1
                self._data[key][m_str] = score_flt

            if added > 0 or len(mapping) > 0:
                self._updated_at[key] = now
            self._record_access(key)
            return added

    def _get_sorted_zset(self, key: str, reverse: bool = False) -> List[Tuple[str, float]]:
        """Internal helper sorting zset elements by (score ASC, member ASC)."""
        items = list(self._data[key].items())
        items.sort(key=lambda item: (item[1], item[0]), reverse=reverse)
        return items

    def zrange(
        self,
        key: str,
        start: int,
        stop: int,
        withscores: bool = False,
    ) -> List[Union[str, Tuple[str, float]]]:
        """ZRANGE key start stop [WITHSCORES] -> elements sorted by score ASC."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return []
            self._check_type(key, RedisType.ZSET)
            self._record_access(key)
            sorted_items = self._get_sorted_zset(key, reverse=False)
            n = len(sorted_items)
            if n == 0:
                return []

            if start < 0:
                start = max(0, n + start)
            if stop < 0:
                stop = n + stop
            else:
                stop = min(n - 1, stop)

            if start > stop or start >= n:
                return []

            slice_items = sorted_items[start : stop + 1]
            if withscores:
                return slice_items
            return [m for m, s in slice_items]

    def zrevrange(
        self,
        key: str,
        start: int,
        stop: int,
        withscores: bool = False,
    ) -> List[Union[str, Tuple[str, float]]]:
        """ZREVRANGE key start stop [WITHSCORES] -> elements sorted by score DESC."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return []
            self._check_type(key, RedisType.ZSET)
            self._record_access(key)
            sorted_items = self._get_sorted_zset(key, reverse=True)
            n = len(sorted_items)
            if n == 0:
                return []

            if start < 0:
                start = max(0, n + start)
            if stop < 0:
                stop = n + stop
            else:
                stop = min(n - 1, stop)

            if start > stop or start >= n:
                return []

            slice_items = sorted_items[start : stop + 1]
            if withscores:
                return slice_items
            return [m for m, s in slice_items]

    def zrangebyscore(
        self,
        key: str,
        min_score: float,
        max_score: float,
        withscores: bool = False,
    ) -> List[Union[str, Tuple[str, float]]]:
        """ZRANGEBYSCORE key min max [WITHSCORES]"""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return []
            self._check_type(key, RedisType.ZSET)
            self._record_access(key)
            sorted_items = self._get_sorted_zset(key, reverse=False)
            filtered = [(m, s) for m, s in sorted_items if min_score <= s <= max_score]
            if withscores:
                return filtered
            return [m for m, s in filtered]

    def zrank(self, key: str, member: Any) -> Optional[int]:
        """ZRANK key member -> returns 0-indexed rank of member sorted ASC, or None."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return None
            self._check_type(key, RedisType.ZSET)
            self._record_access(key)
            m_str = str(member)
            if m_str not in self._data[key]:
                return None
            sorted_items = self._get_sorted_zset(key, reverse=False)
            for rank, (m, _) in enumerate(sorted_items):
                if m == m_str:
                    return rank
            return None

    def zrevrank(self, key: str, member: Any) -> Optional[int]:
        """ZREVRANK key member -> returns 0-indexed rank of member sorted DESC, or None."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return None
            self._check_type(key, RedisType.ZSET)
            self._record_access(key)
            m_str = str(member)
            if m_str not in self._data[key]:
                return None
            sorted_items = self._get_sorted_zset(key, reverse=True)
            for rank, (m, _) in enumerate(sorted_items):
                if m == m_str:
                    return rank
            return None

    def zscore(self, key: str, member: Any) -> Optional[float]:
        """ZSCORE key member -> returns float score of member or None."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return None
            self._check_type(key, RedisType.ZSET)
            self._record_access(key)
            return self._data[key].get(str(member))

    def zrem(self, key: str, *members: Any) -> int:
        """ZREM key member1 member2 ... -> returns count of removed members."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return 0
            self._check_type(key, RedisType.ZSET)
            removed = 0
            for m in members:
                m_str = str(m)
                if m_str in self._data[key]:
                    del self._data[key][m_str]
                    removed += 1
            if removed > 0:
                self._updated_at[key] = time.time()
                self._record_access(key)
            if len(self._data[key]) == 0:
                self._purge_key(key)
            return removed

    def zcard(self, key: str) -> int:
        """ZCARD key -> returns number of members in sorted set."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return 0
            self._check_type(key, RedisType.ZSET)
            self._record_access(key)
            return len(self._data[key])

    def zcount(self, key: str, min_score: float, max_score: float) -> int:
        """ZCOUNT key min max -> returns count of members with scores within [min, max]."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return 0
            self._check_type(key, RedisType.ZSET)
            self._record_access(key)
            return sum(1 for s in self._data[key].values() if min_score <= s <= max_score)

    # ─────────────────────────────────────────────────────────────────────────
    # 7. GENERIC KEY OPERATIONS & METRICS
    # ─────────────────────────────────────────────────────────────────────────
    def delete(self, *keys: str) -> int:
        """DEL key1 key2 ... -> returns count of deleted keys."""
        with self._lock:
            self._cmd_count += 1
            deleted = 0
            for k in keys:
                self._purge_if_expired(k)
                if k in self._data:
                    self._purge_key(k)
                    deleted += 1
            return deleted

    def exists(self, *keys: str) -> int:
        """EXISTS key1 key2 ... -> returns count of keys that exist."""
        with self._lock:
            self._cmd_count += 1
            count = 0
            for k in keys:
                if not self._purge_if_expired(k) and k in self._data:
                    count += 1
                    self._record_access(k)
            return count

    def type(self, key: str) -> RedisType:
        """TYPE key -> returns RedisType."""
        with self._lock:
            self._cmd_count += 1
            if self._purge_if_expired(key) or key not in self._data:
                return RedisType.NONE
            self._record_access(key)
            return self._types.get(key, RedisType.NONE)

    def keys(self, pattern: str = "*") -> List[str]:
        """KEYS pattern -> returns non-expired keys matching glob pattern."""
        with self._lock:
            self._cmd_count += 1
            now = time.time()
            all_keys = list(self._data.keys())
            matched = []
            for k in all_keys:
                if not self._purge_if_expired(k):
                    if pattern == "*" or fnmatch.fnmatch(k, pattern):
                        matched.append(k)
            return matched

    def flushdb(self) -> bool:
        """FLUSHDB -> deletes all keys from database."""
        with self._lock:
            self._cmd_count += 1
            self._data.clear()
            self._types.clear()
            self._created_at.clear()
            self._updated_at.clear()
            self._expires_at.clear()
            self._last_accessed_at.clear()
            self._access_count.clear()
            return True

    def dbsize(self) -> int:
        """DBSIZE -> returns total number of active non-expired keys."""
        with self._lock:
            self.active_expire_cycle(sample_size=20)
            return len(self._data)

    def stats(self) -> Dict[str, Any]:
        """Returns comprehensive stats for monitoring."""
        with self._lock:
            self.active_expire_cycle(sample_size=20)
            type_counts = {}
            for t in RedisType:
                if t != RedisType.NONE:
                    type_counts[t.value] = sum(1 for v in self._types.values() if v == t)

            return {
                "total_keys": len(self._data),
                "volatile_keys": len(self._expires_at),
                "max_keys_limit": self._max_keys,
                "eviction_policy": self._eviction_policy.value,
                "evicted_keys_total": self._evicted_count,
                "expired_keys_total": self._expired_count,
                "type_breakdown": type_counts,
                "total_commands_executed": self._cmd_count,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate_pct": round(
                    (self._hits / max(1, self._hits + self._misses)) * 100, 2
                ),
            }


# Global singleton instance for shared usage
redis_store = RedisStore()
