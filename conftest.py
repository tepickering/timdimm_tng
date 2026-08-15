"""
Root conftest.

Its presence is the point: pytest puts the directory holding the topmost conftest onto `sys.path`,
which is what lets `src/timdimm_tng/tests/test_log_adafruit.py` do `from scripts.log_adafruit
import ...`. Without it a bare `pytest` fails to collect that module, and only `python -m pytest`
works -- and then only from the repository root.
"""
