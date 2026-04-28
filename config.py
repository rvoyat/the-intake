import os
from dataclasses import dataclass, field


@dataclass
class EscalationThresholds:
    min_confidence_auto_route: float = 0.75
    enterprise_min_confidence: float = 0.85
    high_impact_min_confidence: float = 0.80
    max_retries: int = 3


@dataclass
class ModelConfig:
    coordinator_model: str = "claude-haiku-4-5-20251001"
    specialist_model: str = "claude-haiku-4-5-20251001"
    max_tokens: int = 2048
    temperature: float = 0.0


@dataclass
class Config:
    anthropic_api_key: str = field(default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", ""))
    log_level: str = field(default_factory=lambda: os.environ.get("LOG_LEVEL", "INFO"))
    log_file: str = field(default_factory=lambda: os.environ.get("LOG_FILE", "logs/intake.jsonl"))
    escalation: EscalationThresholds = field(default_factory=EscalationThresholds)
    models: ModelConfig = field(default_factory=ModelConfig)
    definition_version: str = "1.0.0"

    HIGH_RISK_TOOLS = {"log_to_crm", "send_rep_notification"}

    FROZEN_ACCOUNTS: set = field(default_factory=lambda: {
        "acme-frozen-001", "legacy-corp-999"
    })

    BLOCKED_ROUTES: set = field(default_factory=lambda: {
        "route_to_ceo", "route_to_legal_direct", "route_to_board"
    })


config = Config()
