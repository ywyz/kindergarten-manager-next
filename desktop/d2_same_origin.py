"""D2 W6 same-origin code comparison (frozen package vs. source).

The W6 acceptance (engineering spec §6 G16) requires that the bundled package
executes the *same* production code as the delivered source. This module gives
both sides one comparison.

Comparison design (why not raw ``marshal.dumps``):

* ``marshal`` serialises ``set``/``frozenset`` constants in iteration order,
  which varies with per-process string-hash randomisation — a *false* mismatch.
  It also carries ``co_filename``, which legitimately differs between the
  source checkout and the frozen package.
* Instead, a **structural signature** is computed from every code field
  (arg/nlocals/stacksize/flags, bytecode, names, varnames, free/cell vars,
  qualname, first line number, line table, exception table and all constants).
  Only ``co_filename`` is ignored; **no line number, constant or other metadata
  is ever dropped**. Collection constants are canonicalised order-insensitively
  so hashing/intern state can never cause a false mismatch.

Source text is always compiled with ``dont_inherit=True`` and the current
interpreter optimisation level, so this module's own ``from __future__ import
annotations`` can never leak into a compared file (W6 R03).

Any module whose code cannot be obtained is reported ``unavailable`` with a
reason — never silently treated as equal.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
import types
from pathlib import Path

# Desktop host modules that belong to the same-origin scan in addition to the
# ``app.*`` production package.
HOST_MODULES = (
    "d1_main",
    "d1_host_api",
    "d1_server",
    "d1_paths",
    "d0_main",
    "d0_paths",
)


# ---------------------------------------------------------------------------
# Structural code signature
# ---------------------------------------------------------------------------


def _const_signature(value):  # noqa: ANN001 - arbitrary code constants
    """Order-insensitive, intern-insensitive signature of one constant."""
    if isinstance(value, types.CodeType):
        return _code_signature(value)
    if isinstance(value, tuple):
        return ["tuple", [_const_signature(item) for item in value]]
    if isinstance(value, frozenset):
        return ["frozenset", sorted(_const_signature(item) for item in value)]
    if isinstance(value, set):  # pragma: no cover - not produced by compile()
        return ["set", sorted(_const_signature(item) for item in value)]
    if isinstance(value, bytes):
        return ["bytes", value.hex()]
    if isinstance(value, bytearray):  # pragma: no cover
        return ["bytearray", bytes(value).hex()]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", value]
    if isinstance(value, float):
        return ["float", repr(value)]
    if isinstance(value, complex):
        return ["complex", repr(value)]
    if value is None:
        return ["none"]
    if value is Ellipsis:
        return ["ellipsis"]
    if value is NotImplemented:  # pragma: no cover
        return ["notimpl"]
    return ["other", type(value).__name__, repr(value)]


def _code_signature(code: types.CodeType) -> dict:
    """Every code field except ``co_filename`` (which legitimately differs)."""
    return {
        "name": code.co_name,
        "qualname": getattr(code, "co_qualname", code.co_name),
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "nlocals": code.co_nlocals,
        "stacksize": code.co_stacksize,
        "flags": code.co_flags,
        "code": code.co_code.hex(),
        "consts": [_const_signature(item) for item in code.co_consts],
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
        "firstlineno": code.co_firstlineno,
        "linetable": code.co_linetable.hex() if code.co_linetable else "",
        "exceptiontable": code.co_exceptiontable.hex()
        if code.co_exceptiontable
        else "",
    }


def fingerprint_code(code: types.CodeType) -> str:
    payload = json.dumps(
        _code_signature(code),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_source(path: str | Path) -> str:
    """Fingerprint a delivered source file by compiling it.

    ``dont_inherit=True`` prevents the compiling module's own future flags from
    leaking into the compared file (W6 R03); the file's own ``__future__``
    imports are still honoured, and the interpreter optimisation level is used.
    """
    text = Path(path).read_text(encoding="utf-8")
    code = compile(
        text,
        str(path),
        "exec",
        dont_inherit=True,
        optimize=sys.flags.optimize,
    )
    return fingerprint_code(code)


def _loader_code(module: types.ModuleType) -> types.CodeType | None:
    """Best-effort code object for an imported module (source or frozen)."""
    loader = getattr(module, "__loader__", None)
    name = getattr(module, "__name__", "")
    spec = getattr(module, "__spec__", None)
    candidates = [loader]
    if spec is not None:
        candidates.append(spec.loader)
    for candidate in candidates:
        if candidate is None:
            continue
        get_code = getattr(candidate, "get_code", None)
        if get_code is not None:
            try:
                code = get_code(name)
                if isinstance(code, types.CodeType):
                    return code
            except Exception:  # noqa: BLE001 - try the next strategy
                pass
        get_data = getattr(candidate, "get_data", None)
        path = getattr(candidate, "path", None)
        if get_code is None and get_data is not None and path:
            try:
                data = get_data(path)
                if isinstance(data, (bytes, bytearray)):
                    obj = marshal_loads_pyc(bytes(data))
                    if isinstance(obj, types.CodeType):
                        return obj
            except Exception:  # noqa: BLE001
                pass
    source = getattr(module, "__file__", None)
    if isinstance(source, str) and source.endswith(".py"):
        # A source run usually has the .py; compile it exactly like the import
        # machinery would (no inherited future flags).
        try:
            return compile(
                Path(source).read_text(encoding="utf-8"),
                source,
                "exec",
                dont_inherit=True,
                optimize=sys.flags.optimize,
            )
        except Exception:  # noqa: BLE001
            return None
    return None


def marshal_loads_pyc(data: bytes):
    """Load the code object from a ``.pyc`` payload (skip the 16-byte header)."""
    import marshal

    if data[:4] != importlib.util.MAGIC_NUMBER and len(data) > 4:
        # CPython's MAGIC_NUMBER covers 3.7+; anything else is not a .pyc.
        return marshal.loads(data)
    return marshal.loads(data[16:])


def fingerprint_imported_module(name: str) -> dict:
    """``{status, sha256, source_file}`` for one imported module."""
    try:
        module = importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "reason": f"import:{type(exc).__name__}"}
    code = _loader_code(module)
    if code is None:
        return {"status": "unavailable", "reason": "no-code"}
    return {
        "status": "ok",
        "sha256": fingerprint_code(code),
        "source_file": getattr(module, "__file__", None),
    }


def fingerprint_source_tree(module_root: str | Path, prefix: str) -> dict[str, dict]:
    """Fingerprint every ``.py`` under ``module_root`` as ``prefix.*`` modules."""
    root = Path(module_root)
    result: dict[str, dict] = {}
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root).with_suffix("")
        parts = [part for part in rel.parts if part != "__init__"]
        name = prefix.rstrip(".") if not parts else prefix + ".".join(parts)
        try:
            result[name] = {
                "status": "ok",
                "sha256": fingerprint_source(path),
                "source_file": str(path),
            }
        except Exception as exc:  # noqa: BLE001
            result[name] = {"status": "error", "reason": type(exc).__name__}
    return result


def loaded_production_modules() -> list[str]:
    """Currently-loaded modules that belong to the source comparison set."""
    names: list[str] = []
    for name in sys.modules:
        if name.startswith("app."):
            names.append(name)
        elif name in HOST_MODULES:
            names.append(name)
    return sorted(set(names))


__all__ = [
    "HOST_MODULES",
    "fingerprint_code",
    "fingerprint_imported_module",
    "fingerprint_source",
    "fingerprint_source_tree",
    "loaded_production_modules",
]
