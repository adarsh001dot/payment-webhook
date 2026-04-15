"""
===========================================
🌐 PAYMENT WEBHOOK SERVER - DARKXALPHA.IN
===========================================
Developer: @VIP_X_OFFICIAL
Purpose: Handle payment callbacks and auto-add points
===========================================
"""

from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime
from pytz import timezone
import requests
import logging

# ==================== CONFIGURATION ====================
MONGODB_URI = "mongodb+srv://nikilsaxena843_db_user:3gF2wyT4IjsFt0cY@vipbot.puv6gfk.mongodb.net/?appName=vipbot"
BOT_TOKEN = "8612834168:AAFT1VX35aEpyEOMoszHf2ymrr2R4iP3gvQ"
OWNER_ID = 7459756974
OWNER_USERNAME = "@VIP_X_OFFICIAL"
IST = timezone('Asia/Kolkata')

# Flask App
app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== DATABASE CONNECTION ====================
try:
    client = MongoClient(MONGODB_URI)
    db = client['vip_bot']
    users_col = db['users']
    transactions_col = db['transactions']
    orders_col = db['orders']
    logger.info("✅ Database Connected Successfully!")
except Exception as e:
    logger.error(f"❌ Database Error: {e}")
    exit(1)


# ==================== HELPER FUNCTIONS ====================
def get_ist():
    """Get current IST time"""
    return datetime.now(IST)


def format_ist(dt):
    """Format IST datetime"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone('UTC')).astimezone(IST)
    return dt.strftime("%d-%m-%Y %I:%M:%S %p")


def format_number(num):
    """Format number with commas"""
    return f"{num:,}"


def add_points(user_id, points, reason, admin_id=None):
    """Add points to user"""
    user = users_col.find_one({'user_id': user_id})
    if not user:
        logger.error(f"User {user_id} not found!")
        return False

    new_balance = user['points'] + points
    users_col.update_one(
        {'user_id': user_id},
        {'$set': {'points': new_balance}}
    )

    # Log transaction
    transactions_col.insert_one({
        'user_id': user_id,
        'type': 'credit',
        'amount': points,
        'reason': reason,
        'admin_id': admin_id,
        'balance': new_balance,
        'timestamp': get_ist()
    })

    logger.info(f"✅ Added {points} points to user {user_id}. New balance: {new_balance}")
    return new_balance


def send_telegram_message(chat_id, text):
    """Send message via Telegram Bot"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': text,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return None


def check_order_status_from_api(order_id, user_token):
    """Check order status from darkxalpha API"""
    try:
        url = "https://darkxalpha.in/api/check-order-status"
        payload = {
            'user_token': user_token,
            'order_id': order_id
        }
        response = requests.post(url, data=payload, timeout=15)
        
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"API Error: {e}")
        return None


