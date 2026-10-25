"""Roles and the tools each role may use. Single source of truth for the
server-side registration and the gateway-side allowlist."""

ALL_TOOLS = ("search_dataset", "read_file", "write_note")

ROLE_TOOLS: dict[str, tuple[str, ...]] = {
    "planner": (),
    "researcher": ("search_dataset", "read_file"),
    "executor": ("write_note",),
}
