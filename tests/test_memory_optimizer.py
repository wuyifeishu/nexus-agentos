"""Tests for agentos.tools.memory_optimizer."""

import time

from agentos.tools.memory_optimizer import (
    LRUCache,
    MemoryMonitor,
    ObjectPool,
    SmartCache,
    create_lru_cache,
    create_object_pool,
    create_smart_cache,
    get_memory_monitor,
)

# ============================================================================
# ObjectPool Tests
# ============================================================================

class TestObjectPool:
    def test_acquire_release(self):
        pool = ObjectPool(list, max_size=10, max_idle=5)
        obj = pool.acquire()
        assert isinstance(obj, list)
        assert pool.stats["borrowed"] == 1
        pool.release(obj)
        assert pool.stats["returned"] == 1
        assert pool.stats["idle"] == 1

    def test_reuse(self):
        pool = ObjectPool(list, max_size=10, max_idle=5)
        obj1 = pool.acquire()
        pool.release(obj1)
        obj2 = pool.acquire()
        assert obj1 is obj2  # same object reused

    def test_max_size(self):
        count = 0
        def factory():
            nonlocal count
            count += 1
            return {}
        pool = ObjectPool(factory, max_size=5, max_idle=2)
        objs = [pool.acquire() for _ in range(8)]
        # pool tracks up to max_size; excess acquires create temp objects
        assert count >= 5
        for o in objs:
            pool.release(o)
        assert pool.stats["idle"] <= pool._max_idle

    def test_factory(self):
        pool = ObjectPool(lambda: {"a": 1}, max_size=5)
        obj = pool.acquire()
        assert obj == {"a": 1}

    def test_idle_timeout_eviction(self):
        pool = ObjectPool(list, max_size=10, max_idle=5, idle_timeout=0.01)
        obj = pool.acquire()
        pool.release(obj)
        time.sleep(0.02)
        obj2 = pool.acquire()
        assert obj is not obj2  # expired, new object created


# ============================================================================
# LRUCache Tests
# ============================================================================

class TestLRUCache:
    def test_basic_get_put(self):
        cache = LRUCache[str](capacity=10)
        cache.put("a", "alpha")
        assert cache.get("a") == "alpha"
        assert cache.get("b") is None

    def test_eviction_on_capacity(self):
        cache = LRUCache[int](capacity=3)
        for i in range(5):
            cache.put(f"k{i}", i)
        assert cache.get("k0") is None  # evicted
        assert cache.get("k1") is None  # evicted
        assert cache.get("k2") == 2
        assert cache.get("k3") == 3
        assert cache.get("k4") == 4

    def test_move_to_end_on_get(self):
        cache = LRUCache[int](capacity=3)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        cache.get("a")  # touch a, moves to end
        cache.put("d", 4)  # should evict b
        assert cache.get("a") == 1
        assert cache.get("b") is None
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_ttl_expiry(self):
        cache = LRUCache[int](capacity=10, ttl=0.01)
        cache.put("a", 1)
        assert cache.get("a") == 1
        time.sleep(0.02)
        assert cache.get("a") is None

    def test_remove(self):
        cache = LRUCache[int](capacity=10)
        cache.put("a", 1)
        assert cache.remove("a") is True
        assert cache.get("a") is None
        assert cache.remove("b") is False

    def test_clear(self):
        cache = LRUCache[int](capacity=10)
        for i in range(5):
            cache.put(f"k{i}", i)
        cache.clear()
        assert len(cache) == 0

    def test_stats(self):
        cache = LRUCache[int](capacity=10)
        cache.put("a", 1)
        cache.get("a")
        cache.get("b")
        stats = cache.stats
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["size"] == 1
        assert 0.4 <= stats["hit_rate"] <= 0.6

    def test_contains(self):
        cache = LRUCache[int](capacity=10)
        cache.put("x", 100)
        assert "x" in cache
        assert "y" not in cache

    def test_update_existing(self):
        cache = LRUCache[int](capacity=10)
        cache.put("a", 1)
        cache.put("a", 2)
        assert cache.get("a") == 2
        assert len(cache) == 1


# ============================================================================
# SmartCache Tests
# ============================================================================

