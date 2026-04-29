"""Runtime dependencies shared by extracted routers.

This keeps the current monolith working while routes move progressively out of
main.py. The goal is an intermediate modular-monolith step, not a new service.
"""


class Runtime:
    pass


runtime = Runtime()