# ==================== WEBHOOK ROUTES ====================
@app.route('/webhook', methods=['POST'])
def payment_webhook():
    """
    Handle payment callback from darkxalpha.in
    Expected form data:
    - status: SUCCESS/FAILED/PENDING
    - order_id: Order ID
    - amount: Amount paid
    - utr: Transaction reference (optional)
    - remark1: User ID (we'll store user_id here)
    """
    try:
        # Get form data
        data = request.form
        logger.info(f"📥 Webhook Received: {dict(data)}")

        status = data.get('status', '').upper()
        order_id = data.get('order_id', '')
        amount = data.get('amount', '0')
        utr = data.get('utr', '')
        remark1 = data.get('remark1', '')  # We'll store user_id in remark1

        if not order_id:
            logger.error("❌ No order_id in webhook data")
            return jsonify({"error": "Missing order_id"}), 400

        # Find order in database
        order = orders_col.find_one({'order_id': order_id})
        
        if not order:
            logger.error(f"❌ Order {order_id} not found in database")
            return jsonify({"error": "Order not found"}), 404

        user_id = order.get('user_id')
        
        # If user_id not in order, try to get from remark1
        if not user_id and remark1:
            try:
                user_id = int(remark1)
            except:
                pass

        if not user_id:
            logger.error(f"❌ No user_id found for order {order_id}")
            return jsonify({"error": "User ID not found"}), 400

        # Process based on status
        if status == "SUCCESS" or status == "COMPLETED":
            # Check if already processed
            if order.get('status') == 'completed':
                logger.info(f"ℹ️ Order {order_id} already processed")
                return "OK", 200

            # Update order status
            orders_col.update_one(
                {'order_id': order_id},
                {'$set': {
                    'status': 'completed',
                    'payment_status': status,
                    'utr': utr,
                    'webhook_received': get_ist(),
                    'completed_at': get_ist()
                }}
            )

            # Add points to user
            points = order.get('points', 0)
            new_balance = add_points(
                user_id, 
                points, 
                f"Payment completed for order {order_id}"
            )

            # Get user language preference
            user = users_col.find_one({'user_id': user_id})
            lang = user.get('language', 'en') if user else 'en'

            # Prepare success message
            if lang == 'hi':
                success_msg = f"""
✅ <b>पेमेंट सफल!</b>

🆔 ऑर्डर ID: <code>{order_id}</code>
💰 पॉइंट्स जोड़े गए: <b>{points}</b>
💎 नया बैलेंस: <b>{format_number(new_balance)}</b>
📅 समय: {format_ist(get_ist())}

🎉 आपके पॉइंट्स आपके अकाउंट में जोड़ दिए गए हैं!
आप अब सर्च सेवा का उपयोग कर सकते हैं।

👑 एडमिन: {OWNER_USERNAME}
            """
            else:
                success_msg = f"""
✅ <b>Payment Successful!</b>

🆔 Order ID: <code>{order_id}</code>
💰 Points Added: <b>{points}</b>
💎 New Balance: <b>{format_number(new_balance)}</b>
📅 Time: {format_ist(get_ist())}

🎉 Your points have been added to your account!
You can now use the search service.

👑 Admin: {OWNER_USERNAME}
            """

            # Send success message to user
            send_telegram_message(user_id, success_msg)

            # Notify admin
            admin_msg = f"""
💰 <b>Payment Received!</b>

🆔 Order: <code>{order_id}</code>
👤 User: <code>{user_id}</code>
💰 Amount: ₹{amount}
📦 Points: {points}
🔖 UTR: {utr}
🕐 Time: {format_ist(get_ist())}

✅ Points automatically added!
            """
            send_telegram_message(OWNER_ID, admin_msg)

            logger.info(f"✅ Payment processed successfully for order {order_id}")
            return "OK", 200

        elif status == "FAILED" or status == "ERROR":
            # Update order as failed
            orders_col.update_one(
                {'order_id': order_id},
                {'$set': {
                    'status': 'failed',
                    'payment_status': status,
                    'webhook_received': get_ist(),
                    'failed_at': get_ist()
                }}
            )

            # Notify user about failure
            user = users_col.find_one({'user_id': user_id})
            lang = user.get('language', 'en') if user else 'en'

            if lang == 'hi':
                fail_msg = f"""
❌ <b>पेमेंट विफल!</b>

🆔 ऑर्डर ID: <code>{order_id}</code>
⚠️ स्थिति: विफल

कृपया पुनः प्रयास करें या एडमिन से संपर्क करें।
👑 एडमिन: {OWNER_USERNAME}
            """
            else:
                fail_msg = f"""
❌ <b>Payment Failed!</b>

🆔 Order ID: <code>{order_id}</code>
⚠️ Status: Failed

Please try again or contact admin.
👑 Admin: {OWNER_USERNAME}
            """

            send_telegram_message(user_id, fail_msg)

            logger.info(f"❌ Payment failed for order {order_id}")
            return "OK", 200

        elif status == "PENDING":
            # Update as pending
            orders_col.update_one(
                {'order_id': order_id},
                {'$set': {
                    'payment_status': 'pending',
                    'webhook_received': get_ist()
                }}
            )
            logger.info(f"⏳ Payment pending for order {order_id}")
            return "OK", 200

        else:
            logger.warning(f"⚠️ Unknown status: {status} for order {order_id}")
            return jsonify({"error": f"Unknown status: {status}"}), 400

    except Exception as e:
        logger.error(f"❌ Webhook Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/webhook', methods=['GET'])
def webhook_get():
    """Handle GET requests (for testing)"""
    return jsonify({
        "status": "active",
        "message": "Payment webhook is running",
        "time": format_ist(get_ist())
    }), 200


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "database": "connected",
        "time": format_ist(get_ist())
    }), 200


# ==================== MAIN ====================
if __name__ == '__main__':
    print("=" * 50)
    print("🌐 PAYMENT WEBHOOK SERVER STARTED")
    print("=" * 50)
    print(f"🕐 Time: {format_ist(get_ist())} IST")
    print(f"📡 Webhook URL: http://your-server:5000/webhook")
    print(f"💓 Health Check: http://your-server:5000/health")
    print(f"👑 Admin: {OWNER_USERNAME}")
    print("=" * 50)
    
    # Run Flask app
    # For production, use a proper WSGI server like gunicorn
    app.run(host='0.0.0.0', port=5000, debug=False)