import pytest

from buildout.data.synthetic import simulate

BOOK = ["MSFT", "AMZN", "GOOGL", "META", "NVDA", "AVGO", "TSLA", "SPCX", "ORCL"]


@pytest.fixture(scope="session")
def world():
    return simulate(BOOK, n_days=2520, seed=7)
