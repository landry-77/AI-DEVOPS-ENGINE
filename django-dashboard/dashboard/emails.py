import logging
from django.conf import settings
from .email_backends import get_email_backend

logger = logging.getLogger(__name__)


def _send_email(to_email: str, subject: str, html_content: str) -> bool:
    backend = get_email_backend()
    return backend.send(
        to_email=to_email,
        subject=subject,
        html_content=html_content,
    )


def send_billing_alert_email(
    user_email: str, org_name: str, provider: str,
    service: str, severity: str, current_cost: float, threshold: float,
) -> bool:
    color = "#f59e0b" if severity == "warning" else "#ef4444"
    label = "Warning" if severity == "warning" else "Critical"
    subject = f"[{label}] Cost Anomaly Detected — {provider}/{service}"
    html = f"""
    <div style="font-family: sans-serif; max-width: 600px; color: #334155; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
        <h2 style="color: {color}; margin-bottom: 4px;">{label}: Cost Anomaly Detected</h2>
        <p style="font-size: 14px; color: #64748b; margin-top: 0;">{provider.upper()} / {service}</p>
        <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;"/>
        <p>Hello team <strong>{org_name}</strong>,</p>
        <p>An automated cost anomaly check has detected unusual spending:</p>
        <div style="background-color: #f8fafc; padding: 15px; border-radius: 6px; margin: 20px 0; font-family: monospace; font-size: 13px;">
            <strong>Provider:</strong> {provider.upper()}<br/>
            <strong>Service:</strong> {service}<br/>
            <strong>Current Cost:</strong> ${current_cost:.2f}<br/>
            <strong>Threshold:</strong> ${threshold:.2f}<br/>
            <strong>Severity:</strong> {label}
        </div>
        <p style="font-size: 12px; color: #94a3b8;">
            Review your billing dashboard for details. Acknowledge this alert to dismiss it.
        </p>
    </div>
    """
    return _send_email(user_email, subject, html)


def send_instant_usage_invoice_email(user_email: str, org_name: str, project_id: str, cost: str = "$2.00") -> bool:
    subject = f"Usage Invoice: Code Remediation Run Complete [{project_id}]"
    html = f"""
    <div style="font-family: sans-serif; max-width: 600px; color: #334155; padding: 20px; border: 1px solid #e2e8f0; border-radius: 8px;">
        <h2 style="color: #0e7490; margin-bottom: 4px;">AI DevOps Ledger Update</h2>
        <p style="font-size: 14px; color: #64748b; margin-top: 0;">Autonomous Processing Completed Successfully</p>
        <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;"/>
        <p>Hello team <strong>{org_name}</strong>,</p>
        <p>Our sandboxed core system has successfully analyzed, patched, and verified your repository payload code changes.</p>
        <div style="background-color: #f8fafc; padding: 15px; border-radius: 6px; margin: 20px 0; font-family: monospace; font-size: 13px;">
            <strong>Execution Context:</strong> {project_id}<br/>
            <strong>Status Metric:</strong> Passed & Triggered PR<br/>
            <strong>Unit Transaction Cost:</strong> {cost} USD
        </div>
        <p style="font-size: 12px; color: #94a3b8;">
            This transaction has been applied to your account ledger. No further action is required.
        </p>
    </div>
    """
    return _send_email(user_email, subject, html)
