"""
core/redis_store.py
High-performance, thread-safe in-memory Redis data structures store.
Supports all 5 fundamental Redis data types:
  1. Strings (SET, GET, INCR, DECR, MSET, MGET, SETNX, APPEND, STRLEN)
  2. Hashes (HSET, HGET, HGETALL, HDEL, HEXISTS, HKEYS, HVALS, HLEN, HINCRBY)
  3. Lists (LPUSH, RPUSH, LPOP, RPOP, LRANGE, LLEN, LINDEX, LTRIM)
  4. Sets (SADD, SMEMBERS, SREM, SISMEMBER, SCARD, SINTER, SUNION, SDIFF)
  5. Sorted Sets / ZSets (ZADD, ZRANGE, ZREVRANGE, ZRANGEBYSCORE, ZRANK, ZREVRANK, ZSCORE, ZREM, ZCARD, ZCOUNT)
"""
from __future__ import annotations
import fnmatch
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


class RedisError(Exception):
    """Base exception for Redis store operations."""
    pass


class WrongTypeError(RedisError):
    """WRONGTYPE Operation against a key holding the wrong kind of value."""
    def __init__(self, message: str = "WRONGTYPE Operation against a key holding the wrong kind of value"):
        super().__init__(message)


class RedisStore:
    """
    Thread-safe in-memory Redis data structures engine.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}
        self._types: Dict[str, RedisType] = {}
        self._created_at: Dict[str, float] = {}
        self._updated_at: Dict[str, float] = {}
        self._cmd_count: int = 0
        self._hits: int = 0
        self._misses: int = 0

    def _check_type(self, key: str, expected: RedisType) -> None:
        """Enforces Redis type safety; raises WrongTypeError if key holds a different type."""
        if key in self._types and self._types[key] != expected:
            raise WrongTypeError()

    # ─────────────────────────────────────────────────────────────────────────
    # 1. STRING OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────
    def set(
        self,
        key: str,
        value: Any,
        nx: bool = False,
        xx: bool = False,
    ) -> bool:
        """
        SET key value [NX|XX]
        nx=True: set only if key does not exist.
        xx=True: set only if key already exists.
        """
        with self._lock:
            self._cmd_count += 1
            now = time.time()
            exists = key in self._data

            if nx and exists:
                return False
            if xx and not exists:
                return False

            self._data[key] = str(value)
            self._types[key] = RedisType.STRING
            if not exists:
                self._created_at[key] = now
            self._updated_at[key] = now
            return True

    def get(self, key: str) -> Optional[str]:
        """GET key -> returns string value or None."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                self._misses += 1
                return None
            self._check_type(key, RedisType.STRING)
            self._hits += 1
            return str(self._data[key])

    def incr(self, key: str, delta: int = 1) -> int:
        """INCR / INCRBY key delta -> increments integer value."""
        with self._lock:
            self._cmd_count += 1
            self._check_type(key, RedisType.STRING)
            val_str = self._data.get(key, "0")
            try:
                val = int(val_str) + delta
            except ValueError:
                raise RedisError("ERR value is not an integer or out of range")
            
            self._data[key] = str(val)
            self._types[key] = RedisType.STRING
            now = time.time()
            if key not in self._created_at:
                self._created_at[key] = now
            self._updated_at[key] = now
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
                self._data[k] = str(v)
                self._types[k] = RedisType.STRING
                if k not in self._created_at:
                    self._created_at[k] = now
                self._updated_at[k] = now
            return True

    def mget(self, *keys: str) -> List[Optional[str]]:
        """MGET key1 key2 ..."""
        with self._lock:
            self._cmd_count += 1
            res = []
            for k in keys:
                if k in self._data and self._types.get(k) == RedisType.STRING:
                    res.append(str(self._data[k]))
                    self._hits += 1
                else:
                    res.append(None)
                    self._misses += 1
            return res

    def append(self, key: str, value: str) -> int:
        """APPEND key value -> appends to string and returns new length."""
        with self._lock:
            self._cmd_count += 1
            self._check_type(key, RedisType.STRING)
            current = str(self._data.get(key, ""))
            new_val = current + str(value)
            self._data[key] = new_val
            self._types[key] = RedisType.STRING
            now = time.time()
            if key not in self._created_at:
                self._created_at[key] = now
            self._updated_at[key] = now
            return len(new_val)

    def strlen(self, key: str) -> int:
        """STRLEN key -> returns length of string value."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return 0
            self._check_type(key, RedisType.STRING)
            return len(str(self._data[key]))

    # ─────────────────────────────────────────────────────────────────────────
    # 2. HASH OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────
    def hset(self, key: str, field: str, value: Any) -> int:
        """HSET key field value -> returns 1 if new field, 0 if updated."""
        with self._lock:
            self._cmd_count += 1
            self._check_type(key, RedisType.HASH)
            now = time.time()
            if key not in self._data:
                self._data[key] = {}
                self._types[key] = RedisType.HASH
                self._created_at[key] = now

            is_new = 1 if field not in self._data[key] else 0
            self._data[key][str(field)] = str(value)
            self._updated_at[key] = now
            return is_new

    def hmset(self, key: str, mapping: Dict[str, Any]) -> bool:
        """HMSET / HSET key field1 val1 field2 val2 ..."""
        with self._lock:
            self._cmd_count += 1
            self._check_type(key, RedisType.HASH)
            now = time.time()
            if key not in self._data:
                self._data[key] = {}
                self._types[key] = RedisType.HASH
                self._created_at[key] = now

            for f, v in mapping.items():
                self._data[key][str(f)] = str(v)
            self._updated_at[key] = now
            return True

    def hget(self, key: str, field: str) -> Optional[str]:
        """HGET key field -> returns field value or None."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                self._misses += 1
                return None
            self._check_type(key, RedisType.HASH)
            val = self._data[key].get(str(field))
            if val is not None:
                self._hits += 1
            else:
                self._misses += 1
            return val

    def hgetall(self, key: str) -> Dict[str, str]:
        """HGETALL key -> returns copy of entire field dictionary."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                self._misses += 1
                return {}
            self._check_type(key, RedisType.HASH)
            self._hits += 1
            return dict(self._data[key])

    def hdel(self, key: str, *fields: str) -> int:
        """HDEL key field1 field2 ... -> returns count of removed fields."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return 0
            self._check_type(key, RedisType.HASH)
            removed = 0
            for f in fields:
                if str(f) in self._data[key]:
                    del self._data[key][str(f)]
                    removed += 1
            if removed > 0:
                self._updated_at[key] = time.time()
            if len(self._data[key]) == 0:
                self._clean_empty_key(key)
            return removed

    def hexists(self, key: str, field: str) -> bool:
        """HEXISTS key field -> returns True if field exists."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return False
            self._check_type(key, RedisType.HASH)
            return str(field) in self._data[key]

    def hkeys(self, key: str) -> List[str]:
        """HKEYS key -> returns list of fields in hash."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return []
            self._check_type(key, RedisType.HASH)
            return list(self._data[key].keys())

    def hvals(self, key: str) -> List[str]:
        """HVALS key -> returns list of values in hash."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return []
            self._check_type(key, RedisType.HASH)
            return list(self._data[key].values())

    def hlen(self, key: str) -> int:
        """HLEN key -> returns number of fields in hash."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return 0
            self._check_type(key, RedisType.HASH)
            return len(self._data[key])

    def hincrby(self, key: str, field: str, delta: int = 1) -> int:
        """HINCRBY key field delta -> increments integer value of field."""
        with self._lock:
            self._cmd_count += 1
            self._check_type(key, RedisType.HASH)
            now = time.time()
            if key not in self._data:
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
            return new_val

    # ─────────────────────────────────────────────────────────────────────────
    # 3. LIST OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────
    def lpush(self, key: str, *values: Any) -> int:
        """LPUSH key val1 val2 ... -> pushes to the head of list, returns new length."""
        with self._lock:
            self._cmd_count += 1
            self._check_type(key, RedisType.LIST)
            now = time.time()
            if key not in self._data:
                self._data[key] = deque()
                self._types[key] = RedisType.LIST
                self._created_at[key] = now

            for v in values:
                self._data[key].appendleft(str(v))
            self._updated_at[key] = now
            return len(self._data[key])

    def rpush(self, key: str, *values: Any) -> int:
        """RPUSH key val1 val2 ... -> pushes to the tail of list, returns new length."""
        with self._lock:
            self._cmd_count += 1
            self._check_type(key, RedisType.LIST)
            now = time.time()
            if key not in self._data:
                self._data[key] = deque()
                self._types[key] = RedisType.LIST
                self._created_at[key] = now

            for v in values:
                self._data[key].append(str(v))
            self._updated_at[key] = now
            return len(self._data[key])

    def lpop(self, key: str, count: int = 1) -> Union[Optional[str], List[str]]:
        """LPOP key [count] -> pops element(s) from the head."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return None if count == 1 else []
            self._check_type(key, RedisType.LIST)
            d: deque = self._data[key]
            
            if count == 1:
                val = d.popleft() if d else None
                if len(d) == 0:
                    self._clean_empty_key(key)
                return val
            else:
                popped = []
                for _ in range(min(count, len(d))):
                    popped.append(d.popleft())
                if len(d) == 0:
                    self._clean_empty_key(key)
                return popped

    def rpop(self, key: str, count: int = 1) -> Union[Optional[str], List[str]]:
        """RPOP key [count] -> pops element(s) from the tail."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return None if count == 1 else []
            self._check_type(key, RedisType.LIST)
            d: deque = self._data[key]
            
            if count == 1:
                val = d.pop() if d else None
                if len(d) == 0:
                    self._clean_empty_key(key)
                return val
            else:
                popped = []
                for _ in range(min(count, len(d))):
                    popped.append(d.pop())
                if len(d) == 0:
                    self._clean_empty_key(key)
                return popped

    def lrange(self, key: str, start: int, stop: int) -> List[str]:
        """LRANGE key start stop -> returns list elements in index range (0-indexed, inclusive)."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return []
            self._check_type(key, RedisType.LIST)
            d_list = list(self._data[key])
            n = len(d_list)
            if n == 0:
                return []

            # Handle negative indices
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
            if key not in self._data:
                return 0
            self._check_type(key, RedisType.LIST)
            return len(self._data[key])

    def lindex(self, key: str, index: int) -> Optional[str]:
        """LINDEX key index -> returns element at index."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return None
            self._check_type(key, RedisType.LIST)
            d_list = list(self._data[key])
            try:
                return d_list[index]
            except IndexError:
                return None

    def ltrim(self, key: str, start: int, stop: int) -> bool:
        """LTRIM key start stop -> trims list to specified range."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return True
            self._check_type(key, RedisType.LIST)
            trimmed = self.lrange(key, start, stop)
            if not trimmed:
                self.delete(key)
            else:
                self._data[key] = deque(trimmed)
                self._updated_at[key] = time.time()
            return True

    # ─────────────────────────────────────────────────────────────────────────
    # 4. SET OPERATIONS
    # ─────────────────────────────────────────────────────────────────────────
    def sadd(self, key: str, *members: Any) -> int:
        """SADD key member1 member2 ... -> returns count of newly added members."""
        with self._lock:
            self._cmd_count += 1
            self._check_type(key, RedisType.SET)
            now = time.time()
            if key not in self._data:
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
            return added

    def smembers(self, key: str) -> Set[str]:
        """SMEMBERS key -> returns set of all members."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return set()
            self._check_type(key, RedisType.SET)
            return set(self._data[key])

    def srem(self, key: str, *members: Any) -> int:
        """SREM key member1 member2 ... -> returns count of removed members."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
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
            if len(self._data[key]) == 0:
                self._clean_empty_key(key)
            return removed

    def sismember(self, key: str, member: Any) -> bool:
        """SISMEMBER key member -> returns True if member is in set."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return False
            self._check_type(key, RedisType.SET)
            return str(member) in self._data[key]

    def scard(self, key: str) -> int:
        """SCARD key -> returns number of elements in set."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return 0
            self._check_type(key, RedisType.SET)
            return len(self._data[key])

    def sinter(self, *keys: str) -> Set[str]:
        """SINTER key1 key2 ... -> returns intersection of sets."""
        with self._lock:
            self._cmd_count += 1
            if not keys:
                return set()
            sets = []
            for k in keys:
                if k not in self._data:
                    return set()
                self._check_type(k, RedisType.SET)
                sets.append(self._data[k])
            return set.intersection(*sets)

    def sunion(self, *keys: str) -> Set[str]:
        """SUNION key1 key2 ... -> returns union of sets."""
        with self._lock:
            self._cmd_count += 1
            res: Set[str] = set()
            for k in keys:
                if k in self._data:
                    self._check_type(k, RedisType.SET)
                    res.update(self._data[k])
            return res

    def sdiff(self, first_key: str, *other_keys: str) -> Set[str]:
        """SDIFF key1 key2 ... -> returns difference between first set and all successive sets."""
        with self._lock:
            self._cmd_count += 1
            if first_key not in self._data:
                return set()
            self._check_type(first_key, RedisType.SET)
            res = set(self._data[first_key])
            for k in other_keys:
                if k in self._data:
                    self._check_type(k, RedisType.SET)
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
            self._check_type(key, RedisType.ZSET)
            now = time.time()
            if key not in self._data:
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
            return added

    def _get_sorted_zset(self, key: str, reverse: bool = False) -> List[Tuple[str, float]]:
        """Internal helper sorting zset elements by (score ASC, member ASC)."""
        items = list(self._data[key].items())
        # Sort by score first, then lexicographically by member
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
            if key not in self._data:
                return []
            self._check_type(key, RedisType.ZSET)
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
            if key not in self._data:
                return []
            self._check_type(key, RedisType.ZSET)
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
            if key not in self._data:
                return []
            self._check_type(key, RedisType.ZSET)
            sorted_items = self._get_sorted_zset(key, reverse=False)
            filtered = [(m, s) for m, s in sorted_items if min_score <= s <= max_score]
            if withscores:
                return filtered
            return [m for m, s in filtered]

    def zrank(self, key: str, member: Any) -> Optional[int]:
        """ZRANK key member -> returns 0-indexed rank of member sorted ASC, or None."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return None
            self._check_type(key, RedisType.ZSET)
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
            if key not in self._data:
                return None
            self._check_type(key, RedisType.ZSET)
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
            if key not in self._data:
                return None
            self._check_type(key, RedisType.ZSET)
            return self._data[key].get(str(member))

    def zrem(self, key: str, *members: Any) -> int:
        """ZREM key member1 member2 ... -> returns count of removed members."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
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
            if len(self._data[key]) == 0:
                self._clean_empty_key(key)
            return removed

    def zcard(self, key: str) -> int:
        """ZCARD key -> returns number of members in sorted set."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return 0
            self._check_type(key, RedisType.ZSET)
            return len(self._data[key])

    def zcount(self, key: str, min_score: float, max_score: float) -> int:
        """ZCOUNT key min max -> returns count of members with scores within [min, max]."""
        with self._lock:
            self._cmd_count += 1
            if key not in self._data:
                return 0
            self._check_type(key, RedisType.ZSET)
            return sum(1 for s in self._data[key].values() if min_score <= s <= max_score)

    # ─────────────────────────────────────────────────────────────────────────
    # 6. GENERIC KEY OPERATIONS & METRICS
    # ─────────────────────────────────────────────────────────────────────────
    def _clean_empty_key(self, key: str) -> None:
        """Removes key from store when container becomes empty."""
        if key in self._data:
            del self._data[key]
        if key in self._types:
            del self._types[key]
        if key in self._created_at:
            del self._created_at[key]
        if key in self._updated_at:
            del self._updated_at[key]

    def delete(self, *keys: str) -> int:
        """DEL key1 key2 ... -> returns count of deleted keys."""
        with self._lock:
            self._cmd_count += 1
            deleted = 0
            for k in keys:
                if k in self._data:
                    del self._data[k]
                    self._types.pop(k, None)
                    self._created_at.pop(k, None)
                    self._updated_at.pop(k, None)
                    deleted += 1
            return deleted

    def exists(self, *keys: str) -> int:
        """EXISTS key1 key2 ... -> returns count of keys that exist."""
        with self._lock:
            self._cmd_count += 1
            return sum(1 for k in keys if k in self._data)

    def type(self, key: str) -> RedisType:
        """TYPE key -> returns RedisType."""
        with self._lock:
            self._cmd_count += 1
            return self._types.get(key, RedisType.NONE)

    def keys(self, pattern: str = "*") -> List[str]:
        """KEYS pattern -> returns keys matching glob pattern."""
        with self._lock:
            self._cmd_count += 1
            if pattern == "*":
                return list(self._data.keys())
            return [k for k in self._data.keys() if fnmatch.fnmatch(k, pattern)]

    def flushdb(self) -> bool:
        """FLUSHDB -> deletes all keys from database."""
        with self._lock:
            self._cmd_count += 1
            self._data.clear()
            self._types.clear()
            self._created_at.clear()
            self._updated_at.clear()
            return True

    def dbsize(self) -> int:
        """DBSIZE -> returns total number of keys."""
        with self._lock:
            return len(self._data)

    def stats(self) -> Dict[str, Any]:
        """Returns comprehensive stats for monitoring."""
        with self._lock:
            type_counts = {}
            for t in RedisType:
                if t != RedisType.NONE:
                    type_counts[t.value] = sum(1 for v in self._types.values() if v == t)

            return {
                "total_keys": len(self._data),
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
