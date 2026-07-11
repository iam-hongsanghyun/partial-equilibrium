"""``SupabaseBackend`` is an interface-only seam: every method must raise
``NotImplementedError`` (never silently no-op, never partially work) so a
caller can't mistake it for a live backend.
"""

from __future__ import annotations

import pytest

from pe.registry.supabase_backend import SupabaseBackend


@pytest.fixture
def backend() -> SupabaseBackend:
    return SupabaseBackend(url="https://example.supabase.co", key="test-key")


def test_save_model_not_implemented(backend: SupabaseBackend) -> None:
    with pytest.raises(NotImplementedError, match="save_model"):
        backend.save_model("id", "Name", {"scenarios": []}, None)


def test_get_model_not_implemented(backend: SupabaseBackend) -> None:
    with pytest.raises(NotImplementedError, match="get_model"):
        backend.get_model("id")


def test_list_models_not_implemented(backend: SupabaseBackend) -> None:
    with pytest.raises(NotImplementedError, match="list_models"):
        backend.list_models()


def test_rename_model_not_implemented(backend: SupabaseBackend) -> None:
    with pytest.raises(NotImplementedError, match="rename_model"):
        backend.rename_model("id", "New Name")


def test_delete_model_not_implemented(backend: SupabaseBackend) -> None:
    with pytest.raises(NotImplementedError, match="delete_model"):
        backend.delete_model("id")


def test_constructible_without_credentials() -> None:
    """Constructing the stub never touches a network — only calling a method does."""
    backend = SupabaseBackend()
    with pytest.raises(NotImplementedError):
        backend.list_models()
