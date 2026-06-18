import logging
from abc import ABC, abstractmethod
from django.conf import settings

logger = logging.getLogger(__name__)


class EmailBackend(ABC):
    @abstractmethod
    def send(self, to_email: str, subject: str, html_content: str, from_email: str = None, from_name: str = None) -> bool:
        ...


class SendGridBackend(EmailBackend):
    def send(self, to_email: str, subject: str, html_content: str, from_email: str = None, from_name: str = None) -> bool:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail, Email, To
        message = Mail(
            from_email=Email(from_email or settings.EMAIL_FROM_ADDRESS, from_name or settings.EMAIL_FROM_NAME),
            to_emails=To(to_email),
            subject=subject,
            html_content=html_content,
        )
        try:
            sg_client = SendGridAPIClient(settings.SENDGRID_API_KEY)
            response = sg_client.send(message)
            return response.status_code == 202
        except Exception as e:
            logger.error(f"SendGrid delivery failed: {e}")
            return False


class SMTPBackend(EmailBackend):
    def send(self, to_email: str, subject: str, html_content: str, from_email: str = None, from_name: str = None) -> bool:
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = from_email or settings.EMAIL_FROM_ADDRESS
            msg["To"] = to_email
            msg.attach(MIMEText(html_content, "html"))
            with smtplib.SMTP(settings.EMAIL_SMTP_HOST, settings.EMAIL_SMTP_PORT) as server:
                if settings.EMAIL_SMTP_TLS:
                    server.starttls()
                if settings.EMAIL_SMTP_USER:
                    server.login(settings.EMAIL_SMTP_USER, settings.EMAIL_SMTP_PASSWORD)
                server.sendmail(msg["From"], [to_email], msg.as_string())
            return True
        except Exception as e:
            logger.error(f"SMTP delivery failed: {e}")
            return False


class ConsoleBackend(EmailBackend):
    def send(self, to_email: str, subject: str, html_content: str, from_email: str = None, from_name: str = None) -> bool:
        print(f"[EMAIL_CONSOLE] To: {to_email} | Subject: {subject}")
        print(f"[EMAIL_CONSOLE] From: {from_email or settings.EMAIL_FROM_ADDRESS}")
        print(f"[EMAIL_CONSOLE] Body: {html_content[:500]}...")
        return True


class LoggingBackend(EmailBackend):
    def send(self, to_email: str, subject: str, html_content: str, from_email: str = None, from_name: str = None) -> bool:
        logger.info(f"[EMAIL_LOG] To={to_email} Subject={subject}")
        return True


BACKEND_MAP = {
    "sendgrid": SendGridBackend,
    "smtp": SMTPBackend,
    "console": ConsoleBackend,
    "log": LoggingBackend,
}


def get_email_backend() -> EmailBackend:
    backend_name = getattr(settings, "EMAIL_BACKEND", "console").lower()
    backend_cls = BACKEND_MAP.get(backend_name)
    if not backend_cls:
        logger.warning(f"Unknown EMAIL_BACKEND '{backend_name}', falling back to console")
        backend_cls = ConsoleBackend
    return backend_cls()
