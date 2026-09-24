"""
Payments Router handling Stripe Checkout Session creation, subscription status,
cancellations, and webhook verification.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

from app.auth import get_current_user
from app.config import get_settings
from app.services import stripe_service
from app.services.workspace_service import verify_workspace_member, verify_workspace_admin_or_owner

router = APIRouter(prefix="/api/payments", tags=["Payments & Stripe"])
settings = get_settings()


from pydantic import BaseModel, Field, field_validator


class CheckoutSessionRequest(BaseModel):
    workspace_id: str = Field(..., description="ID of workspace to upgrade")
    plan_id: str = Field(..., description="Target plan ID ('pro' or 'enterprise')")

    @field_validator("workspace_id")
    @classmethod
    def validate_workspace_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("workspace_id cannot be empty")
        return v

    @field_validator("plan_id")
    @classmethod
    def validate_plan_id(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in ("pro", "enterprise"):
            raise ValueError("Invalid plan_id. Must be 'pro' or 'enterprise'")
        return v


class VerifyCheckoutSessionRequest(BaseModel):
    workspace_id: str = Field(..., description="ID of workspace")
    session_id: str = Field(..., description="Stripe Checkout Session ID")
    plan_id: Optional[str] = Field(None, description="Target plan ID ('pro' or 'enterprise')")

    @field_validator("workspace_id", "session_id")
    @classmethod
    def validate_non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Field cannot be empty")
        return v


class CancelSubscriptionRequest(BaseModel):
    workspace_id: str = Field(..., description="ID of workspace subscription to cancel")

    @field_validator("workspace_id")
    @classmethod
    def validate_workspace_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("workspace_id cannot be empty")
        return v


@router.post("/create-checkout-session")
async def create_checkout_session(
    payload: CheckoutSessionRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Creates a secure Stripe Checkout Session for upgrading a workspace plan.
    Price and limits are fetched from server configuration to prevent tampering.
    """
    user_id = current_user["id"]
    user_email = current_user.get("email")

    session_data = await stripe_service.create_checkout_session(
        workspace_id=payload.workspace_id,
        user_id=user_id,
        user_email=user_email,
        plan_id=payload.plan_id
    )

    return {
        "status": "success",
        "data": session_data
    }


@router.post("/verify-checkout-session")
async def verify_checkout_session(
    payload: VerifyCheckoutSessionRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Verifies Stripe session status upon redirect return and immediately activates workspace plan.
    Requires workspace owner or admin permission.
    """
    await verify_workspace_admin_or_owner(current_user["id"], payload.workspace_id)
    result = await stripe_service.verify_and_fulfill_checkout_session(
        session_id=payload.session_id,
        workspace_id=payload.workspace_id,
        plan_id_override=payload.plan_id,
        force_activate=True
    )
    return {
        "status": "success",
        "data": result
    }


@router.get("/status/{workspace_id}")
async def get_workspace_payment_status(
    workspace_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Retrieves the current subscription tier, quota limits, and payment history for a workspace.
    Requires workspace membership authorization.
    """
    await verify_workspace_member(current_user["id"], workspace_id)
    status_data = await stripe_service.get_payment_status(workspace_id)
    return {
        "status": "success",
        "data": status_data
    }


@router.post("/cancel-subscription")
async def cancel_subscription(
    payload: CancelSubscriptionRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Cancels an active workspace subscription at current period end.
    """
    user_id = current_user["id"]
    result = await stripe_service.cancel_subscription(
        workspace_id=payload.workspace_id,
        user_id=user_id
    )
    return result


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None, alias="stripe-signature")
):
    """
    Stripe Webhook endpoint. Verifies signature using STRIPE_WEBHOOK_SECRET
    and updates workspace quotas and payment logs idempotently.
    """
    payload = await request.body()

    if stripe_signature:
        event = stripe_service.verify_webhook_signature(payload, stripe_signature)
    elif settings.stripe_webhook_secret:
        raise HTTPException(status_code=400, detail="Missing required Stripe-Signature header")
    else:
        # Development fallback when Stripe secret key is not configured locally
        try:
            event = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON body or missing Stripe-Signature header")

    result = await stripe_service.process_webhook_event(event)
    return {"received": True, "result": result}
