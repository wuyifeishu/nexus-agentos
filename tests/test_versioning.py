"""Tests for agentos.api.versioning."""
import pytest

from agentos.api.versioning import (
    DeprecationPolicy,
    SemVer,
    VersionedRouter,
)


class TestSemVer:
    def test_parse_v1(self):
        v = SemVer.parse("v1")
        assert v is not None
        assert v.major == 1
        assert v.minor == 0
        assert v.patch == 0

    def test_parse_v2_0(self):
        v = SemVer.parse("v2.0")
        assert v is not None
        assert v.major == 2
        assert v.minor == 0

    def test_parse_full(self):
        v = SemVer.parse("v1.2.3")
        assert v is not None
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_parse_no_v(self):
        v = SemVer.parse("3.1.4")
        assert v is not None
        assert v.major == 3

    def test_parse_invalid(self):
        assert SemVer.parse("abc") is None
        assert SemVer.parse("") is None

    def test_is_compatible(self):
        v1 = SemVer(1, 0, 0)
        v1_2 = SemVer(1, 2, 0)
        v2 = SemVer(2, 0, 0)
        assert v1.is_compatible(v1_2)
        assert not v1.is_compatible(v2)

    def test_ordering(self):
        v1 = SemVer(1, 0, 0)
        v2 = SemVer(2, 0, 0)
        v1_5 = SemVer(1, 5, 0)
        assert v1 < v2
        assert v1 < v1_5
        assert v2 > v1_5

    def test_str(self):
        assert str(SemVer(1, 2, 3)) == "v1.2.3"


class TestDeprecationPolicy:
    def test_deprecate(self):
        policy = DeprecationPolicy()
        policy.deprecate("v1", sunset_days=1)
        assert policy.is_deprecated(SemVer(1))

    def test_not_sunset_yet(self):
        policy = DeprecationPolicy()
        policy.deprecate("v1", sunset_days=365)
        assert not policy.should_block(SemVer(1))

    def test_sunset_past(self):
        policy = DeprecationPolicy()
        policy.deprecate("v1", sunset_days=-1)  # already past
        assert policy.should_block(SemVer(1))

    def test_list_deprecated(self):
        policy = DeprecationPolicy()
        policy.deprecate("v1", sunset_days=90)
        deprecated = policy.list_deprecated()
        assert "v1.0.0" in deprecated

    def test_invalid_version(self):
        policy = DeprecationPolicy()
        with pytest.raises(ValueError):
            policy.deprecate("not-a-version")


class TestVersionedRouter:
    def test_register_and_resolve_exact(self):
        router = VersionedRouter()
        router.register("v1", lambda: "v1_handler")
        handler, version = router.resolve(SemVer(1))
        assert handler is not None
        assert str(version) == "v1.0.0"

    def test_minor_fallback(self):
        router = VersionedRouter()
        router.register("v1.0.0", lambda: "v1.0")
        # Request v1.3.0 should fall back to v1.0.0
        handler, version = router.resolve(SemVer(1, 3, 0))
        assert handler is not None
        assert str(version) == "v1.0.0"

    def test_no_match_no_default(self):
        router = VersionedRouter()
        router.register("v1", lambda: "v1")
        handler, version = router.resolve(SemVer(2))
        assert handler is None

    def test_default_version(self):
        router = VersionedRouter()
        router.register("v1", lambda: "v1")
        router.set_default("v1")
        handler, version = router.resolve(SemVer(3))
        assert handler is not None

    def test_list_versions(self):
        router = VersionedRouter()
        router.register("v1", lambda: None)
        router.register("v2.0", lambda: None)
        versions = router.list_versions()
        assert len(versions) == 2
        assert "v1.0.0" in versions
        assert "v2.0.0" in versions

    def test_invalid_register(self):
        router = VersionedRouter()
        with pytest.raises(ValueError):
            router.register("not-a-version", lambda: None)
