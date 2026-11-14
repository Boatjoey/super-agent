"""Development scripts, importable as ``scripts.*`` so tests can type-check what they call.

A regular package rather than a namespace one: an installed top-level ``scripts``
module would take precedence over a namespace package, never over this one. The
files still run as programs (``python scripts/smoke.py``), and the wheel ships only
``super_agent``.
"""
