"""Tests for agentos.tools.di_container."""

import pytest

from agentos.tools.di_container import CircularDependencyError, DIContainer, Lifetime

# ============================================================
# Test classes for DI
# ============================================================

class AbstractDB:
    def query(self, sql: str) -> list:
        raise NotImplementedError


class ConcretePostgres(AbstractDB):
    def query(self, sql: str) -> list:
        return [{"result": "pg_" + sql}]


class AbstractCache:
    def get(self, key: str) -> str:
        raise NotImplementedError


class RedisCache(AbstractCache):
    def __init__(self):
        self._store = {}

    def get(self, key: str) -> str:
        return self._store.get(key, "")


class ServiceWithDeps:
    def __init__(self, db: AbstractDB, cache: AbstractCache):
        self.db = db
        self.cache = cache


class ServiceWithDefault:
    def __init__(self, name: str = "default_name"):
        self.name = name


class ServiceA:
    def __init__(self, b: "ServiceB"):
        self.b = b


class ServiceB:
    def __init__(self, a: ServiceA):
        self.a = a


class TestDIContainer:
    def test_register_and_resolve_singleton(self):
        c = DIContainer()
        c.register(AbstractDB, ConcretePostgres, Lifetime.SINGLETON)
        db1 = c.resolve(AbstractDB)
        db2 = c.resolve(AbstractDB)
        assert db1 is db2
        assert isinstance(db1, ConcretePostgres)
        assert db1.query("test") == [{"result": "pg_test"}]

    def test_register_and_resolve_transient(self):
        c = DIContainer()
        c.register(AbstractDB, ConcretePostgres, Lifetime.TRANSIENT)
        db1 = c.resolve(AbstractDB)
        db2 = c.resolve(AbstractDB)
        assert db1 is not db2
        assert isinstance(db1, ConcretePostgres)

    def test_register_instance(self):
        c = DIContainer()
        db = ConcretePostgres()
        c.register_instance(AbstractDB, db)
        resolved = c.resolve(AbstractDB)
        assert resolved is db

    def test_register_factory(self):
        c = DIContainer()
        c.register_factory(AbstractDB, lambda: ConcretePostgres())
        db1 = c.resolve(AbstractDB)
        db2 = c.resolve(AbstractDB)
        assert isinstance(db1, ConcretePostgres)
        assert db1 is not db2

    def test_factory_singleton(self):
        c = DIContainer()
        c.register_factory(AbstractDB, lambda: ConcretePostgres(), lifetime=Lifetime.SINGLETON)
        db1 = c.resolve(AbstractDB)
        db2 = c.resolve(AbstractDB)
        assert db1 is db2

    def test_unregistered_raises(self):
        c = DIContainer()
        with pytest.raises(KeyError):
            c.resolve(AbstractDB)

    def test_is_registered(self):
        c = DIContainer()
        assert not c.is_registered(AbstractDB)
        c.register(AbstractDB, ConcretePostgres)
        assert c.is_registered(AbstractDB)

    def test_auto_wiring(self):
        c = DIContainer()
        c.register(AbstractDB, ConcretePostgres, Lifetime.SINGLETON)
        c.register(AbstractCache, RedisCache, Lifetime.SINGLETON)
        c.register(ServiceWithDeps, ServiceWithDeps)
        svc = c.resolve(ServiceWithDeps)
        assert isinstance(svc.db, ConcretePostgres)
        assert isinstance(svc.cache, RedisCache)

    def test_default_param_no_registration(self):
        c = DIContainer()
        c.register(ServiceWithDefault)
        svc = c.resolve(ServiceWithDefault)
        assert svc.name == "default_name"

    def test_circular_dependency(self):
        c = DIContainer()
        c.register(ServiceA)
        c.register(ServiceB)
        with pytest.raises(CircularDependencyError) as exc:
            c.resolve(ServiceA)
        assert "Circular dependency" in str(exc.value)

    def test_scoped_container(self):
        parent = DIContainer()
        parent.register(AbstractDB, ConcretePostgres, Lifetime.SINGLETON)
        scope = parent.create_scope()
        # scope inherits from parent
        assert scope.is_registered(AbstractDB)
        db = scope.resolve(AbstractDB)
        assert isinstance(db, ConcretePostgres)

    def test_scoped_override(self):
        parent = DIContainer()
        parent.register(AbstractDB, ConcretePostgres, Lifetime.SINGLETON)
        scope = parent.create_scope()
        # Register a different implementation in scope
        class MockDB(AbstractDB):
            def query(self, sql):
                return [{"mock": True}]

        scope.register(AbstractDB, MockDB, Lifetime.TRANSIENT)
        # scope's own registration takes priority
        db = scope.resolve(AbstractDB)
        assert isinstance(db, MockDB)

    def test_single_class_no_interface(self):
        """Register impl==interface (no abstract/impl split)."""
        c = DIContainer()
        c.register(RedisCache, lifetime=Lifetime.SINGLETON)
        obj = c.resolve(RedisCache)
        assert isinstance(obj, RedisCache)

    def test_transient_cache_reuse(self):
        """Transient: every resolve creates new instance."""
        c = DIContainer()
        c.register(RedisCache, lifetime=Lifetime.TRANSIENT)
        a = c.resolve(RedisCache)
        b = c.resolve(RedisCache)
        assert a is not b

    def test_nested_resolution_unique_copies(self):
        """Two resolves of a service with deps should yield different instances if transient."""
        c = DIContainer()
        c.register(AbstractDB, ConcretePostgres, Lifetime.TRANSIENT)
        c.register(AbstractCache, RedisCache, Lifetime.TRANSIENT)
        c.register(ServiceWithDeps, ServiceWithDeps)
        svc1 = c.resolve(ServiceWithDeps)
        svc2 = c.resolve(ServiceWithDeps)
        assert svc1 is not svc2
        assert svc1.db is not svc2.db
        assert svc1.cache is not svc2.cache
