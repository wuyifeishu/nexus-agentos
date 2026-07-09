"""Tests for agentos.tools.startup_accelerator."""

import time

import pytest

from agentos.tools.startup_accelerator import (
    LazyLoader,
    ModulePreloader,
    StartupOptimizer,
    _LazyModule,
    create_lazy_loader,
    create_module_preloader,
    create_startup_optimizer,
    quick_start,
)

# ============================================================================
# LazyLoader Tests
# ============================================================================

class TestLazyLoader:
    def test_register_and_load(self):
        loader = LazyLoader()
        proxy = loader.register("json")
        assert "json" in loader._proxies
        assert proxy._module is None  # not loaded yet
        dumps = proxy.dumps
        assert proxy._module is not None  # loaded on access
        assert dumps({"a": 1}) == '{"a": 1}'

    def test_lazy_attribute_access(self):
        loader = LazyLoader()
        proxy = loader.register("math")
        assert proxy.sqrt(4) == 2.0

    def test_load_now(self):
        loader = LazyLoader()
        loader.register("json")
        module = loader.load_now("json")
        assert module.__name__ == "json"

    def test_load_all(self):
        loader = LazyLoader()
        for m in ["json", "math", "collections"]:
            loader.register(m)
        results = loader.load_all()
        assert len(results) == 3
        for name, elapsed in results:
            assert isinstance(name, str)
            assert elapsed >= 0

    def test_preload(self):
        loader = LazyLoader()
        results = loader.preload(["json", "math"])
        assert len(results) == 2
        proxy = loader["json"]
        assert proxy._module is not None

    def test_stats(self):
        loader = LazyLoader()
        loader.preload(["json"])
        loader.register("os")
        stats = loader.stats
        assert stats["registered"] == 2
        assert stats["loaded"] == 1
        assert stats["unloaded"] == 1
        assert "json" in stats["load_times"]

    def test_getitem(self):
        loader = LazyLoader()
        loader["json"]  # register via []
        loader["json"]  # same, no re-create
        assert len(loader._proxies) == 1

    def test_repr(self):
        proxy = _LazyModule("missing_module_xyz")
        assert "unloaded" in repr(proxy)

    def test_load_failure(self):
        loader = LazyLoader()
        proxy = loader.register("nonexistent_module_abc_123")
        with pytest.raises(ModuleNotFoundError):
            _ = proxy.something


# ============================================================================
# ModulePreloader Tests
# ============================================================================

class TestModulePreloader:
    def test_precompile_sequential(self):
        preloader = ModulePreloader(max_concurrent=1)
        results = preloader.precompile(["json", "math", "collections"], parallel=False)
        assert len(results) == 3
        for name, elapsed in results.items():
            assert elapsed >= 0

    def test_precompile_parallel(self):
        preloader = ModulePreloader(max_concurrent=4)
        results = preloader.precompile(["json", "math", "collections", "functools"], parallel=True)
        assert len(results) == 4

    def test_get(self):
        preloader = ModulePreloader()
        preloader.precompile(["json"], parallel=False)
        mod = preloader.get("json")
        assert mod is not None
        assert mod.__name__ == "json"
        assert preloader.get("nonexistent") is None

    def test_warm_cache(self):
        preloader = ModulePreloader()
        count = preloader.warm_cache(["json", "math", "json"])  # json duplicate
        assert count == 2
        assert preloader.get("json") is not None

    def test_clear(self):
        preloader = ModulePreloader()
        preloader.precompile(["json"], parallel=False)
        assert len(preloader._cache) == 1
        preloader.clear()
        assert len(preloader._cache) == 0

    def test_stats(self):
        preloader = ModulePreloader()
        preloader.precompile(["json"], parallel=False)
        stats = preloader.stats
        assert stats["cached_modules"] == 1
        assert stats["total_preload_time"] >= 0


# ============================================================================
# StartupOptimizer Tests
# ============================================================================

class TestStartupOptimizer:
    def test_basic_profile(self):
        opt = StartupOptimizer()
        opt.start()
        opt.begin_phase("init_config")
        time.sleep(0.02)
        opt.end_phase("init_config")
        opt.begin_phase("load_plugins")
        time.sleep(0.03)
        opt.end_phase("load_plugins")
        opt.end()
        report = opt.report()
        assert report["phase_count"] == 2
        assert report["total_duration_ms"] > 0
        assert report["bottleneck"] in ("init_config", "load_plugins")
        assert len(report["phases"]) == 2

    def test_duration_ms(self):
        opt = StartupOptimizer()
        opt.start()
        opt.begin_phase("test")
        time.sleep(0.05)
        opt.end_phase("test")
        opt.end()
        assert opt.total_duration_ms() >= 50

    def test_phase_metadata(self):
        opt = StartupOptimizer()
        opt.start()
        opt.begin_phase("db_connect", db_type="postgres", pool_size=10)
        time.sleep(0.01)
        opt.end_phase("db_connect")
        opt.end()
        report = opt.report()
        phase = [p for p in report["phases"] if p["name"] == "db_connect"][0]
        assert phase["db_type"] == "postgres"
        assert phase["pool_size"] == 10

    def test_bottleneck_correct(self):
        opt = StartupOptimizer()
        opt.start()
        opt.begin_phase("fast")
        time.sleep(0.02)
        opt.end_phase("fast")
        opt.begin_phase("slow")
        time.sleep(0.1)
        opt.end_phase("slow")
        opt.end()
        report = opt.report()
        assert report["bottleneck"] == "slow"

    def test_empty_report(self):
        opt = StartupOptimizer()
        opt.start()
        opt.end()
        report = opt.report()
        assert report["phase_count"] == 0
        assert report["bottleneck"] is None


# ============================================================================
# Convenience Functions Tests
# ============================================================================

class TestConvenienceFunctions:
    def test_create_lazy_loader(self):
        loader = create_lazy_loader()
        assert isinstance(loader, LazyLoader)

    def test_create_module_preloader(self):
        preloader = create_module_preloader(max_concurrent=2)
        assert isinstance(preloader, ModulePreloader)

    def test_create_startup_optimizer(self):
        opt = create_startup_optimizer()
        assert isinstance(opt, StartupOptimizer)

    def test_quick_start(self):
        result = quick_start(
            essential_modules=["json", "math"],
            lazy_modules=["os", "sys"],
            hot_modules=["collections"],
        )
        assert "json" in result["essential"]
        assert "math" in result["essential"]
        assert result["lazy_count"] == 2
        assert result["cached_total"] >= 2
        assert result["total_essential_ms"] >= 0
