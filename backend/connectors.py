"""External-source contracts. No undocumented endpoint is implemented."""
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass
class ConnectorStatus:
    key: str
    name: str
    status: str
    base_url: str
    note: str
    checked_at: str | None = None

# Concrete implementation lives in resa_connector and requires an injected DB connection.
from resa_connector import LBRResaConnector

class EurostatNaceConnector:
    """NACE source boundary; exact dataset endpoints must be configured."""
    def status(self):
        return ConnectorStatus("eurostat_nace", "Eurostat NACE Rev. 2.1", "NOT_CONNECTED",
            "https://ec.europa.eu/eurostat/web/nace",
            "Official catalogue identified; dataset import endpoint not configured.")
