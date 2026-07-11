# Backward-compatibility shim — re-exports from pe.registry.supabase_backend.
# New location: src/pe/registry/supabase_backend.py.
import warnings

from pe.registry.supabase_backend import SupabaseBackend

warnings.warn(
    "ets.registry.supabase_backend is deprecated; import from "
    "pe.registry.supabase_backend instead. Removal milestone: 0.4.0.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "SupabaseBackend",
]
