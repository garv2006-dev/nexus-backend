import logging
import httpx
from typing import List, Optional
from email.utils import formataddr, parseaddr

from app.config import get_settings

logger = logging.getLogger(__name__)


async def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    plain_text: str
) -> bool:
    """
    Sends an email using configured email service provider (Direct SMTP, Mailjet, Brevo, or Resend API).
    Includes anti-spam transactional headers and clean MIME formatting for optimal inbox deliverability.
    """
    settings = get_settings()

    # 1. Try Direct SMTP (Gmail / Brevo / Custom SMTP) if configured
    if settings.smtp_host and settings.smtp_user and settings.smtp_password:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            
            # Format From with display name if available
            parsed_name, parsed_email = parseaddr(settings.smtp_from or settings.smtp_user)
            sender_name = parsed_name if parsed_name else "Nexus AI"
            sender_email = parsed_email if parsed_email else settings.smtp_user
            msg["From"] = formataddr((sender_name, sender_email))
            msg["To"] = to_email
            msg["Reply-To"] = sender_email
            
            # Anti-spam deliverability headers
            msg["X-Mailer"] = "NexusAI-EmailService/1.0"
            msg["Auto-Submitted"] = "auto-generated"
            msg["X-Auto-Response-Suppress"] = "All"

            # Attach plain text first, HTML second (RFC standard for multipart/alternative)
            msg.attach(MIMEText(plain_text, "plain", "utf-8"))
            msg.attach(MIMEText(html_content, "html", "utf-8"))

            envelope_sender = sender_email

            if settings.smtp_port == 465:
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(envelope_sender, [to_email], msg.as_string())
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(envelope_sender, [to_email], msg.as_string())

            logger.info(f"Email sent to {to_email} via SMTP ({settings.smtp_host})")
            return True
        except Exception as e:
            logger.error(f"SMTP sending failed: {str(e)}")

    # 2. Try Mailjet REST API if configured
    if settings.mailjet_api_key and settings.mailjet_secret_key:
        try:
            parsed_name, parsed_email = parseaddr(settings.smtp_from or settings.email_from)
            sender_email = parsed_email if parsed_email else "noreply@nexusai.com"
            sender_name = parsed_name if parsed_name else "Nexus AI"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.mailjet.com/v3.1/send",
                    auth=(settings.mailjet_api_key, settings.mailjet_secret_key),
                    headers={"Content-Type": "application/json"},
                    json={
                        "Messages": [
                            {
                                "From": {"Email": sender_email, "Name": sender_name},
                                "To": [{"Email": to_email}],
                                "Subject": subject,
                                "TextPart": plain_text,
                                "HTMLPart": html_content,
                                "Headers": {
                                    "Reply-To": sender_email,
                                    "Auto-Submitted": "auto-generated"
                                }
                            }
                        ]
                    }
                )
                if response.status_code in (200, 201, 202):
                    logger.info(f"Email sent to {to_email} via Mailjet API.")
                    return True
                else:
                    logger.error(f"Mailjet API error ({response.status_code}): {response.text}")
        except Exception as e:
            logger.error(f"Failed to send email via Mailjet API: {str(e)}")

    # 3. Try Brevo REST API if configured
    if settings.brevo_api_key:
        try:
            parsed_name, parsed_email = parseaddr(settings.smtp_from or settings.smtp_user or settings.email_from)
            sender_email = parsed_email if parsed_email else "noreply@nexusai.com"
            sender_name = parsed_name if parsed_name else "Nexus AI"

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={
                        "api-key": settings.brevo_api_key,
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    },
                    json={
                        "sender": {"name": sender_name, "email": sender_email},
                        "to": [{"email": to_email}],
                        "replyTo": {"email": sender_email, "name": sender_name},
                        "subject": subject,
                        "htmlContent": html_content,
                        "textContent": plain_text,
                        "headers": {
                            "Auto-Submitted": "auto-generated",
                            "X-Auto-Response-Suppress": "All"
                        }
                    }
                )
                if response.status_code in (200, 201, 202):
                    logger.info(f"Email sent to {to_email} via Brevo API.")
                    return True
                else:
                    logger.error(f"Brevo API error ({response.status_code}): {response.text}")
        except Exception as e:
            logger.error(f"Failed to send email via Brevo API: {str(e)}")

    # 4. Try Resend API if configured
    if settings.resend_api_key:
        try:
            parsed_name, parsed_email = parseaddr(settings.email_from)
            sender_email = parsed_email if parsed_email else "onboarding@resend.dev"
            sender_name = parsed_name if parsed_name else "Nexus AI"
            from_formatted = formataddr((sender_name, sender_email))

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings.resend_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "from": from_formatted,
                        "to": [to_email],
                        "reply_to": sender_email,
                        "subject": subject,
                        "html": html_content,
                        "text": plain_text,
                        "headers": {
                            "Auto-Submitted": "auto-generated",
                            "X-Auto-Response-Suppress": "All"
                        }
                    }
                )
                if response.status_code in (200, 201):
                    logger.info(f"Email sent to {to_email} via Resend.")
                    return True
                else:
                    logger.error(f"Resend API error ({response.status_code}): {response.text}")
        except Exception as e:
            logger.error(f"Failed to send email via Resend: {str(e)}")

    logger.warning(f"No valid email provider configured for recipient: {to_email}")
    return False


