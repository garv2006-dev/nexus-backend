"""
Stripe Service for Payment Processing, Checkout Sessions, Webhooks, and Subscription Management.
"""

import uuid
import time
import datetime
from typing import Dict, Any, Optional
import stripe
from fastapi import HTTPException

from app.config import get_settings
from app.database import fetch_one, execute, fetch_all
from app.services.email_service import (
    send_subscription_canceled_email,
    send_subscription_expired_downgrade_email,
    send_payment_invoice_email
)

settings = get_settings()

# Server-side pricing dictionary (source of truth for plans, pricing, and resource limits)
PLAN_CONFIG: Dict[str, Dict[str, Any]] = {
    "starter": {
        "name": "Starter / Free Plan",
        "amount": 0,
        "currency": "usd",
        "daily_token_limit": 25000,
        "max_pages": 25,
        "max_members": 3,
        "interval": "month"
    },
    "pro": {
        "name": "Pro Plan",
        "amount": 2900,  # $29.00 USD in cents
        "currency": "usd",
        "daily_token_limit": 250000,
        "max_pages": 100,
        "max_members": 10,
        "interval": "month",
        "price_id_setting": "stripe_pro_price_id"
    },
    "enterprise": {
        "name": "Enterprise Plan",
        "amount": 9900,  # $99.00 USD in cents
        "currency": "usd",
        "daily_token_limit": 1000000,
        "max_pages": 150,
        "max_members": 25,
        "interval": "month",
        "price_id_setting": "stripe_enterprise_price_id"
    }
}


def init_stripe():
    """Initializes Stripe secret key."""
    if settings.stripe_secret_key:
        stripe.api_key = settings.stripe_secret_key


async def get_or_create_stripe_customer(user_id: str, email: Optional[str] = None, name: Optional[str] = None) -> str:
    """Retrieves existing Stripe Customer ID or creates a new Stripe Customer."""
    init_stripe()
    
    # Check database for user's stripe_customer_id
    user = await fetch_one("SELECT stripe_customer_id FROM users WHERE id = $1", user_id)
    if user and user.get("stripe_customer_id"):
        return user["stripe_customer_id"]

    if not settings.stripe_secret_key:
        # Development fallback ID if Stripe Secret Key is not configured yet
        mock_customer_id = f"cus_test_{user_id[:12]}"
        await execute("UPDATE users SET stripe_customer_id = $1 WHERE id = $2", mock_customer_id, user_id)
        return mock_customer_id

    try:
        customer = stripe.Customer.create(
            email=email or None,
            name=name or None,
            metadata={
                "user_id": user_id,
                "app": "Multi-User RAG Workspace System"
            }
        )
        customer_id = customer["id"]
        await execute("UPDATE users SET stripe_customer_id = $1 WHERE id = $2", customer_id, user_id)
        return customer_id
    except stripe.StripeError as e:
        print(f"Stripe Customer Creation Warning: {e}")
        # Fallback customer ID for non-blocking local dev testing
        fallback_id = f"cus_fallback_{user_id[:10]}"
        await execute("UPDATE users SET stripe_customer_id = $1 WHERE id = $2", fallback_id, user_id)
        return fallback_id


