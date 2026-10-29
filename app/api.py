from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.agent.service import AgentService, RunNotFound, RunStateError
from app.config import get_settings
from app.llm.base import LLMConfigError
from app.tools import build_registry

router = APIRouter()


class RunRequest(BaseModel):
    request: str = Field(min_length=3, max_length=2000, examples=["Prepare a sales report for this month and identify the products with declining sales."])
    provider: str | None = Field(None, description="mock | openai | anthropic | gemini (default from LLM_PROVIDER)")
    api_key: str | None = Field(None, repr=False, description="Optional. Overrides the key from .env for this run only; never stored.")
    model: str | None = Field(None, description="Optional model name override")


class ApprovalRequest(BaseModel):
    approve: bool
    api_key: str | None = Field(None, repr=False)


def get_service() -> AgentService:
    return AgentService()


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/tools")
def list_tools():
    s = get_settings()
    return [{"name": t.name, "description": t.description, "read_only": not t.mutating, "requires_approval": t.requires_approval}
            for t in build_registry(s).all()]


@router.post("/runs")
def create_run(body: RunRequest, svc: AgentService = Depends(get_service)):
    try:
        return svc.start_run(body.request, body.provider, body.api_key, body.model)
    except LLMConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/runs/{run_id}")
def get_run(run_id: str, svc: AgentService = Depends(get_service)):
    try:
        return svc.get_run(run_id)
    except RunNotFound:
        raise HTTPException(status_code=404, detail="Run not found")


@router.get("/runs/{run_id}/logs")
def get_logs(run_id: str, svc: AgentService = Depends(get_service)):
    try:
        return svc.get_logs(run_id)
    except RunNotFound:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/approval")
def decide(run_id: str, body: ApprovalRequest, svc: AgentService = Depends(get_service)):
    try:
        return svc.resume_run(run_id, body.approve, body.api_key)
    except RunNotFound:
        raise HTTPException(status_code=404, detail="Run not found")
    except RunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
