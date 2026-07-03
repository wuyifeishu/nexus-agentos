"""
DIContainer — lightweight dependency injection container.

Supports:
    - Singleton and transient lifetimes
    - Constructor autowiring via type annotations
    - Factory registration
    - Instance registration
    - Scoped sub-containers (snapshot-based)
    - Circular dependency detection
"""

from __future__ import annotations

import inspect
from enum import Enum
from threading import RLock
from typing import Any, Callable, Dict, Optional, Set, Type, TypeVar, get_type_hints

T = TypeVar("T")


# ============================================================================
# Lifetime
# ============================================================================

class Lifetime(Enum):
    SINGLETON = "singleton"
    TRANSIENT = "transient"


# ============================================================================
# Registration
# ============================================================================

class Registration:
    __slots__ = ("interface", "implementation", "lifetime", "factory", "instance", "instance_lock")

    def __init__(
        self,
        interface: Type,
        implementation: Optional[Type] = None,
        lifetime: Lifetime = Lifetime.TRANSIENT,
        factory: Optional[Callable[[], Any]] = None,
        instance: Any = None,
    ):
        self.interface = interface
        self.implementation = implementation
        self.lifetime = lifetime
        self.factory = factory
        self.instance = instance
        self.instance_lock = RLock()


# ============================================================================
# Circular Dependency Error
# ============================================================================

class CircularDependencyError(Exception):
    def __init__(self, chain: list):
        self.chain = chain
        super().__init__(f"Circular dependency detected: {' → '.join(str(c) for c in chain)}")


# ============================================================================
# DIContainer
# ============================================================================

class DIContainer:
    """Lightweight dependency injection container.

    Usage:
        container = DIContainer()

        # Register singleton
        container.register(AbstractDB, ConcretePostgres, Lifetime.SINGLETON)

        # Register transient
        container.register(AbstractCache, RedisCache, Lifetime.TRANSIENT)

        # Register instance
        container.register_instance(ConfigService, config_obj)

        # Resolve
        db = container.resolve(AbstractDB)

        # Factory
        container.register_factory(AbstractQueue, lambda: build_queue())
    """

    def __init__(self, parent: Optional["DIContainer"] = None):
        self._registrations: Dict[Any, Registration] = {}
        self._lock = RLock()
        self._parent = parent

    # ---------- register ----------

    def register(
        self,
        interface: Type,
        implementation: Optional[Type] = None,
        lifetime: Lifetime = Lifetime.TRANSIENT,
    ) -> None:
        """Register an interface with its implementation."""
        if implementation is None:
            implementation = interface
        with self._lock:
            self._registrations[interface] = Registration(
                interface=interface,
                implementation=implementation,
                lifetime=lifetime,
            )

    def register_instance(self, interface: Type, instance: Any) -> None:
        """Register a pre-built instance."""
        with self._lock:
            self._registrations[interface] = Registration(
                interface=interface,
                implementation=type(instance),
                lifetime=Lifetime.SINGLETON,
                instance=instance,
            )

    def register_factory(self, interface: Type, factory: Callable[[], Any], lifetime: Lifetime = Lifetime.TRANSIENT) -> None:
        """Register a factory callable for the interface."""
        with self._lock:
            self._registrations[interface] = Registration(
                interface=interface,
                implementation=None,
                lifetime=lifetime,
                factory=factory,
            )

    # ---------- resolve ----------

    def resolve(self, interface: Type[T]) -> T:
        """Resolve and return an instance of the given interface."""
        return self._resolve(interface, set())

    def _resolve(self, interface: Type, resolving: Set[Type]) -> Any:
        # Check circular deps
        if interface in resolving:
            raise CircularDependencyError(list(resolving) + [interface])

        reg = self._get_registration(interface)
        resolving.add(interface)

        try:
            # Instance already cached
            if reg.instance is not None:
                return reg.instance

            # Singleton: create once
            if reg.lifetime == Lifetime.SINGLETON:
                with reg.instance_lock:
                    if reg.instance is not None:
                        return reg.instance
                    instance = self._build(reg, resolving)
                    reg.instance = instance
                    return instance

            # Transient: create every time
            return self._build(reg, resolving)
        finally:
            resolving.discard(interface)

    def _get_registration(self, interface: Type) -> Registration:
        with self._lock:
            if interface in self._registrations:
                return self._registrations[interface]
            if self._parent:
                return self._parent._get_registration(interface)
        raise KeyError(f"No registration for {interface.__name__}")

    def _build(self, reg: Registration, resolving: Set[Type]) -> Any:
        # Factory takes priority
        if reg.factory is not None:
            return reg.factory()

        # Constructor injection
        impl = reg.implementation or reg.interface
        hints = self._safe_get_type_hints(impl.__init__)
        kwargs: Dict[str, Any] = {}

        for param_name, param in inspect.signature(impl.__init__).parameters.items():
            if param_name == "self":
                continue
            param_type = hints.get(param_name)
            if param_type is not None:
                try:
                    kwargs[param_name] = self._resolve(param_type, resolving.copy())
                except (KeyError, CircularDependencyError):
                    if param.default is not inspect.Parameter.empty:
                        kwargs[param_name] = param.default
                    else:
                        raise
            elif param.default is not inspect.Parameter.empty:
                kwargs[param_name] = param.default

        return impl(**kwargs)

    @staticmethod
    def _safe_get_type_hints(func) -> Dict[str, Any]:
        try:
            return get_type_hints(func)
        except Exception:
            return {}

    # ---------- scoped ----------

    def create_scope(self) -> "DIContainer":
        """Create a scoped child container (snapshot of current registrations)."""
        return DIContainer(parent=self)

    # ---------- check ----------

    def is_registered(self, interface: Type) -> bool:
        with self._lock:
            if interface in self._registrations:
                return True
            if self._parent:
                return self._parent.is_registered(interface)
        return False
