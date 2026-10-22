"""The engine's framework: a content-addressed cache, a parallel dependency-graph runner with isolation, timeouts,
retries, output contracts and last-good fallback, structured logging, and the health check.

    cache       memoize pure computations by code and data; fetch network inputs with a last-good fallback
    runner      run engines as a graph of tasks in parallel processes and record what each read and wrote
    contracts   what each output file must contain before anything may read it
    log         structured logs and timing spans
    doctor      the health check behind `python -m buildout doctor`
"""
from . import cache, contracts, log, runner  # noqa: F401
