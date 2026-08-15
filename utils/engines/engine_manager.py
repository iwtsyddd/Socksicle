"""Engine manager: registry, selection, and provisioning orchestration.

Provides a central place to:
  - List available engines
  - Get the currently selected engine
  - Provision (download/install) any engine
  - Switch engines with proper cleanup
"""
import logging

from .base import ProxyEngine, EngineType, CheckResult, InstallResult

log = logging.getLogger("engine.manager")

# Singleton registry
_ENGINES: dict[EngineType, type[ProxyEngine]] = {}
_INSTANCES: dict[EngineType, ProxyEngine] = {}


def register_engine(cls: type[ProxyEngine]):
    """Register an engine class. Call at import time."""
    _ENGINES[cls.engine_type] = cls
    return cls


def get_engine_classes() -> dict[EngineType, type[ProxyEngine]]:
    """Return all registered engine classes."""
    return dict(_ENGINES)


def get_all_engine_types() -> list[EngineType]:
    """Return all registered engine types in display order."""
    return list(_ENGINES.keys())


def get_engine(cls_or_type) -> ProxyEngine:
    """Get or create a singleton engine instance."""
    if isinstance(cls_or_type, type):
        et = cls_or_type.engine_type
        cls = cls_or_type
    else:
        et = cls_or_type
        cls = _ENGINES.get(et)
    if et not in _INSTANCES:
        _INSTANCES[et] = cls()
    return _INSTANCES[et]


def get_current_engine(settings: dict) -> ProxyEngine:
    """Get the engine instance for the currently selected engine type."""
    engine_key = settings.get("engine", "sslocal")
    try:
        et = EngineType(engine_key)
    except ValueError:
        et = EngineType.SSLOCAL
    return get_engine(et)


def check_engine(engine_type: EngineType) -> CheckResult:
    """Check if a specific engine binary is available and usable."""
    engine = get_engine(engine_type)
    binary = engine.find_binary()
    if binary is None:
        return CheckResult(False, f"{engine_type.value} binary not found")
    return engine.check_usable(binary)


def install_engine(engine_type: EngineType, progress_cb=None) -> InstallResult:
    """Download and install an engine."""
    engine = get_engine(engine_type)
    return engine.install(progress_cb=progress_cb)


def ensure_engine(engine_type: EngineType, progress_cb=None) -> InstallResult:
    """Ensure an engine is available, reusing existing or installing."""
    existing = get_engine(engine_type).find_binary()
    if existing is not None:
        check = get_engine(engine_type).check_usable(existing)
        if check.usable:
            return InstallResult(True, existing, "Reusing existing binary.")
    return install_engine(engine_type, progress_cb=progress_cb)


def switch_engine(settings: dict, new_engine_type: EngineType,
                  connection_manager=None) -> ProxyEngine:
    """Switch to a new engine. Disconnects the current one if connected.

    Returns the new engine instance.
    """
    if connection_manager and connection_manager.is_connected:
        connection_manager.disconnect()

    settings["engine"] = new_engine_type.value
    return get_engine(new_engine_type)


def cleanup_stale_core_processes() -> list[str]:
    """Kill engine processes left alive by a previously crashed session.

    Only processes recorded in our own pid markers are touched; foreign
    processes and recycled pids are never killed.  Returns a list of
    actions performed (empty when there was nothing to clean).
    """
    from .proc_guard import cleanup_stale_engines
    return cleanup_stale_engines([et.value for et in _ENGINES])


# Auto-register all engines on import
def _register_all():
    from .sslocal_engine import SslocalEngine
    from .xray_engine import XrayEngine
    from .singbox_engine import SingBoxEngine
    register_engine(SslocalEngine)
    register_engine(XrayEngine)
    register_engine(SingBoxEngine)


_register_all()
