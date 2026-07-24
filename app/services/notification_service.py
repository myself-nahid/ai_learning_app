import firebase_admin
from firebase_admin import credentials, messaging
from app.core.config import settings

# Initialize Firebase (You will need a serviceAccountKey.json from Firebase Console)
# cred = credentials.Certificate("serviceAccountKey.json")
# firebase_admin.initialize_app(cred)

async def send_push_notification(fcm_token: str, title: str, body: str, data_payload: dict):
    """
    Sends a targeted push notification to a specific device.
    """
    if not fcm_token:
        return
        
    print(f"🔔 PUSH TO {fcm_token}: {title} | {body} | Data: {data_payload}")
    
    # --- PRODUCTION FIREBASE CODE ---
    # message = messaging.Message(
    #     notification=messaging.Notification(title=title, body=body),
    #     data=data_payload, # This hidden data tells the app which screen to open!
    #     token=fcm_token,
    # )
    # try:
    #     response = messaging.send(message)
    #     return response
    # except Exception as e:
    #     print(f"Failed to send push: {e}")