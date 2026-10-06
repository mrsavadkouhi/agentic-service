from dataclasses import dataclass


@dataclass
class ProbeInput:
    probe_id: str
    correlation_id: str
    worker_role: str


@dataclass
class ProbeResult:
    probe_id: str
    worker_role: str
    state: str
    external_writes: bool = False

