"""Tests for agentos.tools.startup_accelerator — LazyLoader, ModulePreloader, StartupOptimizer."""

import threading
import time

import pytest

from agentos.tools.startup_accelerator import (
    LazyLoader,
    ModulePreloader,
    StartupOptimizer,
    _LazyModule,
    _StartupPhase,
    create_lazy_loader,
    create_module_preloader,
    create_startup_optimizer,
    quick_start,
)

# ============================================================================
# _LazyModule
# ============================================================================

class TestLazyModule:
    def test_initial_state(self):
        lm = _LazyModule("os")
        assert lm._module_name == "os"
        assert lm._module is None

    def test_repr_unloaded(self):
        lm = _LazyModule("nonexistent")
        r = repr(lm)
        assert "nonexistent" in r
        assert "unloaded" in r

    def test_repr_loaded(self):
        lm = _LazyModule("os")
        lm._load()
        r = repr(lm)
        assert "unloaded" not in r

    def test_deferred_load(self):
        lm = _LazyModule("os")
        assert lm._module is None
        # Access an attribute triggers load
        _ = lm.path
        assert lm._module is not None

    def test_getattr_attribute(self):
        lm = _LazyModule("json")
        assert lm.dumps({"k": 1}) == '{"k": 1}'

    def test_load_caches(self):
        lm = _LazyModule("os")
        m1 = lm._load()
        m2 = lm._load()
        assert m1 is m2


# ============================================================================
# LazyLoader
# ============================================================================

class TestLazyLoader:
    def test_register_new(self):
        ll = LazyLoader()
        proxy = ll.register("os")
        assert isinstance(proxy, _LazyModule)
        assert proxy._module is None

    def test_register_idempotent(self):
        ll = LazyLoader()
        p1 = ll.register("json")
        p2 = ll.register("json")
        assert p1 is p2

    def test_getitem(self):
        ll = LazyLoader()
        proxy = ll["os"]
        assert proxy._module_name == "os"

    def test_load_now(self):
        ll = LazyLoader()
        ll.register("json")
        mod = ll.load_now("json")
        assert hasattr(mod, "dumps")

    def test_load_now_returns_module(self):
        ll = LazyLoader()
        mod = ll.load_now("os")
        assert hasattr(mod, "path")

    def test_load_all(self):
        ll = LazyLoader()
        ll.register("json")
        ll.register("os")
        results = ll.load_all()
        assert len(results) == 2
        for name, elapsed in results:
            assert elapsed >= 0

    def test_preload(self):
        ll = LazyLoader()
        modules = ["json", "os"]
        results = ll.preload(modules)
        assert len(results) == 2
        for name, elapsed in results:
            assert elapsed >= 0

    def test_stats(self):
        ll = LazyLoader()
        ll.register("json")
        ll.register("os")
        ll.load_now("json")
        s = ll.stats
        assert s["registered"] == 2
        assert s["loaded"] == 1
        assert s["unloaded"] == 1
        assert "json" in s["load_times"]
        assert isinstance(s["total_load_time"], float)

    def test_stats_all_unloaded(self):
        ll = LazyLoader()
        assert ll.stats["registered"] == 0
        assert ll.stats["loaded"] == 0

    def test_thread_safety(self):
        ll = LazyLoader()
        errors = []

        def worker(name):
            try:
                ll.register(name)
                ll.load_now(name)
                _ = ll.stats
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=("os",)) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0


# ============================================================================
# ModulePreloader
# ============================================================================

class TestModulePreloader:
    def test_defaults(self):
        mp = ModulePreloader()
        assert mp._max_concurrent == 4

    def test_custom_concurrent(self):
        mp = ModulePreloader(max_concurrent=2)
        assert mp._max_concurrent == 2

    def test_precompile_serial(self):
        mp = ModulePreloader(max_concurrent=1)
        results = mp.precompile(["json", "os"], parallel=False)
        assert len(results) == 2
        assert "json" in results
        assert results["json"] >= 0

    def test_precompile_parallel(self):
        mp = ModulePreloader()
        results = mp.precompile(["json", "os", "sys"], parallel=True)
        assert len(results) == 3

    def test_precompile_single(self):
        mp = ModulePreloader()
        results = mp.precompile(["json"], parallel=True)
        assert len(results) == 1

    def test_get(self):
        mp = ModulePreloader()
        mp.precompile(["json"], parallel=False)
        mod = mp.get("json")
        assert mod is not None
        assert hasattr(mod, "dumps")

    def test_get_missing(self):
        mp = ModulePreloader()
        assert mp.get("nonexistent_mod_12345") is None

    def test_warm_cache(self):
        mp = ModulePreloader()
        count = mp.warm_cache(["json", "os"])
        assert count == 2
        # Second warm should not re-cache
        count2 = mp.warm_cache(["json", "os"])
        assert count2 == 0

    def test_warm_cache_handles_errors(self):
        mp = ModulePreloader()
        count = mp.warm_cache(["nonexistent_mod_12345"])
        assert count == 0

    def test_clear(self):
        mp = ModulePreloader()
        mp.precompile(["json"], parallel=False)
        assert mp.get("json") is not None
        mp.clear()
        assert mp.get("json") is None

    def test_stats(self):
        mp = ModulePreloader()
        mp.precompile(["json", "os"], parallel=True)
        s = mp.stats
        assert s["cached_modules"] == 2
        assert isinstance(s["total_preload_time"], float)
        assert len(s["module_times"]) == 2

    def test_stats_empty(self):
        mp = ModulePreloader()
        s = mp.stats
        assert s["cached_modules"] == 0

    def test_precompile_parallel_batching(self):
        mp = ModulePreloader(max_concurrent=2)
        results = mp.precompile(["json", "os", "sys", "time"], parallel=True)
        assert len(results) == 4

    def test_precompile_invalid_module(self):
        mp = ModulePreloader()
        # parallel requires >1 modules to actually use thread pool
        results = mp.precompile(["json", "this_module_does_not_exist_123"], parallel=True)
        assert "json" in results
        assert "this_module_does_not_exist_123" not in results

    def test_precompile_invalid_module_serial_raises(self):
        mp = ModulePreloader()
        with pytest.raises(ModuleNotFoundError):
            mp.precompile(["this_module_does_not_exist_123"], parallel=False)


