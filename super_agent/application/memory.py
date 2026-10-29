"""Memory switch application use case."""

from super_agent.application.ports import MemoryPreferences
from super_agent.runtime.session import Session
from super_agent.runtime.session.memory import Switch


class MemoryController:
    """The memory switch as the application sees it: state, persistence, effect.

    The controller holds the same switch the session holds, so turning memory
    off is one write and one rebuild of the conversation context — the stored
    lines are left alone, and turning it back on brings them back.
    """

    __slots__ = ("_preferences", "_session", "switch")

    def __init__(
        self, switch: Switch, session: Session | None = None, preferences: MemoryPreferences | None = None
    ) -> None:
        self.switch = switch
        self._session = session
        self._preferences = preferences

    @property
    def enabled(self) -> bool:
        """Whether the memory is in use right now."""
        return self.switch.enabled

    @property
    def backend(self) -> str:
        """Where the lines live, by name."""
        return self.switch.name

    def items(self) -> list[str]:
        """The stored lines, empty while the memory is off."""
        return self.switch.load()

    async def setEnabled(self, enabled: bool) -> None:
        """Turn the memory on or off, persist it, and rebuild the context."""
        self.switch.setEnabled(enabled)
        if self._preferences is not None:
            self._preferences.set_enabled(enabled)
        session = self._session
        if session is not None:
            await session.refresh_memory()
