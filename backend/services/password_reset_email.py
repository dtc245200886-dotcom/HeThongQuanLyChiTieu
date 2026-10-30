"""Send password reset links using the configured SMTP server."""
from email.message import EmailMessage
from email.utils import parseaddr
from html import escape
import math
import os
import smtplib
from email_validator import EmailNotValidError, validate_email
from urllib.parse import urlparse


class PasswordResetEmailConfigurationError(RuntimeError):
    pass


def _settings() -> dict:
    required = ("SMTP_HOST", "SMTP_FROM_EMAIL", "APP_BASE_URL")
    missing = [key for key in required if not os.getenv(key, "").strip()]
    if missing:
        raise PasswordResetEmailConfigurationError(
            "Thiếu cấu hình email đặt lại mật khẩu: " + ", ".join(missing)
        )

    base_url = os.getenv("APP_BASE_URL", "").strip().rstrip("/")
    parsed_base_url = urlparse(base_url)
    if (
        parsed_base_url.scheme not in ("http", "https")
        or not parsed_base_url.hostname
        or parsed_base_url.username
        or parsed_base_url.password
        or parsed_base_url.query
        or parsed_base_url.fragment
    ):
        raise PasswordResetEmailConfigurationError("APP_BASE_URL phải là URL http hoặc https hợp lệ.")
    try:
        parsed_base_url.port
    except ValueError as exc:
        raise PasswordResetEmailConfigurationError("APP_BASE_URL có cổng không hợp lệ.") from exc
    is_production = os.getenv("APP_ENV", "development").strip().lower() in ("prod", "production")
    if is_production and parsed_base_url.scheme != "https":
        raise PasswordResetEmailConfigurationError("APP_BASE_URL phải dùng HTTPS trong môi trường production.")

    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise PasswordResetEmailConfigurationError(
            "SMTP_USERNAME và SMTP_PASSWORD phải được cấu hình cùng nhau."
        )

    def read_bool(name: str, default: str) -> bool:
        value = os.getenv(name, default).strip().lower()
        if value in ("1", "true", "yes"):
            return True
        if value in ("0", "false", "no"):
            return False
        raise PasswordResetEmailConfigurationError(f"{name} phải là true hoặc false.")

    use_tls = read_bool("SMTP_USE_TLS", "true")
    use_ssl = read_bool("SMTP_USE_SSL", "false")
    if use_tls and use_ssl:
        raise PasswordResetEmailConfigurationError(
            "Chỉ bật một trong hai cấu hình SMTP_USE_TLS hoặc SMTP_USE_SSL."
        )
    if username and not (use_tls or use_ssl):
        raise PasswordResetEmailConfigurationError(
            "SMTP cần bật TLS hoặc SSL khi sử dụng thông tin đăng nhập."
        )

    try:
        port = int(os.getenv("SMTP_PORT", "587"))
        timeout = float(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))
    except ValueError as exc:
        raise PasswordResetEmailConfigurationError(
            "SMTP_PORT và SMTP_TIMEOUT_SECONDS phải là số hợp lệ."
        ) from exc
    if not 1 <= port <= 65535:
        raise PasswordResetEmailConfigurationError("SMTP_PORT phải nằm trong khoảng 1 đến 65535.")
    if not math.isfinite(timeout) or timeout <= 0:
        raise PasswordResetEmailConfigurationError("SMTP_TIMEOUT_SECONDS phải là số dương hữu hạn.")

    from_email = os.getenv("SMTP_FROM_EMAIL", "").strip()
    parsed_sender = parseaddr(from_email)[1]
    if not parsed_sender or "\r" in from_email or "\n" in from_email:
        raise PasswordResetEmailConfigurationError("SMTP_FROM_EMAIL phải là địa chỉ email hợp lệ.")
    try:
        validate_email(parsed_sender, check_deliverability=False)
    except EmailNotValidError as exc:
        raise PasswordResetEmailConfigurationError(
            "SMTP_FROM_EMAIL phải là địa chỉ email hợp lệ."
        ) from exc

    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": port,
        "username": username,
        "password": password,
        "from_email": from_email,
        "use_tls": use_tls,
        "use_ssl": use_ssl,
        "timeout": timeout,
    }


def ensure_password_reset_email_configured() -> None:
    _settings()


def send_password_reset_email(to_email: str, reset_url: str) -> None:
    settings = _settings()
    message = EmailMessage()
    message["Subject"] = "Đặt lại mật khẩu Chi tiêu AI"
    message["From"] = settings["from_email"]
    message["To"] = to_email
    message.set_content(
        "Bạn đã yêu cầu đặt lại mật khẩu Chi tiêu AI.\n"
        "Mở liên kết sau trong vòng 15 phút để tiếp tục:\n"
        f"{reset_url}\n\n"
        "Nếu bạn không yêu cầu thao tác này, hãy bỏ qua email."
    )
    message.add_alternative(
        "<p>Bạn đã yêu cầu đặt lại mật khẩu Chi tiêu AI.</p>"
        f'<p><a href="{escape(reset_url, quote=True)}">Đặt lại mật khẩu</a></p>'
        "<p>Liên kết có hiệu lực trong 15 phút. Nếu bạn không yêu cầu thao tác này, "
        "hãy bỏ qua email.</p>",
        subtype="html",
    )

    smtp_class = smtplib.SMTP_SSL if settings["use_ssl"] else smtplib.SMTP
    with smtp_class(
        settings["host"],
        settings["port"],
        timeout=settings["timeout"],
    ) as smtp:
        if settings["use_tls"]:
            smtp.starttls()
        if settings["username"]:
            smtp.login(settings["username"], settings["password"])
        refused = smtp.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
