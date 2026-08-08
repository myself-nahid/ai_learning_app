from pathlib import Path
p = Path('app/services/email_service.py')
text = p.read_text()
old = """    message = MessageSchema(
        subject=f\"Your OTP for {purpose}\", 
        recipients=[email],
        body=html,
        subtype=MessageType.html
    )

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
    except Exception as e:
        logger.error(\"Failed to send email to %s: %s\", email, str(e), exc_info=True)
"""
new = """    message = MessageSchema(
        subject=f\"Your OTP for {purpose}\", 
        recipients=[email],
        body=html,
        subtype=MessageType.html
    )

    if settings.EMAIL_BACKEND == \"console\":
        logger.info(
            \"[EMAIL BACKEND=console] OTP for %s: %s | subject=%s\",
            email,
            otp_code,
            message.subject,
        )
        return

    fm = FastMail(conf)
    try:
        await fm.send_message(message)
    except Exception as e:
        logger.error(
            \"Failed to send email to %s using %s at %s:%s: %s\",
            email,
            settings.EMAIL_BACKEND,
            settings.MAIL_SERVER,
            settings.MAIL_PORT,
            str(e),
            exc_info=True,
        )
"""
if old not in text:
    raise RuntimeError('old block not found')
text = text.replace(old, new)
p.write_text(text)
print('patched')
