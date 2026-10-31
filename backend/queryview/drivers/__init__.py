"""Driver registry: maps a connection `type` to the Driver that executes it."""

from __future__ import annotations

from .base import Driver
from .clickhouse import ClickHouseDriver
from .duckdb import DuckDBDriver
from .postgres import PostgresDriver
from .sqlite import SqliteDriver

DRIVERS: dict[str, Driver] = {d.type: d for d in (ClickHouseDriver(), PostgresDriver(), DuckDBDriver(), SqliteDriver())}