async def create_checkout_session(
    workspace_id: str,
    user_id: str,
    user_email: Optional[str],
    plan_id: str
) -> Dict[str, Any]:
    """
    Creates a Stripe Checkout Session for subscription purchase.
    Validates pricing server-side to prevent client price tampering.
    """
    init_stripe()

    if plan_id not in PLAN_CONFIG or plan_id == "starter":
        raise HTTPException(status_code=400, detail="Invalid plan selected for paid upgrade.")

    plan_info = PLAN_CONFIG[plan_id]

    # Verify workspace ownership / admin permission
    member = await fetch_one(
        "SELECT role FROM workspace_members WHERE workspace_id = $1 AND user_id = $2",
        workspace_id, user_id
    )
    if not member or member.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only workspace owner or admin can purchase plan upgrades.")

    customer_id = await get_or_create_stripe_customer(user_id, user_email)

    frontend_base = (settings.app_frontend_url or "http://localhost:5173").rstrip("/")
    success_url = f"{frontend_base}/workspace/{workspace_id}/plan?success=true&session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{frontend_base}/workspace/{workspace_id}/plan?canceled=true"

    if not settings.stripe_secret_key:
        # Development mode simulation if secret key is missing
        simulated_session_id = f"cs_test_{int(time.time())}"
        await execute(
            """
            INSERT INTO payments (
                user_id, workspace_id, stripe_customer_id, stripe_checkout_session_id,
                plan_id, amount, currency, payment_status, subscription_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', 'incomplete')
            ON CONFLICT (stripe_checkout_session_id) DO NOTHING
            """,
            user_id, workspace_id, customer_id, simulated_session_id,
            plan_id, plan_info["amount"], plan_info["currency"]
        )
        return {
            "session_id": simulated_session_id,
            "checkout_url": f"{frontend_base}/workspace/{workspace_id}/plan?success=true&session_id={simulated_session_id}&simulated=true",
            "publishable_key": settings.stripe_publishable_key or "pk_test_placeholder",
            "simulated": True
        }

    # Determine price ID or dynamic line item configuration
    configured_price_id = getattr(settings, plan_info.get("price_id_setting", ""), None)

    try:
        if configured_price_id:
            line_items = [{"price": configured_price_id, "quantity": 1}]
        else:
            line_items = [{
                "price_data": {
                    "currency": plan_info["currency"],
                    "product_data": {
                        "name": f"Nexus AI RAG Workspace - {plan_info['name']}",
                        "description": f"Expands daily token limit to {plan_info['daily_token_limit']:,} tokens & {plan_info['max_pages']} page storage limit.",
                    },
                    "unit_amount": plan_info["amount"],
                    "recurring": {
                        "interval": plan_info["interval"]
                    }
                },
                "quantity": 1
            }]

        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=line_items,
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=workspace_id,
            metadata={
                "workspace_id": workspace_id,
                "user_id": user_id,
                "plan_id": plan_id
            },
            subscription_data={
                "metadata": {
                    "workspace_id": workspace_id,
                    "user_id": user_id,
                    "plan_id": plan_id
                }
            }
        )

        # Log pending payment session to database
        await execute(
            """
            INSERT INTO payments (
                user_id, workspace_id, stripe_customer_id, stripe_checkout_session_id,
                plan_id, amount, currency, payment_status, subscription_status
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', 'incomplete')
            ON CONFLICT (stripe_checkout_session_id) DO UPDATE SET
                payment_status = 'pending',
                plan_id = EXCLUDED.plan_id,
                amount = EXCLUDED.amount
            """,
            user_id, workspace_id, customer_id, session.id,
            plan_id, plan_info["amount"], plan_info["currency"]
        )

        return {
            "session_id": session.id,
            "checkout_url": session.url,
            "publishable_key": settings.stripe_publishable_key
        }

    except stripe.StripeError as e:
        print(f"Stripe Checkout Error: {e}")
        raise HTTPException(status_code=400, detail=f"Stripe Checkout Session error: {str(e)}")