# ============================================================================
# StartupOptimizer
# ============================================================================

class TestStartupOptimizer:
    def test_start_and_end(self):
        so = StartupOptimizer()
        so.start()
        time.sleep(0.01)
        so.end()
        assert so.total_duration_ms() > 0

    def test_begin_end_phase(self):
        so = StartupOptimizer()
        so.start()
        so.begin_phase("init")
        time.sleep(0.01)
        duration = so.end_phase("init")
        so.end()
        assert duration is not None
        assert duration > 0

    def test_end_phase_missing(self):
        so = StartupOptimizer()
        assert so.end_phase("nonexistent") is None

    def test_begin_phase_with_metadata(self):
        so = StartupOptimizer()
        so.start()
        so.begin_phase("db", target="postgres")
        so.end_phase("db")
        so.end()
        report = so.report()
        phases = report["phases"]
        db_phase = [p for p in phases if p["name"] == "db"][0]
        assert db_phase["target"] == "postgres"

    def test_report_structure(self):
        so = StartupOptimizer()
        so.start()
        so.begin_phase("a")
        so.end_phase("a")
        so.begin_phase("b")
        so.end_phase("b")
        so.end()
        r = so.report()
        assert "total_duration_ms" in r
        assert "phase_count" in r
        assert "phases" in r
        assert "bottleneck" in r
        assert r["phase_count"] == 2
        assert isinstance(r["total_duration_ms"], float)

    def test_report_bottleneck(self):
        so = StartupOptimizer()
        so.start()
        so.begin_phase("fast")
        so.end_phase("fast")
        so.begin_phase("slow")
        time.sleep(0.02)
        so.end_phase("slow")
        so.end()
        r = so.report()
        assert r["bottleneck"] == "slow"

    def test_report_empty(self):
        so = StartupOptimizer()
        so.start()
        so.end()
        r = so.report()
        assert r["phase_count"] == 0
        assert r["bottleneck"] is None

    def test_phases_sorted_by_duration(self):
        so = StartupOptimizer()
        so.start()
        so.begin_phase("medium")
        time.sleep(0.01)
        so.end_phase("medium")
        so.begin_phase("fast")
        so.end_phase("fast")
        so.end()
        r = so.report()
        durations = [p["duration_ms"] for p in r["phases"]]
        assert durations == sorted(durations, reverse=True)

    def test_pct_of_total(self):
        so = StartupOptimizer()
        so.start()
        so.begin_phase("a")
        time.sleep(0.01)
        so.end_phase("a")
        so.end()
        r = so.report()
        for p in r["phases"]:
            assert 0 <= p["pct_of_total"] <= 100

    def test_total_duration_ms(self):
        so = StartupOptimizer()
        so.start()
        time.sleep(0.01)
        so.end()
        assert so.total_duration_ms() > 0

    def test_total_duration_ms_before_end(self):
        so = StartupOptimizer()
        so.start()
        # Accessing before end returns some value (may be negative)
        d = so.total_duration_ms()
        assert isinstance(d, float)

    def test_thread_safety(self):
        so = StartupOptimizer()
        so.start()
        errors = []

        def worker(idx):
            try:
                so.begin_phase(f"p{idx}")
                so.end_phase(f"p{idx}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        so.end()
        assert len(errors) == 0


# ============================================================================
# _StartupPhase
# ============================================================================

class TestStartupPhase:
    def test_duration(self):
        sp = _StartupPhase(name="test", start_time=0.0, end_time=5.0)
        assert sp.duration == 5.0

    def test_name(self):
        sp = _StartupPhase(name="init")
        assert sp.name == "init"

    def test_default_metadata(self):
        sp = _StartupPhase(name="x")
        assert sp.metadata == {}


# ============================================================================
# Convenience Functions
# ============================================================================

class TestConvenience:
    def test_create_lazy_loader(self):
        ll = create_lazy_loader()
        assert isinstance(ll, LazyLoader)

    def test_create_module_preloader(self):
        mp = create_module_preloader(max_concurrent=8)
        assert isinstance(mp, ModulePreloader)
        assert mp._max_concurrent == 8

    def test_create_module_preloader_default(self):
        mp = create_module_preloader()
        assert mp._max_concurrent == 4

    def test_create_startup_optimizer(self):
        so = create_startup_optimizer()
        assert isinstance(so, StartupOptimizer)

    def test_quick_start(self):
        result = quick_start(
            essential_modules=["json"],
            lazy_modules=["os"],
            hot_modules=["sys"],
        )
        assert "essential" in result
        assert result["lazy_count"] == 1
        assert result["cached_total"] == 2
        assert "total_essential_ms" in result

    def test_quick_start_no_hot_modules(self):
        result = quick_start(
            essential_modules=["json"],
            lazy_modules=["os"],
        )
        assert result["cached_total"] == 1
