"""
===========================================
🌐 PAYMENT WEBHOOK SERVER - DARKXALPHA.IN (FIXED - NO DOUBLE POINTS)
===========================================
Developer: @VIP_X_OFFICIAL
Version: 3.0 (FIXED - Idempotency Check + Auto Delete Trigger)
===========================================
"""

from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime
from pytz import timezone
import requests
import logging
import hashlib
import threading

# ==================== CONFIGURATION ====================
MONGODB_URI = "mongodb+srv://nikilsaxena843_db_user:3gF2wyT4IjsFt0cY@vipbot.puv6gfk.mongodb.net/?appName=vipbot"
BOT_TOKEN = "8612834168:AAFT1VX35aEpyEOMoszHf2ymrr2R4iP3gvQ"
OWNER_ID = 7459756974
OWNER_USERNAME = "@VIP_X_OFFICIAL"
IST = timezone('Asia/Kolkata')

# DarkXAlpha Payment API Configuration
PAYMENT_CHECK_URL = "https://darkxalpha.in/api/check-order-status"
PAYMENT_TOKEN = "281b83999638fcca7c5e753195cd5931"

# Flask App
app = Flask(__name__)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Store processed webhook IDs to prevent duplicates
processed_webhooks = {}

# ==================== DATABASE CONNECTION ====================
try:
    client = MongoClient(MONGODB_URI)
    db = client['vip_bot']
    users_col = db['users']
    transactions_col = db['transactions']
    orders_col = db['orders']
    
    # Create index for webhook_id to prevent duplicates
    try:
        orders_col.create_index('webhook_id', unique=True, sparse=True)
    except:
        pass
    
    logger.info("✅ Database Connected Successfully!")
except Exception as e:
    logger.error(f"❌ Database Error: {e}")
    exit(1)


# ==================== HELPER FUNCTIONS ====================
def get_ist():
    return datetime.now(IST)


def format_ist(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone('UTC')).astimezone(IST)
    return dt.strftime("%d-%m-%Y %I:%M:%S %p")


def format_number(num):
    return f"{num:,}"


def generate_webhook_id(order_id, timestamp, amount):
    unique_string = f"{order_id}_{timestamp}_{amount}"
    return hashlib.md5(unique_string.encode()).hexdigest()


def add_points(user_id, points, reason, admin_id=None):
    try:
        user = users_col.find_one({'user_id': user_id})
        if not user:
            logger.error(f"User {user_id} not found!")
            return False

        new_balance = user['points'] + points
        users_col.update_one(
            {'user_id': user_id},
            {'$set': {'points': new_balance}}
        )

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
    except Exception as e:
        logger.error(f"Error adding points: {e}")
        return False


def send_telegram_message(chat_id, text):
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


def delete_telegram_message(chat_id, message_id):
    """Delete a specific message"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteMessage"
        payload = {
            'chat_id': chat_id,
            'message_id': message_id
        }
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"✅ Deleted message {message_id} for user {chat_id}")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")
        return None


def edit_telegram_message(chat_id, message_id, new_text, reply_markup=None):
    """Edit a message to show payment completed"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/editMessageText"
        payload = {
            'chat_id': chat_id,
            'message_id': message_id,
            'text': new_text,
            'parse_mode': 'HTML'
        }
        if reply_markup:
            payload['reply_markup'] = reply_markup
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Failed to edit message: {e}")
        return None