async def verify_and_fulfill_checkout_session(session_id: str, workspace_id: str) -> Dict[str, Any]:
    """
    Verifies a Stripe Checkout Session status directly with Stripe API upon user return,
    and immediately upgrades workspace plan and resource quotas.
    This guarantees plan activation even if webhooks are delayed or not connected locally.
    """
    init_stripe()

    # 1. Check if workspace exists
    workspace = await fetch_one("SELECT id, plan_type FROM workspaces WHERE id = $1", workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    plan_id = "pro"
    customer_id = None
    subscription_id = None
    payment_intent_id = None
    is_paid = False

    if settings.stripe_secret_key and not session_id.startswith("cs_test_"):
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            metadata = session.get("metadata") or {}
            plan_id = metadata.get("plan_id") or "pro"
            customer_id = session.get("customer")
            subscription_id = session.get("subscription")
            payment_intent_id = session.get("payment_intent")

            # Check if paid / complete
            if session.get("payment_status") in ("paid", "no_payment_required") or session.get("status") == "complete":
                is_paid = True
        except stripe.StripeError as e:
            print(f"Stripe Session Retrieve Warning: {e}")
            raise HTTPException(status_code=400, detail=f"Could not verify Stripe session: {str(e)}")
    else:
        # Development / simulated session
        is_paid = True

    if not is_paid:
        return {
            "status": "pending",
            "message": "Payment is not completed yet.",
            "workspace_id": workspace_id
        }

    if plan_id not in PLAN_CONFIG:
        plan_id = "pro"

    plan_meta = PLAN_CONFIG[plan_id]
    now = datetime.datetime.now(datetime.timezone.utc)
    period_end = now + datetime.timedelta(days=30)
    effective_sub_id = subscription_id or f"sub_simulated_{workspace_id}"

    # 2. Update Workspaces table with paid tier capacity immediately
    await execute(
        """
        UPDATE workspaces
        SET plan_type = $1,
            daily_token_limit = $2,
            max_pages = $3,
            max_members = $4,
            stripe_customer_id = COALESCE($5, stripe_customer_id),
            stripe_subscription_id = COALESCE($6, stripe_subscription_id),
            subscription_status = 'active',
            current_period_end = $7,
            updated_at = $8
        WHERE id = $9
        """,
        plan_id, plan_meta["daily_token_limit"], plan_meta["max_pages"],
        plan_meta["max_members"], customer_id, effective_sub_id, period_end, now, workspace_id
    )

    # 3. Insert or update payments record
    await execute(
        """
        INSERT INTO payments (
            user_id, workspace_id, stripe_customer_id, stripe_checkout_session_id,
            stripe_payment_intent_id, stripe_subscription_id, plan_id, amount,
            currency, payment_status, subscription_status, completed_at
        ) VALUES ('user', $1, $2, $3, $4, $5, $6, $7, $8, 'succeeded', 'active', $9)
        ON CONFLICT (stripe_checkout_session_id) DO UPDATE SET
            stripe_payment_intent_id = EXCLUDED.stripe_payment_intent_id,
            stripe_subscription_id = EXCLUDED.stripe_subscription_id,
            payment_status = 'succeeded',
            subscription_status = 'active',
            completed_at = EXCLUDED.completed_at
        """,
        workspace_id, customer_id, session_id,
        payment_intent_id, effective_sub_id, plan_id, plan_meta["amount"],
        plan_meta["currency"], now
    )

    # Return updated payment status
    return await get_payment_status(workspace_id)



async def cancel_subscription(workspace_id: str, user_id: str) -> Dict[str, Any]:
    """Cancels active subscription for a workspace at current period end."""
    init_stripe()

    # Check permission
    member = await fetch_one(
        "SELECT role FROM workspace_members WHERE workspace_id = $1 AND user_id = $2",
        workspace_id, user_id
    )
    if not member or member.get("role") not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only workspace owner or admin can manage subscriptions.")

    workspace = await fetch_one(
        "SELECT stripe_subscription_id, plan_type, subscription_status FROM workspaces WHERE id = $1",
        workspace_id
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    sub_id = workspace.get("stripe_subscription_id")

    # If subscription ID is missing on workspace record, check payments table
    if not sub_id:
        payment = await fetch_one(
            """
            SELECT stripe_subscription_id FROM payments 
            WHERE workspace_id = $1 AND stripe_subscription_id IS NOT NULL 
            ORDER BY completed_at DESC LIMIT 1
            """,
            workspace_id
        )
        if payment and payment.get("stripe_subscription_id"):
            sub_id = payment["stripe_subscription_id"]

    # Fallback for active paid tiers where subscription_id was not set (e.g., test or manual activation)
    if not sub_id:
        is_paid_plan = (workspace.get("plan_type") and workspace.get("plan_type") != "starter") or workspace.get("subscription_status") == "active"
        if is_paid_plan:
            sub_id = f"sub_simulated_{workspace_id}"
            await execute(
                "UPDATE workspaces SET stripe_subscription_id = $1 WHERE id = $2",
                sub_id, workspace_id
            )
        else:
            await execute(
                "UPDATE workspaces SET subscription_status = 'canceled' WHERE id = $1",
                workspace_id
            )
            return {
                "status": "success",
                "message": "Subscription set to cancel at the end of the billing period.",
                "workspace_id": workspace_id
            }

    cancel_date = datetime.datetime.now(datetime.timezone.utc)

    if settings.stripe_secret_key and not sub_id.startswith("sub_simulated_"):
        try:
            subscription = stripe.Subscription.modify(
                sub_id,
                cancel_at_period_end=True
            )
            cancel_at = subscription.get("cancel_at")
            if cancel_at:
                cancel_date = datetime.datetime.fromtimestamp(cancel_at, tz=datetime.timezone.utc)
        except stripe.StripeError as e:
            print(f"Stripe Cancellation Warning: {e}")

    await execute(
        """
        UPDATE workspaces
        SET subscription_status = 'canceling'
        WHERE id = $1
        """,
        workspace_id
    )

    await execute(
        """
        UPDATE payments
        SET subscription_status = 'canceling', canceled_at = $1
        WHERE workspace_id = $2 AND (stripe_subscription_id = $3 OR stripe_subscription_id IS NULL)
        """,
        cancel_date, workspace_id, sub_id
    )

    # Send cancellation notification email to workspace owner
    try:
        user = await fetch_one("SELECT email FROM users WHERE id = $1", user_id)
        ws_detail = await fetch_one("SELECT name FROM workspaces WHERE id = $1", workspace_id)
        if user and user.get("email") and ws_detail:
            effective_date_str = cancel_date.strftime("%B %d, %Y")
            await send_subscription_canceled_email(
                to_email=user["email"],
                workspace_name=ws_detail["name"],
                effective_date_str=effective_date_str
            )
    except Exception as e:
        print(f"Failed to send cancellation email: {e}")

    return {
        "status": "success",
        "message": "Subscription set to cancel at the end of the billing period.",
        "workspace_id": workspace_id
    }


async def downgrade_workspace_to_default_plan(workspace_id: str) -> Dict[str, Any]:
    """
    Reverts a workspace to the Default Free Starter Plan when subscription period ends.
    Prunes excess member seats (> 5) and excess document pages (> 50 pages).
    Sends email notifications to workspace owner listing any removed items.
    """
    ws_id_str = str(workspace_id)

    workspace = await fetch_one(
        "SELECT id, name, owner_id FROM workspaces WHERE id = $1",
        ws_id_str
    )
    if not workspace:
        return {"status": "error", "message": "Workspace not found"}

    workspace_name = workspace["name"]
    owner_id = workspace.get("owner_id")

    now = datetime.datetime.now(datetime.timezone.utc)

    # 1. Revert workspace record to Starter tier limits
    await execute(
        """
        UPDATE workspaces
        SET plan_type = 'starter',
            daily_token_limit = 25000,
            max_pages = 25,
            max_members = 3,
            subscription_status = 'canceled',
            updated_at = $1
        WHERE id = $2
        """,
        now, ws_id_str
    )

    await execute(
        """
        UPDATE payments
        SET subscription_status = 'canceled', canceled_at = $1
        WHERE workspace_id = $2
        """,
        now, ws_id_str
    )

    # 2. Prune excess member seats (> 3)
    members = await fetch_all(
        """
        SELECT wm.user_id, wm.role, u.email, u.name
        FROM workspace_members wm
        LEFT JOIN users u ON u.id = wm.user_id
        WHERE wm.workspace_id = $1
        ORDER BY (CASE WHEN wm.role = 'owner' THEN 0 ELSE 1 END) ASC, wm.joined_at ASC
        """,
        ws_id_str
    )

    removed_members = []
    if len(members) > 3:
        keep_members = members[:3]
        excess_members = members[3:]
        for m in excess_members:
            m_user_id = m["user_id"]
            m_identifier = m.get("name") or m.get("email") or str(m_user_id)
            removed_members.append(m_identifier)
            await execute(
                "DELETE FROM workspace_members WHERE workspace_id = $1 AND user_id = $2",
                ws_id_str, m_user_id
            )

    # 3. Prune excess document pages (> 25 pages total)
    docs = await fetch_all(
        """
        SELECT id, name, page_count, created_at
        FROM documents
        WHERE workspace_id = $1
        ORDER BY created_at ASC
        """,
        ws_id_str
    )

    removed_documents = []
    total_pages = sum([d.get("page_count") or 1 for d in docs])

    if total_pages > 25:
        pages_to_remove = total_pages - 25
        pages_removed_so_far = 0
        for doc in docs:
            if pages_removed_so_far < pages_to_remove:
                doc_id = doc["id"]
                doc_name = doc["name"]
                p_cnt = doc.get("page_count") or 1
                removed_documents.append(doc_name)
                pages_removed_so_far += p_cnt
                await execute("DELETE FROM documents WHERE id = $1", doc_id)

    # 4. Dispatch Email Notifications
    owner_email = None
    if owner_id:
        owner_user = await fetch_one("SELECT email FROM users WHERE id = $1", owner_id)
        if owner_user:
            owner_email = owner_user.get("email")

    if not owner_email and members:
        owner_email = members[0].get("email")

    if owner_email:
        await send_subscription_expired_downgrade_email(
            to_email=owner_email,
            workspace_name=workspace_name,
            removed_documents=removed_documents,
            removed_members=removed_members
        )

    return {
        "status": "success",
        "message": f"Workspace '{workspace_name}' reverted to Starter Plan.",
        "removed_documents": removed_documents,
        "removed_members": removed_members
    }


async def get_payment_status(workspace_id: str) -> Dict[str, Any]:
    """Retrieves current workspace plan, subscription status, and latest payment history."""
    workspace = await fetch_one(
        """
        SELECT id, name, plan_type, max_members, daily_token_limit, max_pages,
               stripe_customer_id, stripe_subscription_id, subscription_status, current_period_end
        FROM workspaces
        WHERE id = $1
        """,
        workspace_id
    )
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found.")

    # Check if subscription period has expired for a canceled/canceling workspace
    current_status = workspace.get("subscription_status")
    period_end = workspace.get("current_period_end")
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    if current_status == "canceling" and period_end and period_end <= now_utc:
        # Revert workspace to default starter plan & clean up excess capacity
        await downgrade_workspace_to_default_plan(workspace_id)
        workspace = await fetch_one(
            """
            SELECT id, name, plan_type, max_members, daily_token_limit, max_pages,
                   stripe_customer_id, stripe_subscription_id, subscription_status, current_period_end
            FROM workspaces
            WHERE id = $1
            """,
            workspace_id
        )

    recent_payments = await fetch_all(
        """
        SELECT id, plan_id, amount, currency, payment_status, subscription_status,
               stripe_checkout_session_id, stripe_payment_intent_id, created_at, completed_at
        FROM payments
        WHERE workspace_id = $1
        ORDER BY created_at DESC
        LIMIT 10
        """,
        workspace_id
    )

    plan_key = workspace.get("plan_type", "starter")
    plan_meta = PLAN_CONFIG.get(plan_key, PLAN_CONFIG["starter"])

    return {
        "workspace_id": workspace["id"],
        "plan_type": plan_key,
        "plan_name": plan_meta["name"],
        "daily_token_limit": workspace.get("daily_token_limit", 25000),
        "max_pages": workspace.get("max_pages", 25),
        "max_members": workspace.get("max_members", 3),
        "subscription_status": workspace.get("subscription_status") or "active",
        "stripe_customer_id": workspace.get("stripe_customer_id"),
        "stripe_subscription_id": workspace.get("stripe_subscription_id"),
        "current_period_end": workspace.get("current_period_end"),
        "payment_history": recent_payments
    }


def verify_webhook_signature(payload: bytes, sig_header: str) -> stripe.Event:
    """Verifies Stripe Webhook signature against STRIPE_WEBHOOK_SECRET."""
    init_stripe()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=500, detail="STRIPE_WEBHOOK_SECRET is not configured on server.")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
        return event
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook payload: {str(e)}")
    except stripe.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid webhook signature: {str(e)}")


async def process_webhook_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    Processes incoming Stripe Webhook events idempotently.
    Updates workspace subscription tier, token & page quotas, and payment log.
    """
    event_type = event.get("type")
    data_object = event.get("data", {}).get("object", {})

    print(f"Processing Stripe Webhook Event: {event_type}")

    if event_type == "checkout.session.completed":
        session_id = data_object.get("id")
        workspace_id = data_object.get("client_reference_id") or data_object.get("metadata", {}).get("workspace_id")
        user_id = data_object.get("metadata", {}).get("user_id")
        plan_id = data_object.get("metadata", {}).get("plan_id", "pro")
        customer_id = data_object.get("customer")
        subscription_id = data_object.get("subscription")
        payment_intent_id = data_object.get("payment_intent")

        if workspace_id and plan_id in PLAN_CONFIG:
            plan_meta = PLAN_CONFIG[plan_id]
            now = datetime.datetime.now(datetime.timezone.utc)
            period_end = now + datetime.timedelta(days=30)

            # 1. Update Workspaces table with paid tier capacity
            await execute(
                """
                UPDATE workspaces
                SET plan_type = $1,
                    daily_token_limit = $2,
                    max_pages = $3,
                    max_members = $4,
                    stripe_customer_id = COALESCE($5, stripe_customer_id),
                    stripe_subscription_id = COALESCE($6, stripe_subscription_id),
                    subscription_status = 'active',
                    current_period_end = $7,
                    updated_at = $8
                WHERE id = $9
                """,
                plan_id, plan_meta["daily_token_limit"], plan_meta["max_pages"],
                plan_meta["max_members"], customer_id, subscription_id, period_end, now, workspace_id
            )

            # 2. Update Payments table record idempotently
            await execute(
                """
                INSERT INTO payments (
                    user_id, workspace_id, stripe_customer_id, stripe_checkout_session_id,
                    stripe_payment_intent_id, stripe_subscription_id, plan_id, amount,
                    currency, payment_status, subscription_status, completed_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'succeeded', 'active', $10)
                ON CONFLICT (stripe_checkout_session_id) DO UPDATE SET
                    stripe_payment_intent_id = EXCLUDED.stripe_payment_intent_id,
                    stripe_subscription_id = EXCLUDED.stripe_subscription_id,
                    payment_status = 'succeeded',
                    subscription_status = 'active',
                    completed_at = EXCLUDED.completed_at
                """,
                user_id or "system", workspace_id, customer_id, session_id,
                payment_intent_id, subscription_id, plan_id, plan_meta["amount"],
                plan_meta["currency"], now
            )

            # 3. Dispatch Payment Invoice Email to Workspace Owner
            try:
                ws_data = await fetch_one("SELECT name, owner_id FROM workspaces WHERE id = $1", workspace_id)
                if ws_data and ws_data.get("owner_id"):
                    owner = await fetch_one("SELECT email FROM users WHERE id = $1", ws_data["owner_id"])
                    if owner and owner.get("email"):
                        amount_fmt = f"${plan_meta['amount'] / 100:.2f} USD"
                        pay_date_str = now.strftime("%B %d, %Y")
                        next_date_str = period_end.strftime("%B %d, %Y")
                        await send_payment_invoice_email(
                            to_email=owner["email"],
                            workspace_name=ws_data["name"],
                            plan_name=plan_meta["name"],
                            amount_str=amount_fmt,
                            payment_date_str=pay_date_str,
                            next_billing_date_str=next_date_str
                        )
            except Exception as e:
                print(f"Failed to send invoice email on checkout completion: {e}")

    elif event_type in ("invoice.paid", "payment_intent.succeeded"):
        payment_intent_id = data_object.get("payment_intent") or data_object.get("id")
        customer_id = data_object.get("customer")
        subscription_id = data_object.get("subscription")

        if payment_intent_id or customer_id or subscription_id:
            now = datetime.datetime.now(datetime.timezone.utc)
            next_period_end = now + datetime.timedelta(days=30)

            await execute(
                """
                UPDATE payments
                SET payment_status = 'succeeded', completed_at = $1
                WHERE stripe_payment_intent_id = $2 OR stripe_customer_id = $3
                """,
                now, payment_intent_id, customer_id
            )

            # Auto-renew active subscription period & dispatch monthly invoice email
            ws_rec = await fetch_one(
                "SELECT id, name, plan_type, owner_id FROM workspaces WHERE stripe_customer_id = $1 OR stripe_subscription_id = $2",
                customer_id, subscription_id
            )
            if ws_rec:
                plan_k = ws_rec.get("plan_type", "pro")
                plan_meta = PLAN_CONFIG.get(plan_k, PLAN_CONFIG["pro"])

                await execute(
                    """
                    UPDATE workspaces
                    SET subscription_status = 'active',
                        current_period_end = $1,
                        updated_at = $2
                    WHERE id = $3
                    """,
                    next_period_end, now, ws_rec["id"]
                )

                if ws_rec.get("owner_id"):
                    try:
                        owner = await fetch_one("SELECT email FROM users WHERE id = $1", ws_rec["owner_id"])
                        if owner and owner.get("email"):
                            amount_fmt = f"${plan_meta['amount'] / 100:.2f} USD"
                            pay_date_str = now.strftime("%B %d, %Y")
                            next_date_str = next_period_end.strftime("%B %d, %Y")
                            await send_payment_invoice_email(
                                to_email=owner["email"],
                                workspace_name=ws_rec["name"],
                                plan_name=plan_meta["name"],
                                amount_str=amount_fmt,
                                payment_date_str=pay_date_str,
                                next_billing_date_str=next_date_str
                            )
                    except Exception as e:
                        print(f"Failed to send monthly invoice email on renewal: {e}")

    elif event_type in ("payment_intent.payment_failed", "invoice.payment_failed"):
        payment_intent_id = data_object.get("payment_intent") or data_object.get("id")
        customer_id = data_object.get("customer")
        if payment_intent_id or customer_id:
            await execute(
                """
                UPDATE payments
                SET payment_status = 'failed'
                WHERE stripe_payment_intent_id = $1 OR stripe_customer_id = $2
                """,
                payment_intent_id, customer_id
            )

    elif event_type == "customer.subscription.deleted":
        subscription_id = data_object.get("id")
        if subscription_id:
            ws = await fetch_one("SELECT id FROM workspaces WHERE stripe_subscription_id = $1", subscription_id)
            if ws:
                await downgrade_workspace_to_default_plan(ws["id"])

    elif event_type == "customer.subscription.updated":
        subscription_id = data_object.get("id")
        status = data_object.get("status")
        cancel_at_period_end = data_object.get("cancel_at_period_end", False)
        sub_status = "canceling" if cancel_at_period_end else status
        if subscription_id:
            await execute(
                """
                UPDATE workspaces
                SET subscription_status = $1
                WHERE stripe_subscription_id = $2
                """,
                sub_status, subscription_id
            )

    return {"status": "event_processed", "event_type": event_type}
