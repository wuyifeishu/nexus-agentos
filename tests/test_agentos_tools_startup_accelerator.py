"""Tests for agentos.tools.startup_accelerator — LazyLoader, ModulePreloader, StartupOptimizer."""

import time

from agentos.tools.startup_accelerator import (
    LazyLoader,
    ModulePreloader,
    StartupOptimizer,
    create_lazy_loader,
    create_module_preloader,
    create_startup_optimizer,
    quick_start,
)

# ============================================================================
# LazyLoader
# ============================================================================

class TestLazyLoader:
    def test_register_returns_proxy(self):
        ll = LazyLoader()
        proxy = ll.register("json")
        assert str(proxy).startswith("<LazyModule: json")

    def test_access_triggers_load(self):
        ll = LazyLoader()
        proxy = ll.register("json")
        d = proxy.dumps({"a": 1})
        assert '"a"' in d

    def test_repr_unloaded(self):
        ll = LazyLoader()
        proxy = ll.register("nonexistent_zzz")
        assert "unloaded" in repr(proxy)

    def test_repr_loaded(self):
        ll = LazyLoader()
        proxy = ll.register("json")
        proxy._load()
        assert "module" in repr(proxy)

    def test_load_now(self):
        ll = LazyLoader()
        mod = ll.load_now("json")
        assert hasattr(mod, "dumps")

    def test_load_all(self):
        ll = LazyLoader()
        ll.register("json")
        ll.register("math")
        results = ll.load_all()
        assert len(results) >= 2
        for name, t in results:
            assert t > 0

    def test_preload(self):
        ll = LazyLoader()
        results = ll.preload(["json", "math"])
        assert len(results) == 2
        for name, t in results:
            assert t > 0

    def test_stats(self):
        ll = LazyLoader()
        ll.register("json")
        ll.register("math")
        ll.load_now("json")
        st = ll.stats
        assert st["registered"] == 2
        assert st["loaded"] == 1
        assert st["unloaded"] == 1

    def test_getitem(self):
        ll = LazyLoader()
        proxy = ll["json"]
        assert proxy.dumps({"x": 1}) == '{"x": 1}'

    def test_double_register_same_proxy(self):
        ll = LazyLoader()
        p1 = ll.register("json")
        p2 = ll.register("json")
        assert p1 is p2


# ============================================================================
# ModulePreloader
# ============================================================================

class TestModulePreloader:
    def test_precompile_single(self):
        mp = ModulePreloader()
        results = mp.precompile(["json"], parallel=False)
        assert "json" in results
        assert results["json"] > 0

    def test_precompile_parallel(self):
        mp = ModulePreloader(max_concurrent=4)
        mods = ["json", "math", "re", "os"]
        results = mp.precompile(mods, parallel=True)
        assert len(results) == 4

    def test_get(self):
        mp = ModulePreloader()
        mp.precompile(["json"])
        assert mp.get("json") is not None
        assert mp.get("nope") is None

    def test_warm_cache(self):
        mp = ModulePreloader()
        count = mp.warm_cache(["json", "math"])
        assert count == 2
        # second call should not re-add
        count2 = mp.warm_cache(["json", "math", "os"])
        assert count2 == 1

    def test_warm_cache_handles_errors(self):
        mp = ModulePreloader()
        count = mp.warm_cache(["no_such_module_xyz_999"])
        assert count == 0

    def test_clear(self):
        mp = ModulePreloader()
        mp.warm_cache(["json"])
        assert mp.get("json") is not None
        mp.clear()
        assert mp.get("json") is None

    def test_stats(self):
        mp = ModulePreloader()
        mp.precompile(["json", "math"])
        st = mp.stats
        assert st["cached_modules"] >= 2
        assert "total_preload_time" in st


# ============================================================================
# StartupOptimizer
# ============================================================================

class TestStartupOptimizer:
    def test_phase_timing(self):
        so = StartupOptimizer()
        so.start()
        so.begin_phase("init_db")
        time.sleep(0.01)
        so.end_phase("init_db")
        so.end()
        report = so.report()
        assert report["total_duration_ms"] > 0
        assert report["phase_count"] == 1
        assert len(report["phases"]) == 1
        assert report["phases"][0]["name"] == "init_db"
        assert report["bottleneck"] == "init_db"

    def test_multiple_phases(self):
        so = StartupOptimizer()
        so.start()
        so.begin_phase("a")
        time.sleep(0.01)
        so.end_phase("a")
        so.begin_phase("b")
        time.sleep(0.02)
        so.end_phase("b")
        so.begin_phase("c")
        time.sleep(0.005)
        so.end_phase("c")
        so.end()
        report = so.report()
        assert report["phase_count"] == 3
        phases = report["phases"]
        # sorted by duration desc
        assert phases[0]["name"] == "b"
        assert phases[0]["pct_of_total"] > 0

    def test_end_phase_missing(self):
        so = StartupOptimizer()
        assert so.end_phase("phantom") is None

    def test_total_duration_ms(self):
        so = StartupOptimizer()
        so.start()
        time.sleep(0.01)
        so.end()
        assert so.total_duration_ms() > 0

    def test_empty_report(self):
        so = StartupOptimizer()
        so.start()
        so.end()
        report = so.report()
        assert report["total_duration_ms"] >= 0
        assert report["bottleneck"] is None

    def test_phase_metadata(self):
        so = StartupOptimizer()
        so.start()
        so.begin_phase("config", mode="lazy")
        so.end_phase("config")
        so.end()
        report = so.report()
        assert report["phases"][0]["mode"] == "lazy"


# ============================================================================
# Convenience Functions
# ============================================================================

class TestConvenience:
    def test_create_lazy_loader(self):
        assert isinstance(create_lazy_loader(), LazyLoader)

    def test_create_module_preloader(self):
        mp = create_module_preloader(max_concurrent=2)
        assert isinstance(mp, ModulePreloader)

    def test_create_startup_optimizer(self):
        assert isinstance(create_startup_optimizer(), StartupOptimizer)

    def test_quick_start(self):
        result = quick_start(
            essential_modules=["json", "math"],
            lazy_modules=["re", "os"],
            hot_modules=["time"],
        )
        assert "essential" in result
        assert result["lazy_count"] == 2
        assert result["cached_total"] >= 3
        assert result["total_essential_ms"] > 0
