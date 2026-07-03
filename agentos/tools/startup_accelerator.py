"""
Startup Acceleration Tools for AgentOS.
Lazy loading, module pre-compilation, and startup sequence optimization.
"""

import importlib
import threading
import time
import types
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


# ============================================================================
# LazyLoader
# ============================================================================

class _LazyModule:
    """Proxy that defers module import until an attribute is accessed."""

    def __init__(self, module_name: str):
        self._module_name = module_name
        self._module: Optional[types.ModuleType] = None

    def _load(self) -> types.ModuleType:
        if self._module is None:
            self._module = importlib.import_module(self._module_name)
        return self._module

    def __getattr__(self, name: str) -> Any:
        return getattr(self._load(), name)

    def __repr__(self) -> str:
        if self._module is None:
            return f"<LazyModule: {self._module_name} (unloaded)>"
        return repr(self._module)


class LazyLoader:
    """Registry for lazy-loaded modules with batch loading and dependency tracking."""

    def __init__(self):
        self._proxies: Dict[str, _LazyModule] = {}
        self._load_times: Dict[str, float] = {}
        self._lock = threading.Lock()

    def register(self, module_name: str) -> _LazyModule:
        """Register a module for lazy loading."""
        with self._lock:
            if module_name not in self._proxies:
                self._proxies[module_name] = _LazyModule(module_name)
            return self._proxies[module_name]

    def load_now(self, module_name: str) -> types.ModuleType:
        """Eagerly load a registered module."""
        proxy = self.register(module_name)
        with self._lock:
            start = time.perf_counter()
            result = proxy._load()
            elapsed = time.perf_counter() - start
            self._load_times[module_name] = elapsed
            return result

    def load_all(self) -> List[Tuple[str, float]]:
        """Eagerly load all registered modules. Returns load times."""
        results: List[Tuple[str, float]] = []
        for name in list(self._proxies.keys()):
            start = time.perf_counter()
            self._proxies[name]._load()
            elapsed = time.perf_counter() - start
            self._load_times[name] = elapsed
            results.append((name, elapsed))
        return results

    def preload(self, module_names: List[str]) -> List[Tuple[str, float]]:
        """Register and load a batch of modules."""
        for name in module_names:
            self.register(name)
        results: List[Tuple[str, float]] = []
        for name in module_names:
            start = time.perf_counter()
            self._proxies[name]._load()
            elapsed = time.perf_counter() - start
            self._load_times[name] = elapsed
            results.append((name, elapsed))
        return results

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            loaded = {k: v for k, v in self._proxies.items() if v._module is not None}
            return {
                "registered": len(self._proxies),
                "loaded": len(loaded),
                "unloaded": len(self._proxies) - len(loaded),
                "load_times": dict(self._load_times),
                "total_load_time": sum(self._load_times.values()),
            }

    def __getitem__(self, module_name: str) -> _LazyModule:
        return self.register(module_name)


# ============================================================================
# ModulePreloader
# ============================================================================

class ModulePreloader:
    """Pre-compile and cache frequently used modules for fast startup."""

    def __init__(self, max_concurrent: int = 4):
        self._cache: Dict[str, types.ModuleType] = {}
        self._max_concurrent = max_concurrent
        self._lock = threading.Lock()
        self._preload_times: Dict[str, float] = {}

    def precompile(self, module_names: List[str], parallel: bool = True) -> Dict[str, float]:
        """Pre-compile a list of modules, optionally in parallel."""
        results: Dict[str, float] = {}

        if parallel and len(module_names) > 1:
            results = self._precompile_parallel(module_names)
        else:
            for name in module_names:
                start = time.perf_counter()
                self._cache[name] = importlib.import_module(name)
                elapsed = time.perf_counter() - start
                results[name] = elapsed

        self._preload_times.update(results)
        return results

    def _precompile_parallel(self, module_names: List[str]) -> Dict[str, float]:
        results: Dict[str, float] = {}
        errors: List[str] = []

        def _worker(name: str) -> None:
            try:
                start = time.perf_counter()
                module = importlib.import_module(name)
                elapsed = time.perf_counter() - start
                with self._lock:
                    self._cache[name] = module
                    results[name] = elapsed
            except Exception as e:
                errors.append(f"{name}: {e}")

        # Batch into groups
        for i in range(0, len(module_names), self._max_concurrent):
            batch = module_names[i:i + self._max_concurrent]
            threads = [threading.Thread(target=_worker, args=(name,)) for name in batch]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        return results

    def get(self, module_name: str) -> Optional[types.ModuleType]:
        return self._cache.get(module_name)

    def warm_cache(self, hot_modules: List[str]) -> int:
        """Preload hot modules into cache. Returns number newly cached."""
        count = 0
        for name in hot_modules:
            if name not in self._cache:
                try:
                    self._cache[name] = importlib.import_module(name)
                    count += 1
                except Exception:
                    pass
        return count

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    @property
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "cached_modules": len(self._cache),
                "total_preload_time": sum(self._preload_times.values()),
                "module_times": dict(self._preload_times),
            }