# ==================== WEBHOOK ROUTES ====================
@app.route('/webhook', methods=['POST'])
def payment_webhook():
    try:
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        logger.info(f"📥 Webhook Received: {data}")
        
        order_id = data.get('order_id') or data.get('orderId') or data.get('txnid')
        status = str(data.get('status', '')).upper()
        amount = data.get('amount', '0')
        utr = data.get('utr') or data.get('txnid') or data.get('reference_id', '')
        timestamp = data.get('timestamp', get_ist().strftime('%Y%m%d%H%M%S'))
        
        if not order_id:
            logger.error("❌ No order_id in webhook data")
            return jsonify({"error": "Missing order_id"}), 400
        
        webhook_id = generate_webhook_id(order_id, timestamp, amount)
        
        # Check for duplicate
        if webhook_id in processed_webhooks:
            logger.warning(f"⚠️ Duplicate webhook detected! Already processed")
            return "OK - Already Processed", 200
        
        existing_order = orders_col.find_one({'webhook_id': webhook_id})
        if existing_order:
            logger.warning(f"⚠️ Duplicate webhook found in DB!")
            return "OK - Already Processed", 200
        
        order = orders_col.find_one({'order_id': order_id})
        if not order:
            order = orders_col.find_one({'api_order_id': order_id})
        
        if not order:
            logger.error(f"❌ Order {order_id} not found in database")
            return jsonify({"error": "Order not found"}), 404
        
        user_id = order.get('user_id')
        
        if order.get('status') == 'completed':
            logger.warning(f"⚠️ Order {order_id} already marked as completed!")
            return "OK - Already Completed", 200
        
        if status == "SUCCESS" or status == "COMPLETED":
            points = order.get('points', 0)
            
            # Check if points already added
            existing_transaction = transactions_col.find_one({
                'user_id': user_id,
                'reason': {'$regex': f"Payment completed for order {order_id}"}
            })
            
            if existing_transaction:
                logger.warning(f"⚠️ Points already added for order {order_id}!")
                return "OK - Already Added", 200
            
            # Add points
            new_balance = add_points(user_id, points, f"Payment completed for order {order_id}")
            
            if new_balance:
                # Update order
                orders_col.update_one(
                    {'_id': order['_id']},
                    {'$set': {
                        'status': 'completed',
                        'payment_status': status,
                        'utr': utr,
                        'webhook_received': get_ist(),
                        'completed_at': get_ist(),
                        'webhook_id': webhook_id,
                        'webhook_data': data
                    }}
                )
                
                processed_webhooks[webhook_id] = get_ist().strftime("%Y-%m-%d %H:%M:%S")
                
                # Clean old cache
                if len(processed_webhooks) > 100:
                    keys_to_remove = list(processed_webhooks.keys())[:50]
                    for key in keys_to_remove:
                        del processed_webhooks[key]
                
                user = users_col.find_one({'user_id': user_id})
                lang = user.get('language', 'en') if user else 'en'
                
                if lang == 'hi':
                    success_msg = f"""
✅ <b>पेमेंट सफल!</b>

🆔 ऑर्डर ID: <code>{order_id}</code>
💰 पॉइंट्स जोड़े गए: <b>{points}</b>
💎 नया बैलेंस: <b>{format_number(new_balance)}</b>
📅 समय: {format_ist(get_ist())}

🎉 आपके पॉइंट्स आपके अकाउंट में जोड़ दिए गए हैं!

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

👑 Admin: {OWNER_USERNAME}
                    """
                
                # Send success message
                send_telegram_message(user_id, success_msg)
                
                # TRY TO DELETE THE OLD PAYMENT LINK MESSAGE
                payment_msg_id = order.get('payment_message_id')
                if payment_msg_id:
                    delete_telegram_message(user_id, payment_msg_id)
                
                # Notify admin
                admin_msg = f"""
💰 <b>Payment Auto-Approved!</b>

🆔 Order: <code>{order_id}</code>
👤 User: <code>{user_id}</code>
💰 Amount: ₹{amount}
📦 Points: {points}
🕐 Time: {format_ist(get_ist())}

✅ Points added! Payment message deleted.
                """
                send_telegram_message(OWNER_ID, admin_msg)
                
                logger.info(f"✅ Payment processed successfully for order {order_id}")
                return "OK", 200
            else:
                logger.error(f"❌ Failed to add points for order {order_id}")
                return jsonify({"error": "Failed to add points"}), 500
                
        elif status == "FAILED" or status == "ERROR":
            orders_col.update_one(
                {'_id': order['_id']},
                {'$set': {
                    'status': 'failed',
                    'payment_status': status,
                    'webhook_received': get_ist(),
                    'failed_at': get_ist(),
                    'webhook_id': webhook_id,
                    'webhook_data': data
                }}
            )
            
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
            
        else:
            logger.info(f"⏳ Payment status: {status} for order {order_id}")
            return "OK", 200
            
    except Exception as e:
        logger.error(f"❌ Webhook Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/webhook', methods=['GET'])
def webhook_get():
    return jsonify({
        "status": "active",
        "message": "Payment webhook is running (FIXED - Auto Delete + No Double Points)",
        "time": format_ist(get_ist()),
        "processed_count": len(processed_webhooks)
    }), 200


@app.route('/health', methods=['GET'])
def health_check():
    try:
        users_col.count_documents({})
        db_status = "connected"
    except:
        db_status = "disconnected"
    
    return jsonify({
        "status": "healthy",
        "database": db_status,
        "time": format_ist(get_ist()),
        "version": "3.0 - Fixed"
    }), 200


if __name__ == '__main__':
    print("=" * 50)
    print("🌐 PAYMENT WEBHOOK SERVER STARTED (FIXED)")
    print("=" * 50)
    print(f"🕐 Time: {format_ist(get_ist())} IST")
    print(f"📡 Webhook URL: http://your-server:5000/webhook")
    print(f"💓 Health Check: http://your-server:5000/health")
    print(f"👑 Admin: {OWNER_USERNAME}")
    print("=" * 50)
    print("✅ FIXES APPLIED:")
    print("   ✓ Double Webhook Prevention")
    print("   ✓ Auto Delete Payment Message Trigger")
    print("   ✓ Idempotency Check")
    print("=" * 50)
    
    app.run(host='0.0.0.0', port=5000, debug=False)