def _build_email_template(
    title: str,
    body_html: str,
    cta_url: Optional[str] = None,
    cta_text: Optional[str] = None,
    preheader: str = "",
    footer_note: str = "",
    badge_text: Optional[str] = None,
    badge_bg: Optional[str] = None,
    badge_color: Optional[str] = None,
    badge_border: Optional[str] = None
) -> str:
    """
    Builds a clean, simple, lightweight HTML email template designed for 100% inbox deliverability.
    Avoids heavy tables or complex elements that trigger spam filters.
    """
    cta_section = ""
    if cta_url and cta_text:
        cta_section = f"""
        <p style="margin: 24px 0;">
          <a href="{cta_url}" target="_blank" style="background-color: #2563eb; color: #ffffff; text-decoration: none; padding: 11px 22px; border-radius: 6px; font-weight: 600; font-size: 14px; display: inline-block;">
            {cta_text}
          </a>
        </p>
        <p style="font-size: 13px; color: #6b7280; margin: 16px 0; word-break: break-all;">
          If the button above does not work, copy and paste this link into your browser:<br>
          <a href="{cta_url}" style="color: #2563eb; text-decoration: underline;">{cta_url}</a>
        </p>
        """

    preheader_html = ""
    if preheader:
        preheader_html = f"""
        <div style="display: none; max-height: 0px; overflow: hidden; font-size: 1px; line-height: 1px; color: #ffffff; opacity: 0;">
          {preheader} &nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;&nbsp;&zwnj;
        </div>
        """

    footer_content = footer_note if footer_note else "This email was sent by Nexus AI."

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #ffffff; color: #111827; margin: 0; padding: 24px 16px; line-height: 1.6;">
  {preheader_html}
  <div style="max-width: 520px; margin: 0 auto; padding: 12px 0;">
    <h2 style="font-size: 18px; font-weight: 600; color: #111827; margin: 0 0 16px 0;">{title}</h2>
    
    <div style="font-size: 15px; color: #374151; margin-bottom: 20px;">
      {body_html}
    </div>

    {cta_section}

    <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 32px 0 16px 0;" />

    <p style="font-size: 12px; color: #6b7280; margin: 0; line-height: 1.5;">
      {footer_content}<br>
      <span style="color: #9ca3af;">Nexus AI Workspace System</span>
    </p>
  </div>
