from typing import Any, List, Dict, Optional
from pydantic import BaseModel, Field, model_validator

class StepExplainability(BaseModel):
    required: bool = False
    mode: Optional[str] = None
    target_field: Optional[str] = None

class StepTelemetry(BaseModel):
    monitor_token_usage: bool = False
    alert_on_latency_ms: Optional[int] = None

class GlobalGovernance(BaseModel):
    telemetry_profile: str = "standard"
    max_workflow_cost_usd: float = 0.50

class SOPStep(BaseModel):
    id: str
    action: str
    capability: str
    inputs: Optional[Dict[str, Any]] = None
    success_criteria: Optional[str] = None
    on_failure: Optional[str] = None
    human_approval: Optional[str] = None
    instruction: Optional[str] = None
    explainability: Optional[StepExplainability] = None
    telemetry: Optional[StepTelemetry] = None

    @model_validator(mode="before")
    @classmethod
    def map_step_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "step_id" in data and "id" not in data:
                data["id"] = data["step_id"]
        return data

class AgenticSOP(BaseModel):
    id: str
    title: str
    version: str
    preconditions: List[str] = Field(default_factory=list)
    global_governance: Optional[GlobalGovernance] = None
    steps: List[SOPStep] = Field(default_factory=list)
    rollback: List[SOPStep] = Field(default_factory=list)