# ============================================================================
# StartupOptimizer
# ============================================================================

@dataclass
class _StartupPhase:
    name: str
    start_time: float = 0.0
    end_time: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end_time - self.start_time


class StartupOptimizer:
    """Profile and optimize application startup sequence."""

    def __init__(self):
        self._phases: OrderedDict[str, _StartupPhase] = OrderedDict()
        self._lock = threading.Lock()
        self._total_start: float = 0.0
        self._total_end: float = 0.0

    def start(self) -> None:
        """Mark the beginning of the startup sequence."""
        self._total_start = time.perf_counter()

    def begin_phase(self, name: str, **metadata) -> None:
        """Begin profiling a startup phase."""
        with self._lock:
            phase = _StartupPhase(name=name, start_time=time.perf_counter(), metadata=metadata)
            self._phases[name] = phase

    def end_phase(self, name: str) -> Optional[float]:
        """End profiling a startup phase. Returns duration."""
        with self._lock:
            phase = self._phases.get(name)
            if phase:
                phase.end_time = time.perf_counter()
                return phase.duration
            return None

    def end(self) -> None:
        """Mark the end of the startup sequence."""
        self._total_end = time.perf_counter()

    def report(self) -> Dict[str, Any]:
        """Generate a startup performance report."""
        phases = []
        for name, phase in self._phases.items():
            phases.append({
                "name": name,
                "duration_ms": round(phase.duration * 1000, 2),
                "pct_of_total": 0.0,
                **phase.metadata,
            })

        total_duration = self._total_end - self._total_start
        total_ms = round(total_duration * 1000, 2)

        for p in phases:
            if total_ms > 0:
                p["pct_of_total"] = round(p["duration_ms"] / total_ms * 100, 1)

        sorted_phases = sorted(phases, key=lambda x: x["duration_ms"], reverse=True)
        return {
            "total_duration_ms": total_ms,
            "phase_count": len(phases),
            "phases": sorted_phases,
            "bottleneck": sorted_phases[0]["name"] if sorted_phases else None,
        }

    def total_duration_ms(self) -> float:
        return round((self._total_end - self._total_start) * 1000, 2)


# ============================================================================
# Convenience Functions
# ============================================================================

def create_lazy_loader() -> LazyLoader:
    """Create a lazy module loader."""
    return LazyLoader()


def create_module_preloader(max_concurrent: int = 4) -> ModulePreloader:
    """Create a module preloader for startup acceleration."""
    return ModulePreloader(max_concurrent=max_concurrent)


def create_startup_optimizer() -> StartupOptimizer:
    """Create a startup sequence profiler and optimizer."""
    return StartupOptimizer()


def quick_start(
    essential_modules: List[str],
    lazy_modules: List[str],
    hot_modules: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """One-shot startup optimization: preload essentials, lazy-load the rest."""
    preloader = ModulePreloader()
    loader = LazyLoader()

    # Preload essential modules
    essential_times = preloader.precompile(essential_modules, parallel=True)

    # Register lazy modules
    for name in lazy_modules:
        loader.register(name)

    # Warm cache with hot modules (extras)
    if hot_modules:
        preloader.warm_cache(hot_modules)

    return {
        "essential": essential_times,
        "lazy_count": len(lazy_modules),
        "cached_total": len(preloader._cache),
        "total_essential_ms": round(sum(essential_times.values()) * 1000, 2),
    }
