"""The runtime: the state machine, the engine, execution, and the session use cases.

This package only groups its subpackages and re-exports nothing. A name is
imported from the subpackage that owns it, for example
``from super_agent.runtime.session import Session``; writing
``from super_agent.runtime import machine`` imports that subpackage itself. R14 in
``tests/architecture/test_dependencies.py`` rejects every other import of this
package, in the code and in the tests.
"""
