async def send_email(
    to_email: str,
    subject: str,
    html_content: str,
    plain_text: str
) -> bool:
    """
    Sends an email using configured email service provider (Direct SMTP, Mailjet, Brevo, or Resend API).
    """
    settings = get_settings()

    # 1. Try Direct SMTP (Gmail / Brevo / Custom SMTP) if configured
    if settings.smtp_host and settings.smtp_user and settings.smtp_password:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        from email.utils import parseaddr

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = settings.smtp_from or settings.smtp_user
            msg["To"] = to_email

            msg.attach(MIMEText(plain_text, "plain"))
            msg.attach(MIMEText(html_content, "html"))

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

            logger.info(f"Email sent to {to_email} via SMTP ({settings.smtp_host})")
            return True
        except Exception as e:
            logger.error(f"SMTP sending failed: {str(e)}")

    # 2. Try Mailjet REST API if configured
    if settings.mailjet_api_key and settings.mailjet_secret_key:
        try:
            from email.utils import parseaddr
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
                                "HTMLPart": html_content
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
                    logger.info(f"Email sent to {to_email} via Brevo API.")
                    return True
                else:
                    logger.error(f"Brevo API error ({response.status_code}): {response.text}")
        except Exception as e:
            logger.error(f"Failed to send email via Brevo API: {str(e)}")

    # 4. Try Resend API if configured
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
                    logger.info(f"Email sent to {to_email} via Resend.")
                    return True
                else:
                    logger.error(f"Resend API error ({response.status_code}): {response.text}")
        except Exception as e:
            logger.error(f"Failed to send email via Resend: {str(e)}")

    logger.warning(f"No valid email provider configured for recipient: {to_email}")
    return False


