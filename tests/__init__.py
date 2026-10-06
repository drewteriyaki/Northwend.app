# Passwords are hashed at 600,000 PBKDF2 iterations (auth.PBKDF2_ITERATIONS),
# which nearly doubles a run of the suite. A local copy (never a hosted one)
# honours a smaller count from NORTHWEND_PBKDF2_ITERATIONS, so the tests use
# one. `python -m unittest tests.test_x` imports this package first; the
# `discover -s tests` run gets the same line from test_core.py (discover
# imports every test module before it runs any). The tests of the real
# counts take the setting away (tests/test_sign_out_and_log.py).
import os

os.environ.setdefault("NORTHWEND_PBKDF2_ITERATIONS", "1000")
