import logging
import httpx
from ..config import get_settings

logger = logging.getLogger(__name__)


async def send_workspace_invitation_email(
    to_email: str,
    inviter_name: str,
    workspace_name: str,
    invitation_url: str
) -> bool:
    """
    Sends an invitation email to join a workspace using Resend API (or fallback logging).
    """
    settings = get_settings()

    subject = f"Invitation to join '{workspace_name}' on Nexus AI"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{
          font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
          background-color: #090d16;
          color: #f8fafc;
          margin: 0;
          padding: 40px 20px;
        }}
        .card {{
          max-width: 520px;
          margin: 0 auto;
          background-color: #0f172a;
          border: 1px solid #1e293b;
          border-radius: 20px;
          padding: 36px;
          box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5);
        }}
        .badge {{
          display: inline-block;
          background-color: rgba(99, 102, 241, 0.15);
          color: #818cf8;
          font-size: 12px;
          font-weight: 600;
          padding: 4px 12px;
          border-radius: 9999px;
          border: 1px solid rgba(99, 102, 241, 0.3);
          margin-bottom: 16px;
        }}
        .title {{
          font-size: 22px;
          font-weight: 700;
          color: #ffffff;
          margin-bottom: 12px;
          line-height: 1.3;
        }}
        .text {{
          font-size: 14px;
          color: #94a3b8;
          line-height: 1.6;
          margin-bottom: 24px;
        }}
        .button-wrapper {{
          text-align: center;
          margin: 32px 0;
        }}
        .button {{
          display: inline-block;
          background-color: #4f46e5;
          color: #ffffff !important;
          text-decoration: none;
          font-size: 14px;
          font-weight: 600;
          padding: 14px 28px;
          border-radius: 12px;
          box-shadow: 0 4px 14px rgba(79, 70, 229, 0.4);
        }}
        .footer {{
          font-size: 12px;
          color: #64748b;
          margin-top: 32px;
          border-top: 1px solid #1e293b;
          padding-top: 20px;
          text-align: center;
        }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="badge">Nexus Workspace Invitation</div>
        <div class="title">You've been invited to collaborate</div>
        <p class="text">
          <strong style="color: #f1f5f9;">{inviter_name}</strong> invited you to join the workspace <strong style="color: #f1f5f9;">'{workspace_name}'</strong> on Nexus AI.
        </p>
        <div class="button-wrapper">
          <a href="{invitation_url}" class="button">Accept Invitation</a>
        </div>
        <p class="text" style="font-size: 12px;">
          Or copy and paste this URL into your browser:<br>
          <a href="{invitation_url}" style="color: #818cf8; word-break: break-all;">{invitation_url}</a>
        </p>
        <div class="footer">
          Nexus AI Workspace System • Multi-Tenant RAG
        </div>
      </div>
    </body>
    </html>
    """

    plain_text = f"""
You've been invited to join '{workspace_name}' on Nexus AI by {inviter_name}.

Accept your invitation here:
{invitation_url}
    """.strip()

    # 1. Try Direct SMTP (Gmail / Brevo / Custom SMTP) if configured
    if settings.smtp_host and settings.smtp_user and settings.smtp_password:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        try:
            from email.utils import parseaddr

            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.smtp_from or settings.smtp_user
            msg["To"] = to_email

            msg.attach(MIMEText(plain_text, "plain"))
            msg.attach(MIMEText(html_content, "html"))

            # Envelope sender must be clean email address (e.g. garvvariya0@gmail.com)
            parsed_email = parseaddr(settings.smtp_from)[1] if settings.smtp_from else ""
            envelope_sender = parsed_email if parsed_email else settings.smtp_user

            if settings.smtp_port == 465:
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(envelope_sender, [to_email], msg.as_string())
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(envelope_sender, [to_email], msg.as_string())

            logger.info(f"Invitation email sent to {to_email} via SMTP ({settings.smtp_host})")
            return True
        except Exception as e:
            logger.error(f"SMTP sending failed: {str(e)}")

    # 2. Try Brevo REST API if configured
    if settings.brevo_api_key:
        try:
            from email.utils import parseaddr
            parsed_name, parsed_email = parseaddr(settings.smtp_from or settings.smtp_user)
            sender_email = parsed_email if parsed_email else (settings.smtp_user or "noreply@nexusai.com")
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
                        "subject": subject,
                        "htmlContent": html_content,
                        "textContent": plain_text
                    }
                )
                if response.status_code in (200, 201, 202):
                    logger.info(f"Invitation email sent to {to_email} via Brevo API. Response: {response.json()}")
                    return True
                else:
                    logger.error(f"Brevo API error ({response.status_code}): {response.text}")
        except Exception as e:
            logger.error(f"Failed to send email via Brevo API: {str(e)}")

    # 3. Try Resend API if configured
    if settings.resend_api_key:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {settings.resend_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "from": settings.email_from,
                        "to": [to_email],
                        "subject": subject,
                        "html": html_content,
                        "text": plain_text
                    }
                )
                if response.status_code in (200, 201):
                    logger.info(f"Invitation email sent to {to_email} via Resend. Response: {response.json()}")
                    return True
                else:
                    logger.error(f"Resend API error ({response.status_code}): {response.text}")
        except Exception as e:
            logger.error(f"Failed to send email via Resend: {str(e)}")

    logger.warning(f"No valid email provider configured. Invitation link generated: {invitation_url}")
    return False