async def send_workspace_invitation_email(
    to_email: str,
    inviter_name: str,
    workspace_name: str,
    invitation_url: str
) -> bool:
    """
    Sends an invitation email to join a workspace.
    """
    subject = f"Invitation to join '{workspace_name}' on Nexus AI"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #090d16; color: #f8fafc; margin: 0; padding: 40px 20px; }}
        .card {{ max-width: 520px; margin: 0 auto; background-color: #0f172a; border: 1px solid #1e293b; border-radius: 20px; padding: 36px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); }}
        .badge {{ display: inline-block; background-color: rgba(99, 102, 241, 0.15); color: #818cf8; font-size: 12px; font-weight: 600; padding: 4px 12px; border-radius: 9999px; border: 1px solid rgba(99, 102, 241, 0.3); margin-bottom: 16px; }}
        .title {{ font-size: 22px; font-weight: 700; color: #ffffff; margin-bottom: 12px; line-height: 1.3; }}
        .text {{ font-size: 14px; color: #94a3b8; line-height: 1.6; margin-bottom: 24px; }}
        .button-wrapper {{ text-align: center; margin: 32px 0; }}
        .button {{ display: inline-block; background-color: #4f46e5; color: #ffffff !important; text-decoration: none; font-size: 14px; font-weight: 600; padding: 14px 28px; border-radius: 12px; box-shadow: 0 4px 14px rgba(79, 70, 229, 0.4); }}
        .footer {{ font-size: 12px; color: #64748b; margin-top: 32px; border-top: 1px solid #1e293b; padding-top: 20px; text-align: center; }}
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
        <div class="footer">Nexus AI Workspace System • Multi-Tenant RAG</div>
      </div>
    </body>
    </html>
    """

    plain_text = f"You've been invited to join '{workspace_name}' on Nexus AI by {inviter_name}.\n\nAccept your invitation here:\n{invitation_url}"

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

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #090d16; color: #f8fafc; margin: 0; padding: 40px 20px; }}
        .card {{ max-width: 520px; margin: 0 auto; background-color: #0f172a; border: 1px solid #1e293b; border-radius: 20px; padding: 36px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); }}
        .badge {{ display: inline-block; background-color: rgba(245, 158, 11, 0.15); color: #fbbf24; font-size: 12px; font-weight: 600; padding: 4px 12px; border-radius: 9999px; border: 1px solid rgba(245, 158, 11, 0.3); margin-bottom: 16px; }}
        .title {{ font-size: 20px; font-weight: 700; color: #ffffff; margin-bottom: 12px; }}
        .text {{ font-size: 14px; color: #94a3b8; line-height: 1.6; margin-bottom: 20px; }}
        .info-box {{ background-color: #1e293b; border-radius: 12px; padding: 16px; margin: 20px 0; border-left: 4px solid #f59e0b; }}
        .footer {{ font-size: 12px; color: #64748b; margin-top: 32px; border-top: 1px solid #1e293b; padding-top: 20px; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="badge">Subscription Update</div>
        <div class="title">Subscription Cancellation Confirmed</div>
        <p class="text">
          The subscription for workspace <strong style="color: #f1f5f9;">'{workspace_name}'</strong> has been set to cancel.
        </p>
        <div class="info-box">
          <p style="margin: 0; font-size: 13px; color: #cbd5e1;">
            <strong>Paid Tier Benefits Active Until:</strong> {effective_date_str}<br>
            When your billing period ends, your workspace will automatically revert to the Default Starter Plan.
          </p>
        </div>
        <p class="text" style="font-size: 13px;">
          You can upgrade or reactivate your subscription at any time directly from the Plan page.
        </p>
        <div class="footer">Nexus AI Workspace System • Multi-Tenant RAG</div>
      </div>
    </body>
    </html>
    """

    plain_text = f"Subscription for '{workspace_name}' has been canceled. Your paid tier features remain active until {effective_date_str}, after which the workspace will revert to Default Starter Plan."

    return await send_email(to_email, subject, html_content, plain_text)


async def send_subscription_expired_downgrade_email(
    to_email: str,
    workspace_name: str,
    removed_documents: list = None,
    removed_members: list = None
) -> bool:
    """
    Sends notification email when a paid subscription period ends and workspace reverts to Default Starter Plan.
    Includes list of removed excess documents and members if capacity was exceeded.
    """
    subject = f"Workspace '{workspace_name}' Reverted to Default Starter Plan"

    docs_html = ""
    docs_text = ""
    if removed_documents:
        items = "".join([f"<li style='margin-bottom: 4px;'>{doc}</li>" for doc in removed_documents])
        docs_html = f"""
        <div style="margin-top: 16px; background-color: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 12px; padding: 16px;">
          <strong style="color: #f87171; font-size: 13px;">Removed Documents (Exceeded 50 Pages Starter Limit):</strong>
          <ul style="color: #cbd5e1; font-size: 13px; margin: 8px 0 0 0; padding-left: 20px;">{items}</ul>
        </div>
        """
        docs_text = f"\n\nRemoved Documents:\n" + "\n".join([f"- {doc}" for doc in removed_documents])

    members_html = ""
    members_text = ""
    if removed_members:
        items = "".join([f"<li style='margin-bottom: 4px;'>{m}</li>" for m in removed_members])
        members_html = f"""
        <div style="margin-top: 16px; background-color: rgba(239, 68, 68, 0.1); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 12px; padding: 16px;">
          <strong style="color: #f87171; font-size: 13px;">Removed Member Seats (Exceeded 5 Seats Starter Limit):</strong>
          <ul style="color: #cbd5e1; font-size: 13px; margin: 8px 0 0 0; padding-left: 20px;">{items}</ul>
        </div>
        """
        members_text = f"\n\nRemoved Member Seats:\n" + "\n".join([f"- {m}" for m in removed_members])

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #090d16; color: #f8fafc; margin: 0; padding: 40px 20px; }}
        .card {{ max-width: 520px; margin: 0 auto; background-color: #0f172a; border: 1px solid #1e293b; border-radius: 20px; padding: 36px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); }}
        .badge {{ display: inline-block; background-color: rgba(99, 102, 241, 0.15); color: #818cf8; font-size: 12px; font-weight: 600; padding: 4px 12px; border-radius: 9999px; border: 1px solid rgba(99, 102, 241, 0.3); margin-bottom: 16px; }}
        .title {{ font-size: 20px; font-weight: 700; color: #ffffff; margin-bottom: 12px; }}
        .text {{ font-size: 14px; color: #94a3b8; line-height: 1.6; margin-bottom: 20px; }}
        .footer {{ font-size: 12px; color: #64748b; margin-top: 32px; border-top: 1px solid #1e293b; padding-top: 20px; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="badge">Workspace Plan Reverted</div>
        <div class="title">Default Starter Plan Activated</div>
        <p class="text">
          Your workspace <strong style="color: #f1f5f9;">'{workspace_name}'</strong> has completed its paid subscription period and has automatically reverted to the <strong style="color: #f1f5f9;">Default Free Starter Plan</strong> (50,000 daily tokens, 50 max pages capacity, 5 member seats).
        </p>
        {docs_html}
        {members_html}
        <p class="text" style="font-size: 13px; margin-top: 20px;">
          You can upgrade your workspace back to Pro or Enterprise at any time to restore higher quotas and team limits.
        </p>
        <div class="footer">Nexus AI Workspace System • Multi-Tenant RAG</div>
      </div>
    </body>
    </html>
    """

    plain_text = f"Workspace '{workspace_name}' has been reverted to Default Starter Plan.{docs_text}{members_text}"

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
    Sends a monthly payment receipt / invoice email to the workspace owner upon successful recurring payment or subscription activation.
    """
    subject = f"Payment Receipt & Invoice for '{workspace_name}' - {plan_name}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #090d16; color: #f8fafc; margin: 0; padding: 40px 20px; }}
        .card {{ max-width: 520px; margin: 0 auto; background-color: #0f172a; border: 1px solid #1e293b; border-radius: 20px; padding: 36px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); }}
        .badge {{ display: inline-block; background-color: rgba(16, 185, 129, 0.15); color: #34d399; font-size: 12px; font-weight: 600; padding: 4px 12px; border-radius: 9999px; border: 1px solid rgba(16, 185, 129, 0.3); margin-bottom: 16px; }}
        .title {{ font-size: 20px; font-weight: 700; color: #ffffff; margin-bottom: 12px; }}
        .text {{ font-size: 14px; color: #94a3b8; line-height: 1.6; margin-bottom: 20px; }}
        .invoice-box {{ background-color: #1e293b; border-radius: 12px; padding: 20px; margin: 20px 0; border: 1px solid #334155; }}
        .row {{ display: flex; justify-content: space-between; margin-bottom: 10px; font-size: 13px; color: #cbd5e1; }}
        .row-total {{ display: flex; justify-content: space-between; padding-top: 10px; border-top: 1px solid #334155; font-size: 15px; font-weight: 700; color: #ffffff; }}
        .footer {{ font-size: 12px; color: #64748b; margin-top: 32px; border-top: 1px solid #1e293b; padding-top: 20px; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="badge">Payment Invoice & Receipt</div>
        <div class="title">Subscription Renewal Successful</div>
        <p class="text">
          Thank you for continuing your subscription! Your monthly payment for workspace <strong style="color: #f1f5f9;">'{workspace_name}'</strong> has been processed successfully.
        </p>
        <div class="invoice-box">
          <div class="row"><span>Workspace:</span><strong>{workspace_name}</strong></div>
          <div class="row"><span>Subscription Plan:</span><strong>{plan_name}</strong></div>
          <div class="row"><span>Payment Date:</span><span>{payment_date_str}</span></div>
          <div class="row"><span>Next Billing Date:</span><span>{next_billing_date_str}</span></div>
          <div class="row-total"><span>Amount Paid:</span><span style="color: #34d399;">{amount_str}</span></div>
        </div>
        <p class="text" style="font-size: 13px;">
          Your workspace quotas and capabilities remain fully active. You can manage your subscription settings anytime from the Plan page.
        </p>
        <div class="footer">Nexus AI Workspace System • Multi-Tenant RAG</div>
      </div>
    </body>
    </html>
    """

    plain_text = f"Payment Invoice for '{workspace_name}' - {plan_name}\nAmount Paid: {amount_str}\nPayment Date: {payment_date_str}\nNext Billing Date: {next_billing_date_str}"

    return await send_email(to_email, subject, html_content, plain_text)