</body>
</html>
"""


def _clean_inviter_display_name(inviter_name: str) -> str:
    if not inviter_name or not inviter_name.strip():
        return "A team member"
    return inviter_name.strip()


async def send_workspace_invitation_email(
    to_email: str,
    inviter_name: str,
    workspace_name: str,
    invitation_url: str
) -> bool:
    """
    Sends a simple, high-deliverability workspace invitation email.
    """
    display_inviter = _clean_inviter_display_name(inviter_name)
    subject = f"{display_inviter} invited you to join '{workspace_name}'"
    preheader = f"{display_inviter} invited you to join the '{workspace_name}' workspace on Nexus AI."

    body_html = f"""
    <p style="margin: 0 0 12px 0;">Hi,</p>
    <p style="margin: 0 0 12px 0;">
      <strong>{display_inviter}</strong> invited you to join the <strong>{workspace_name}</strong> workspace on Nexus AI.
    </p>
    <p style="margin: 0 0 12px 0;">
      Accept your invitation to collaborate with your team and access workspace tools:
    </p>
    """

    html_content = _build_email_template(
        title=f"Join '{workspace_name}' on Nexus AI",
        body_html=body_html,
        cta_url=invitation_url,
        cta_text="Accept Invitation",
        preheader=preheader,
        footer_note=f"This invitation was sent to {to_email} by {display_inviter} via Nexus AI."
    )

    plain_text = (
        f"Hi,\n\n"
        f"{display_inviter} invited you to join the '{workspace_name}' workspace on Nexus AI.\n\n"
        f"Accept your invitation here:\n{invitation_url}\n\n"
        f"Nexus AI Team"
    )

    return await send_email(to_email, subject, html_content, plain_text)


async def send_subscription_canceled_email(
    to_email: str,
    workspace_name: str,
    effective_date_str: str
) -> bool:
    """
    Sends notification email when subscription cancellation is initiated.
    """
    subject = f"Subscription Cancellation Scheduled for '{workspace_name}'"
    preheader = f"Your subscription for '{workspace_name}' is set to cancel on {effective_date_str}."

    body_html = f"""
    <p style="margin: 0 0 12px 0;">Hi,</p>
    <p style="margin: 0 0 12px 0;">
      The subscription cancellation for workspace <strong>'{workspace_name}'</strong> has been confirmed.
    </p>
    <p style="margin: 0 0 12px 0; background-color: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; padding: 12px; font-size: 14px; color: #92400e;">
      <strong>Paid Tier Benefits Active Until:</strong> {effective_date_str}<br>
      When your billing period ends, your workspace will automatically revert to the Default Free Starter Plan.
    </p>
    <p style="margin: 0;">
      You can upgrade or reactivate your subscription at any time directly from your workspace Plan settings page.
    </p>
    """

    html_content = _build_email_template(
        title="Subscription Cancellation Confirmed",
        body_html=body_html,
        preheader=preheader,
        footer_note="This account notification was sent regarding your billing status on Nexus AI."
    )

    plain_text = (
        f"Subscription Cancellation Confirmed\n\n"
        f"The subscription for workspace '{workspace_name}' has been scheduled for cancellation.\n"
        f"Paid Tier Benefits Active Until: {effective_date_str}\n"
        f"After this date, the workspace will automatically revert to Default Free Starter Plan.\n\n"
        f"Nexus AI Team"
    )

    return await send_email(to_email, subject, html_content, plain_text)


async def send_subscription_expired_downgrade_email(
    to_email: str,
    workspace_name: str,
    removed_documents: list = None,
    removed_members: list = None
) -> bool:
    """
    Sends notification email when a paid subscription period ends and workspace reverts to Default Starter Plan.
    """
    subject = f"Workspace '{workspace_name}' Reverted to Starter Plan"
    preheader = f"Your workspace '{workspace_name}' has completed its subscription and reverted to the Free Starter Plan."

    docs_html = ""
    docs_text = ""
    if removed_documents:
        items = "".join([f"<li>{doc}</li>" for doc in removed_documents])
        docs_html = f"""
        <div style="margin-top: 12px; background-color: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 12px; font-size: 13px; color: #991b1b;">
          <strong>Removed Documents (Exceeded Starter Limit):</strong>
          <ul style="margin: 6px 0 0 0; padding-left: 18px;">{items}</ul>
        </div>
        """
        docs_text = f"\n\nRemoved Documents:\n" + "\n".join([f"- {doc}" for doc in removed_documents])

    members_html = ""
    members_text = ""
    if removed_members:
        items = "".join([f"<li>{m}</li>" for m in removed_members])
        members_html = f"""
        <div style="margin-top: 12px; background-color: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: 12px; font-size: 13px; color: #991b1b;">
          <strong>Removed Member Seats (Exceeded Starter Limit):</strong>
          <ul style="margin: 6px 0 0 0; padding-left: 18px;">{items}</ul>
        </div>
        """
        members_text = f"\n\nRemoved Member Seats:\n" + "\n".join([f"- {m}" for m in removed_members])

    body_html = f"""
    <p style="margin: 0 0 12px 0;">Hi,</p>
    <p style="margin: 0 0 12px 0;">
      Your workspace <strong>'{workspace_name}'</strong> has completed its paid subscription cycle and has automatically reverted to the <strong>Default Free Starter Plan</strong> (25,000 daily tokens, 25 max pages capacity, 3 member seats).
    </p>
    {docs_html}
    {members_html}
    <p style="margin: 12px 0 0 0;">
      You can upgrade your workspace back to Pro or Enterprise at any time to restore higher limits and member capacity.
    </p>
    """

    html_content = _build_email_template(
        title="Default Starter Plan Activated",
        body_html=body_html,
        preheader=preheader,
        footer_note="This transactional email was sent to notify you of workspace quota adjustments."
    )

    plain_text = (
        f"Workspace Plan Reverted\n\n"
        f"Workspace '{workspace_name}' has reverted to the Default Free Starter Plan.{docs_text}{members_text}\n\n"
        f"You can upgrade at any time to restore higher quotas.\n\n"
        f"Nexus AI Team"
    )

    return await send_email(to_email, subject, html_content, plain_text)


async def send_payment_invoice_email(
    to_email: str,
    workspace_name: str,
    plan_name: str,
    amount_str: str,
    payment_date_str: str,
    next_billing_date_str: str
) -> bool:
    """
    Sends a monthly payment receipt / invoice email to the workspace owner upon successful subscription payment.
    """
    subject = f"Payment Receipt: {plan_name} for '{workspace_name}'"
    preheader = f"Payment receipt of {amount_str} for {plan_name} on workspace '{workspace_name}'."

    body_html = f"""
    <p style="margin: 0 0 12px 0;">Hi,</p>
    <p style="margin: 0 0 12px 0;">
      Thank you for your payment! Your subscription payment for workspace <strong>'{workspace_name}'</strong> has been processed successfully.
    </p>
    <div style="background-color: #f9fafb; border: 1px solid #e5e7eb; border-radius: 6px; padding: 16px; margin: 16px 0; font-size: 14px; color: #374151;">
      <p style="margin: 0 0 6px 0;"><strong>Workspace:</strong> {workspace_name}</p>
      <p style="margin: 0 0 6px 0;"><strong>Plan:</strong> {plan_name}</p>
      <p style="margin: 0 0 6px 0;"><strong>Payment Date:</strong> {payment_date_str}</p>
      <p style="margin: 0 0 6px 0;"><strong>Next Billing Date:</strong> {next_billing_date_str}</p>
      <p style="margin: 10px 0 0 0; padding-top: 10px; border-top: 1px solid #e5e7eb; font-weight: 600; color: #111827;">
        Amount Paid: <span style="color: #16a34a;">{amount_str}</span>
      </p>
    </div>
    <p style="margin: 0;">
      Your workspace quotas and Pro capabilities remain fully active.
    </p>
    """

    html_content = _build_email_template(
        title="Payment Receipt",
        body_html=body_html,
        preheader=preheader,
        footer_note="This payment receipt was sent to your registered billing email address."
    )

    plain_text = (
        f"Payment Receipt - {plan_name}\n\n"
        f"Workspace: {workspace_name}\n"
        f"Plan: {plan_name}\n"
        f"Payment Date: {payment_date_str}\n"
        f"Next Billing Date: {next_billing_date_str}\n"
        f"Amount Paid: {amount_str}\n\n"
        f"Nexus AI Team"
    )

    return await send_email(to_email, subject, html_content, plain_text)





