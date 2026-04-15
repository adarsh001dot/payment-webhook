"""
===========================================
🌐 PAYMENT WEBHOOK SERVER - DARKXALPHA.IN
===========================================
Developer: @VIP_X_OFFICIAL
Purpose: Handle payment callbacks and auto-add points
Version: 2.0 (Fully Integrated)
===========================================
"""

from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime
from pytz import timezone
import requests
import logging
import json

# ==================== CONFIGURATION ====================
MONGODB_URI = "mongodb+srv://nikilsaxena843_db_user:3gF2wyT4IjsFt0cY@vipbot.puv6gfk.mongodb.net/?appName=vipbot"
BOT_TOKEN = "8612834168:AAFT1VX35aEpyEOMoszHf2ymrr2R4iP3gvQ"
OWNER_ID = 7459756974
OWNER_USERNAME = "@VIP_X_OFFICIAL"
IST = timezone('Asia/Kolkata')

# DarkXAlpha Payment API Configuration
PAYMENT_CHECK_URL = "https://darkxalpha.in/api/check-order-status"
PAYMENT_TOKEN = "897cdfe5264aafaca31d5612e7a521c2"

# Flask App
app = Flask(__name__)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
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
    except Exception as e:
        logger.error(f"Error adding points: {e}")
        return False


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
        if response.status_code == 200:
            logger.info(f"Message sent to {chat_id}")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return None


def check_order_status_from_api(order_id):
    """Check order status from darkxalpha API"""
    try:
        url = PAYMENT_CHECK_URL
        payload = {
            'user_token': PAYMENT_TOKEN,
            'order_id': order_id
        }
        response = requests.post(url, data=payload, timeout=15)
        
        if response.status_code == 200:
            return response.json()
        return None
    except Exception as e:
        logger.error(f"API Error: {e}")
        return None


