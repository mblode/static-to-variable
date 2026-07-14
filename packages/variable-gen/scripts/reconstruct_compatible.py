"""Compatibility shim.

reconstruct_compatible moved into the variable_gen package so the installed
engine carries it. Legacy checkout scripts still ``import reconstruct_compatible``
with scripts/ on sys.path; alias this name to the package module so every symbol
(including private helpers) resolves to the one implementation.
"""

import sys

from variable_gen import reconstruct_compatible as _module

sys.modules[__name__] = _module
