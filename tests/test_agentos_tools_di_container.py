"""Tests for agentos.tools.di_container — DI Container, Registration, Lifetime."""

import pytest

from agentos.tools.di_container import (
    CircularDependencyError,
    DIContainer,
    Lifetime,
    Registration,
)

# ── Test interfaces and implementations ──────────────────────────────

class AbstractDB:
    def query(self):
        raise NotImplementedError

class PostgresDB(AbstractDB):
    def query(self):
        return "postgres"

class AbstractCache:
    def get(self, key):
        raise NotImplementedError

class RedisCache(AbstractCache):
    def get(self, key):
        return f"redis:{key}"

class ServiceWithDeps:
    def __init__(self, db: AbstractDB, cache: AbstractCache):
        self.db = db
        self.cache = cache

class A:
    pass

class B(A):
    pass

class OptionalDep:
    def __init__(self, name: str = "default"):
        self.name = name

class CyclicA:
    def __init__(self, b: "CyclicB" = None):
        self.b = b

class CyclicB:
    def __init__(self, a: CyclicA = None):
        self.a = a

# Hard cycle — no defaults, must be at module level for get_type_hints to work
class HardCyclicA:
    def __init__(self, b: "HardCyclicB"):
        self.b = b

class HardCyclicB:
    def __init__(self, a: HardCyclicA):
        self.a = a


# ── Registration ──────────────────────────────────────────────────────

class TestRegistration:
    def test_defaults(self):
        r = Registration(interface=AbstractDB)
        assert r.interface == AbstractDB
        assert r.implementation is None
        assert r.lifetime == Lifetime.TRANSIENT
        assert r.factory is None
        assert r.instance is None

    def test_with_all_params(self):
        r = Registration(
            interface=AbstractDB,
            implementation=PostgresDB,
            lifetime=Lifetime.SINGLETON,
            factory=lambda: PostgresDB(),
        )
        assert r.implementation == PostgresDB
        assert r.lifetime == Lifetime.SINGLETON


# ── DIContainer: register / is_registered ────────────────────────────

class TestRegister:
    def test_register_default(self):
        c = DIContainer()
        c.register(AbstractDB, PostgresDB)
        assert c.is_registered(AbstractDB)

    def test_register_self_impl(self):
        c = DIContainer()
        c.register(PostgresDB)  # impl defaults to interface
        assert c.is_registered(PostgresDB)

    def test_register_instance(self):
        c = DIContainer()
        pg = PostgresDB()
        c.register_instance(AbstractDB, pg)

    def test_register_factory(self):
        c = DIContainer()
        c.register_factory(AbstractDB, lambda: PostgresDB())
        assert c.is_registered(AbstractDB)

    def test_is_registered_false(self):
        c = DIContainer()
        assert not c.is_registered(AbstractDB)


# ── DIContainer: resolve ─────────────────────────────────────────────

class TestResolve:
    def test_simple(self):
        c = DIContainer()
        c.register(AbstractDB, PostgresDB)
        db = c.resolve(AbstractDB)
        assert isinstance(db, PostgresDB)

    def test_unregistered_raises(self):
        c = DIContainer()
        with pytest.raises(KeyError):
            c.resolve(AbstractDB)

    def test_instance(self):
        c = DIContainer()
        pg = PostgresDB()
        c.register_instance(AbstractDB, pg)
        assert c.resolve(AbstractDB) is pg

    def test_factory(self):
        c = DIContainer()
        c.register_factory(AbstractDB, lambda: PostgresDB())
        db = c.resolve(AbstractDB)
        assert isinstance(db, PostgresDB)

    def test_singleton_same_instance(self):
        c = DIContainer()
        c.register(AbstractDB, PostgresDB, Lifetime.SINGLETON)
        db1 = c.resolve(AbstractDB)
        db2 = c.resolve(AbstractDB)
        assert db1 is db2

    def test_transient_different_instances(self):
        c = DIContainer()
        c.register(AbstractDB, PostgresDB, Lifetime.TRANSIENT)
        db1 = c.resolve(AbstractDB)
        db2 = c.resolve(AbstractDB)
        assert db1 is not db2

    def test_recursive_deps(self):
        c = DIContainer()
        c.register(AbstractDB, PostgresDB, Lifetime.SINGLETON)
        c.register(AbstractCache, RedisCache, Lifetime.SINGLETON)
        c.register(ServiceWithDeps, ServiceWithDeps)
        svc = c.resolve(ServiceWithDeps)
        assert isinstance(svc.db, PostgresDB)
        assert isinstance(svc.cache, RedisCache)

    def test_optional_default(self):
        c = DIContainer()
        c.register(OptionalDep, OptionalDep)
        obj = c.resolve(OptionalDep)
        assert obj.name == "default"

    def test_factory_singleton(self):
        calls = [0]

        def factory():
            calls[0] += 1
            return PostgresDB()

        c = DIContainer()
        c.register_factory(AbstractDB, factory, Lifetime.SINGLETON)
        a = c.resolve(AbstractDB)
        b = c.resolve(AbstractDB)
        assert a is b
        assert calls[0] == 1

    def test_safe_get_type_hints_recovers(self):
        """safe_get_type_hints should handle functions with broken annotations."""
        c = DIContainer()
        # register_self uses the implementation as its own interface
        c.register(A, A)
        obj = c.resolve(A)
        assert isinstance(obj, A)


# ── DIContainer: scoped ──────────────────────────────────────────────

class TestScope:
    def test_create_scope(self):
        parent = DIContainer()
        parent.register(AbstractDB, PostgresDB, Lifetime.SINGLETON)
        child = parent.create_scope()
        assert child.is_registered(AbstractDB)
        db = child.resolve(AbstractDB)
        assert isinstance(db, PostgresDB)

    def test_child_override(self):
        parent = DIContainer()
        parent.register(AbstractDB, PostgresDB, Lifetime.SINGLETON)
        child = parent.create_scope()
        child.register(AbstractDB, PostgresDB, Lifetime.TRANSIENT)
        db1 = child.resolve(AbstractDB)
        db2 = child.resolve(AbstractDB)
        assert db1 is not db2  # child transient overrides parent singleton


# ── DIContainer: circular dependency ─────────────────────────────────

class TestCircularDependency:
    def test_direct_cycle_detected(self):
        """Without defaults, the cycle A→B→A must be caught."""
        c = DIContainer()
        c.register(HardCyclicA, HardCyclicA)
        c.register(HardCyclicB, HardCyclicB)
        with pytest.raises(CircularDependencyError) as exc:
            c.resolve(HardCyclicA)
        assert isinstance(exc.value, CircularDependencyError)