class TestSmartCache:
    def test_get_compute_on_miss(self):
        calls = []
        def compute(k):
            calls.append(k)
            return k.upper()
        cache = SmartCache(compute, capacity=10)
        assert cache.get("hello") == "HELLO"
        assert calls == ["hello"]
        assert cache.get("hello") == "HELLO"  # from cache
        assert calls == ["hello"]  # no new calls

    def test_prefetch(self):
        compute_count = 0
        def compute(k):
            nonlocal compute_count
            compute_count += 1
            return int(k) * 2
        cache = SmartCache(compute, capacity=10)
        count = cache.prefetch(["1", "2", "3", "1"])  # "1" duplicate
        assert count == 3
        assert cache.get("1") == 2
        assert cache.get("2") == 4
        assert cache.get("3") == 6

    def test_invalidate(self):
        def compute(k):
            return k.upper()
        cache = SmartCache(compute, capacity=10)
        cache.get("a")
        assert cache.invalidate("a") is True
        assert cache.invalidate("a") is False  # already gone

    def test_invalidate_pattern(self):
        def compute(k):
            return k
        cache = SmartCache(compute, capacity=20)
        for k in ["user:1", "user:2", "post:1", "post:2"]:
            cache.get(k)
        removed = cache.invalidate_pattern("user:")
        assert removed == 2
        assert cache.get("user:1") == "user:1"  # recomputed
        assert cache.get("post:1") == "post:1"  # still cached

    def test_clear(self):
        def compute(k):
            return k
        cache = SmartCache(compute, capacity=10)
        cache.get("a")
        cache.get("b")
        cache.clear()
        assert len(cache) == 0

    def test_thread_safety(self):
        import threading
        results = []
        def compute(k):
            import time
            time.sleep(0.02)
            return k * 2
        cache = SmartCache(compute, capacity=10)

        def worker():
            results.append(cache.get("shared"))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert all(r == "sharedshared" for r in results)


# ============================================================================
# MemoryMonitor Tests
# ============================================================================

class TestMemoryMonitor:
    def test_singleton(self):
        m1 = MemoryMonitor()
        m2 = MemoryMonitor()
        assert m1 is m2

    def test_register_and_metrics(self):
        monitor = get_memory_monitor()
        monitor.register("test_comp")
        monitor.record_alloc("test_comp", 1024)
        monitor.record_alloc("test_comp", 512)
        monitor.record_free("test_comp", 256)
        snapshot = monitor.snapshot()
        comp = snapshot["test_comp"]
        assert comp["current_bytes"] == 1280
        assert comp["peak_bytes"] == 1536
        assert comp["total_allocations"] == 2

    def test_alert(self):
        monitor = get_memory_monitor()
        monitor.register("alert_test")
        monitor.record_alloc("alert_test", 5000)
        assert monitor.alert("alert_test", 1000) is True
        assert monitor.alert("alert_test", 10000) is False

    def test_total_current(self):
        monitor = get_memory_monitor()
        name_a = f"tc_a_{id(self)}"
        name_b = f"tc_b_{id(self)}"
        monitor.register(name_a)
        monitor.register(name_b)
        monitor.record_alloc(name_a, 100)
        monitor.record_alloc(name_b, 200)
        assert monitor.snapshot()[name_a]["current_bytes"] + monitor.snapshot()[name_b]["current_bytes"] == 300

    def test_peak_correct_on_free(self):
        monitor = get_memory_monitor()
        monitor.register("pk")
        monitor.record_alloc("pk", 1000)
        monitor.record_free("pk", 200)
        monitor.record_alloc("pk", 300)
        snapshot = monitor.snapshot()
        assert snapshot["pk"]["peak_bytes"] == 1100


# ============================================================================
# Convenience Functions Tests
# ============================================================================

class TestConvenienceFunctions:
    def test_create_object_pool(self):
        pool = create_object_pool(dict, max_size=5)
        obj = pool.acquire()
        assert isinstance(obj, dict)
        pool.release(obj)

    def test_create_lru_cache(self):
        cache = create_lru_cache(capacity=5, ttl=60)
        cache.put("k", "v")
        assert cache.get("k") == "v"

    def test_create_smart_cache(self):
        cache = create_smart_cache(lambda k: f"val-{k}", capacity=5)
        assert cache.get("x") == "val-x"

    def test_get_memory_monitor(self):
        m1 = get_memory_monitor()
        m2 = get_memory_monitor()
        assert m1 is m2
