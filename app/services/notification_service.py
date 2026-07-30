import logging
import os
from typing import Optional, Dict, Any
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    FIREBASE_SDK_AVAILABLE = True
except ImportError:
    FIREBASE_SDK_AVAILABLE = False

_firebase_initialized = False
_firebase_service_key = os.getenv("FIREBASE_SERVICE_ACCOUNT_KEY", "serviceAccountKey.json")

if FIREBASE_SDK_AVAILABLE and os.path.exists(_firebase_service_key):
    try:
        cred = credentials.Certificate(_firebase_service_key)
        firebase_admin.initialize_app(cred)
        _firebase_initialized = True
        logger.info("Firebase initialized successfully.")
    except Exception:
        _firebase_initialized = False
        logger.info(
            "Firebase service account key '%s' could not be loaded. Push notifications will be logged only.",
            _firebase_service_key,
        )
else:
    if not FIREBASE_SDK_AVAILABLE:
        logger.info("Firebase Admin SDK is not installed. Push notifications will be logged only.")
    else:
        logger.info(
            "Firebase service account key '%s' not found. Push notifications will be logged only.",
            _firebase_service_key,
        )


async def send_push_notification(
    token: str,
    title: str,
    body: str,
    data_payload: Optional[Dict[str, Any]] = None,
    image_url: Optional[str] = None
):
    """
    Sends a targeted push notification with image/logo support to iOS & Android devices.
    Supports both Expo Push Tokens (e.g. ExponentPushToken[...] / _gLGGk...) and Firebase FCM tokens.
    """
    if not token:
        return None

    data_payload = data_payload or {}
    if image_url and "image_url" not in data_payload:
        data_payload["image_url"] = image_url

    logger.info("Push notification to %s: %s | %s (Image: %s)", token[:12] + "...", title, body, image_url)

    # 1. Check if token is an Expo Push Token
    is_expo_token = token.startswith("ExponentPushToken") or token.startswith("ExpoPushToken") or len(token) < 50

    if is_expo_token:
        # Format token if missing ExponentPushToken wrapper
        expo_token = token if (token.startswith("ExponentPushToken") or token.startswith("ExpoPushToken")) else f"ExponentPushToken[{token}]"
        
        expo_payload = {
            "to": expo_token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": data_payload,
            "badge": 1,
            "channelId": "default",
            "priority": "high",
        }
        if image_url:
            expo_payload["image"] = image_url
            expo_payload["attachments"] = [{"url": image_url}]

        expo_headers = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Content-Type": "application/json",
        }
        expo_access_token = os.getenv("EXPO_ACCESS_TOKEN", "bRPUPF-YVMzbSz_CTR5LO5fYdpalR5Zg9ExWAp2c")
        if expo_access_token:
            expo_headers["Authorization"] = f"Bearer {expo_access_token}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://exp.host/--/api/v2/push/send",
                    json=expo_payload,
                    headers=expo_headers,
                )
                res_data = resp.json()
                logger.info("Expo push response: %s", res_data)
                return res_data
        except Exception as e:
            logger.error("Failed to send Expo push notification: %s", str(e), exc_info=True)
            return None

    # 2. Direct FCM Token via Firebase Admin SDK
    if not _firebase_initialized:
        logger.debug("Firebase not initialized; FCM notification logged but not sent.")
        return None

    try:
        # Build Firebase rich message with image support for Android & iOS APNs
        android_config = messaging.AndroidConfig(
            notification=messaging.AndroidNotification(image=image_url) if image_url else None
        )
        apns_config = messaging.APNSConfig(
            payload=messaging.APNSPayload(aps=messaging.Aps(mutable_content=True)),
            fcm_options=messaging.FCMOptions(image=image_url) if image_url else None
        )

        message = messaging.Message(
            notification=messaging.Notification(title=title, body=body, image=image_url),
            data={k: str(v) for k, v in data_payload.items()},
            android=android_config,
            apns=apns_config,
            token=token,
        )
        response = messaging.send(message)
        logger.info("FCM push notification sent successfully: %s", response)
        return response
    except Exception as e:
        logger.error("Failed to send FCM push notification: %s", str(e), exc_info=True)
        return None