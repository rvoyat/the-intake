from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class LeadSource(str, Enum):
    WEB_FORM = "web_form"
    EMAIL = "email"
    BADGE_SCAN = "badge_scan"
    PHONE = "phone"
    UNKNOWN = "unknown"


class LeadCategory(str, Enum):
    ENTERPRISE = "enterprise"
    MID_MARKET = "mid_market"
    SMB = "smb"
    PARTNER = "partner"
    SPAM = "spam"
    COMPETITOR = "competitor"
    UNQUALIFIED = "unqualified"


class Tier(str, Enum):
    T1_ENTERPRISE = "T1_enterprise"
    T2_MID_MARKET = "T2_mid_market"
    T3_SMB = "T3_smb"
    DISQUALIFY = "disqualify"


class ImpactLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EscalationReason(str, Enum):
    LOW_CONFIDENCE = "low_confidence"
    HIGH_VALUE_UNCERTAIN = "high_value_uncertain"
    ADVERSARIAL_SIGNAL = "adversarial_signal"
    NO_REP_AVAILABLE = "no_rep_available"
    LEGAL_EXPOSURE = "legal_exposure"
    MANUAL_OVERRIDE_REQUESTED = "manual_override_requested"


class LeadRequest(BaseModel):
    lead_id: str
    source: LeadSource
    raw_content: str
    metadata: dict = Field(default_factory=dict)
    timestamp: str


class ClassificationResult(BaseModel):
    lead_id: str
    category: LeadCategory
    confidence: float = Field(ge=0.0, le=1.0)
    signals: list[str] = Field(default_factory=list)
    adversarial_flags: list[str] = Field(default_factory=list)
    reasoning: str


class PriorityResult(BaseModel):
    lead_id: str
    tier: Tier
    impact: ImpactLevel
    lead_score: float = Field(ge=0.0, le=100.0)
    estimated_deal_size: Optional[str] = None
    urgency_signals: list[str] = Field(default_factory=list)
    assigned_rep_id: Optional[str] = None
    reasoning: str


class EscalationDecision(BaseModel):
    should_escalate: bool
    reason: Optional[EscalationReason] = None
    details: str


class RoutingDecision(BaseModel):
    lead_id: str
    action: str  # "route", "escalate", "disqualify", "request_more_info"
    assigned_rep_id: Optional[str] = None
    assigned_rep_name: Optional[str] = None
    tier: Tier
    category: LeadCategory
    confidence: float
    impact: ImpactLevel
    lead_score: float
    escalation: EscalationDecision
    acknowledgment_draft: Optional[str] = None
    reasoning_chain: list[str] = Field(default_factory=list)
    retry_count: int = 0
    definition_version: str = "1.0.0"