def verify_and_add_points(order_id):
    """Verify order and add points to user"""
    try:
        # Find order in database
        order = orders_col.find_one({'order_id': order_id})
        
        if not order:
            # Try to find by api_order_id
            order = orders_col.find_one({'api_order_id': order_id})
        
        if not order:
            logger.error(f"❌ Order {order_id} not found in database")
            return False
        
        # Check if already processed
        if order.get('status') == 'completed':
            logger.info(f"ℹ️ Order {order_id} already processed")
            return True
        
        # Check status from API
        status_data = check_order_status_from_api(order_id)
        
        if status_data and status_data.get('status') == 'COMPLETED':
            user_id = order.get('user_id')
            points = order.get('points', 0)
            
            # Add points to user
            new_balance = add_points(
                user_id, 
                points, 
                f"Payment completed for order {order_id}"
            )
            
            if new_balance:
                # Update order status
                orders_col.update_one(
                    {'_id': order['_id']},
                    {'$set': {
                        'status': 'completed',
                        'payment_status': 'COMPLETED',
                        'completed_at': get_ist(),
                        'utr': status_data.get('result', {}).get('utr'),
                        'webhook_verified': True
                    }}
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
💰 <b>Payment Auto-Approved!</b>

🆔 Order: <code>{order_id}</code>
👤 User: <code>{user_id}</code>
💰 Amount: ₹{order.get('amount')}
📦 Points: {points}
🕐 Time: {format_ist(get_ist())}

✅ Points automatically added via webhook!
                """
                send_telegram_message(OWNER_ID, admin_msg)
                
                logger.info(f"✅ Payment processed successfully for order {order_id}")
                return True
        else:
            logger.info(f"⏳ Payment not completed for order {order_id}. Status: {status_data.get('status') if status_data else 'UNKNOWN'}")
            return False
            
    except Exception as e:
        logger.error(f"Error verifying order: {e}")
        return False


# ==================== WEBHOOK ROUTES ====================
@app.route('/webhook', methods=['POST'])
def payment_webhook():
    """
    Handle payment callback from darkxalpha.in
    Expected data formats:
    1. JSON: {"status": "COMPLETED", "order_id": "xxx", "amount": "100", ...}
    2. Form data: status=COMPLETED&order_id=xxx&amount=100
    """
    try:
        # Get data from request
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        logger.info(f"📥 Webhook Received: {json.dumps(data, indent=2)}")
        
        # Extract order_id and status
        order_id = data.get('order_id') or data.get('orderId') or data.get('txnid')
        status = str(data.get('status', '')).upper()
        amount = data.get('amount', '0')
        utr = data.get('utr') or data.get('txnid') or data.get('reference_id', '')
        remark1 = data.get('remark1', '')
        
        if not order_id:
            logger.error("❌ No order_id in webhook data")
            return jsonify({"error": "Missing order_id"}), 400
        
        # Find order in database
        order = orders_col.find_one({'order_id': order_id})
        if not order:
            order = orders_col.find_one({'api_order_id': order_id})
        
        if not order:
            logger.error(f"❌ Order {order_id} not found in database")
            return jsonify({"error": "Order not found"}), 404
        
        user_id = order.get('user_id')
        
        # Process based on status
        if status == "SUCCESS" or status == "COMPLETED":
            # Check if already processed
            if order.get('status') == 'completed':
                logger.info(f"ℹ️ Order {order_id} already processed")
                return "OK", 200
            
            # Add points to user
            points = order.get('points', 0)
            new_balance = add_points(
                user_id, 
                points, 
                f"Payment completed for order {order_id}"
            )
            
            if new_balance:
                # Update order status
                orders_col.update_one(
                    {'_id': order['_id']},
                    {'$set': {
                        'status': 'completed',
                        'payment_status': status,
                        'utr': utr,
                        'webhook_received': get_ist(),
                        'completed_at': get_ist(),
                        'webhook_data': data
                    }}
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
💰 <b>Payment Received via Webhook!</b>

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
            else:
                logger.error(f"❌ Failed to add points for order {order_id}")
                return jsonify({"error": "Failed to add points"}), 500
                
        elif status == "FAILED" or status == "ERROR":
            # Update order as failed
            orders_col.update_one(
                {'_id': order['_id']},
                {'$set': {
                    'status': 'failed',
                    'payment_status': status,
                    'webhook_received': get_ist(),
                    'failed_at': get_ist(),
                    'webhook_data': data
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
            
            # Notify admin
            admin_msg = f"""
❌ <b>Payment Failed!</b>

🆔 Order: <code>{order_id}</code>
👤 User: <code>{user_id}</code>
💰 Amount: ₹{amount}
🕐 Time: {format_ist(get_ist())}
                """
            send_telegram_message(OWNER_ID, admin_msg)
            
            logger.info(f"❌ Payment failed for order {order_id}")
            return "OK", 200
            
        elif status == "PENDING":
            # Update as pending
            orders_col.update_one(
                {'_id': order['_id']},
                {'$set': {
                    'payment_status': 'pending',
                    'webhook_received': get_ist(),
                    'webhook_data': data
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


@app.route('/webhook/verify/<order_id>', methods=['GET'])
def verify_order(order_id):
    """Manually verify order status"""
    try:
        result = verify_and_add_points(order_id)
        if result:
            return jsonify({
                "status": "success",
                "message": f"Order {order_id} verified and points added"
            }), 200
        else:
            return jsonify({
                "status": "pending",
                "message": f"Order {order_id} not completed yet"
            }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/webhook', methods=['GET'])
def webhook_get():
    """Handle GET requests (for testing)"""
    return jsonify({
        "status": "active",
        "message": "Payment webhook is running",
        "time": format_ist(get_ist()),
        "endpoints": {
            "webhook": "POST - Receive payment callbacks",
            "webhook/verify/<order_id>": "GET - Verify order status manually",
            "health": "GET - Health check"
        }
    }), 200


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        users_col.count_documents({})
        db_status = "connected"
    except:
        db_status = "disconnected"
    
    return jsonify({
        "status": "healthy",
        "database": db_status,
        "time": format_ist(get_ist()),
        "version": "2.0"
    }), 200


@app.route('/webhook/stats', methods=['GET'])
def webhook_stats():
    """Get webhook statistics"""
    try:
        total_webhooks = orders_col.count_documents({'webhook_received': {'$exists': True}})
        completed_via_webhook = orders_col.count_documents({'webhook_received': {'$exists': True}, 'status': 'completed'})
        
        return jsonify({
            "total_webhooks_received": total_webhooks,
            "completed_via_webhook": completed_via_webhook,
            "last_webhook": orders_col.find_one(
                {'webhook_received': {'$exists': True}},
                sort=[('webhook_received', -1)]
            ).get('webhook_received') if total_webhooks > 0 else None
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== MAIN ====================
if __name__ == '__main__':
    print("=" * 50)
    print("🌐 PAYMENT WEBHOOK SERVER STARTED")
    print("=" * 50)
    print(f"🕐 Time: {format_ist(get_ist())} IST")
    print(f"📡 Webhook URL: http://your-server:5000/webhook")
    print(f"🔍 Verify URL: http://your-server:5000/webhook/verify/<order_id>")
    print(f"💓 Health Check: http://your-server:5000/health")
    print(f"📊 Stats URL: http://your-server:5000/webhook/stats")
    print(f"👑 Admin: {OWNER_USERNAME}")
    print(f"💳 Payment API: {PAYMENT_CHECK_URL}")
    print("=" * 50)
    
    # Run Flask app
    # For production, use: gunicorn -w 4 -b 0.0.0.0:5000 webhook_server:app
    app.run(host='0.0.0.0', port=5000, debug=False)