"""
===========================================
🌐 PAYMENT WEBHOOK SERVER - DARKXALPHA.IN (FIXED - NO DOUBLE POINTS)
===========================================
Developer: @VIP_X_OFFICIAL
Version: 3.0 (FIXED - Idempotency Check Added)
Purpose: Handle payment callbacks and auto-add points (Single time only)
===========================================
"""

from flask import Flask, request, jsonify
from pymongo import MongoClient
from datetime import datetime
from pytz import timezone
import requests
import logging
import hashlib

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

# Store processed webhook IDs to prevent duplicates (in-memory cache)
# For production, use Redis or database
processed_webhooks = {}
PROCESSED_EXPIRY = 3600  # 1 hour

# ==================== DATABASE CONNECTION ====================
try:
    client = MongoClient(MONGODB_URI)
    db = client['vip_bot']
    users_col = db['users']
    transactions_col = db['transactions']
    orders_col = db['orders']
    
    # Create index for webhook_id to prevent duplicates
    if 'webhook_id' not in orders_col.index_information():
        orders_col.create_index('webhook_id', unique=True, sparse=True)
    
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


def generate_webhook_id(order_id, timestamp, amount):
    """Generate unique ID for webhook to prevent duplicates"""
    unique_string = f"{order_id}_{timestamp}_{amount}"
    return hashlib.md5(unique_string.encode()).hexdigest()


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
        return response.json()
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return None


# ==================== WEBHOOK ROUTES ====================
@app.route('/webhook', methods=['POST'])
def payment_webhook():
    """
    Handle payment callback from darkxalpha.in
    FIXED: Prevents double points addition
    """
    try:
        # Get data from request
        if request.is_json:
            data = request.get_json()
        else:
            data = request.form.to_dict()
        
        logger.info(f"📥 Webhook Received: {data}")
        
        # Extract order_id and status
        order_id = data.get('order_id') or data.get('orderId') or data.get('txnid')
        status = str(data.get('status', '')).upper()
        amount = data.get('amount', '0')
        utr = data.get('utr') or data.get('txnid') or data.get('reference_id', '')
        timestamp = data.get('timestamp', get_ist().strftime('%Y%m%d%H%M%S'))
        
        if not order_id:
            logger.error("❌ No order_id in webhook data")
            return jsonify({"error": "Missing order_id"}), 400
        
        # Generate unique webhook ID to prevent duplicates
        webhook_id = generate_webhook_id(order_id, timestamp, amount)
        
        # CRITICAL FIX: Check if this webhook was already processed
        # First check in-memory cache
        if webhook_id in processed_webhooks:
            logger.warning(f"⚠️ Duplicate webhook detected! Webhook ID: {webhook_id} already processed at {processed_webhooks[webhook_id]}")
            return "OK - Already Processed", 200
        
        # Also check in database if order already has webhook_id
        existing_order = orders_col.find_one({'webhook_id': webhook_id})
        if existing_order:
            logger.warning(f"⚠️ Duplicate webhook found in DB! Order: {order_id} already processed")
            return "OK - Already Processed", 200
        
        # Find order in database
        order = orders_col.find_one({'order_id': order_id})
        if not order:
            order = orders_col.find_one({'api_order_id': order_id})
        
        if not order:
            logger.error(f"❌ Order {order_id} not found in database")
            return jsonify({"error": "Order not found"}), 404
        
        user_id = order.get('user_id')
        
        # CRITICAL FIX: Check if order is already marked as completed
        if order.get('status') == 'completed':
            logger.warning(f"⚠️ Order {order_id} already marked as completed! Skipping duplicate webhook.")
            return "OK - Already Completed", 200
        
        # Process based on status
        if status == "SUCCESS" or status == "COMPLETED":
            points = order.get('points', 0)
            
            # DOUBLE CHECK: Verify if points already added via transaction
            existing_transaction = transactions_col.find_one({
                'user_id': user_id,
                'reason': {'$regex': f"Payment completed for order {order_id}"}
            })
            
            if existing_transaction:
                logger.warning(f"⚠️ Points already added for order {order_id}! Transaction exists.")
                return "OK - Already Added", 200
            
            # Add points to user (ONLY ONCE!)
            new_balance = add_points(
                user_id, 
                points, 
                f"Payment completed for order {order_id}"
            )
            
            if new_balance:
                # Update order status with webhook_id
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
                
                # Add to processed cache
                processed_webhooks[webhook_id] = get_ist().strftime("%Y-%m-%d %H:%M:%S")
                
                # Clean old entries from cache (keep last 100)
                if len(processed_webhooks) > 100:
                    keys_to_remove = list(processed_webhooks.keys())[:50]
                    for key in keys_to_remove:
                        del processed_webhooks[key]
                
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
                
                # Send success message to user (ONLY ONCE)
                send_telegram_message(user_id, success_msg)
                
                # Notify admin
                admin_msg = f"""
💰 <b>Payment Auto-Approved!</b>

🆔 Order: <code>{order_id}</code>
👤 User: <code>{user_id}</code>
💰 Amount: ₹{amount}
📦 Points: {points}
🔖 UTR: {utr}
🕐 Time: {format_ist(get_ist())}

✅ Points automatically added via webhook!
                """
                send_telegram_message(OWNER_ID, admin_msg)
                
                logger.info(f"✅ Payment processed successfully for order {order_id} (Webhook ID: {webhook_id})")
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
                    'webhook_id': webhook_id,
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
    """Handle GET requests (for testing)"""
    return jsonify({
        "status": "active",
        "message": "Payment webhook is running (FIXED - No Double Points)",
        "time": format_ist(get_ist()),
        "processed_count": len(processed_webhooks)
    }), 200


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        users_col.count_documents({})
        db_status = "connected"
    except:
        db_status = "disconnected"
    
    return jsonify({
        "status": "healthy",
        "database": db_status,
        "time": format_ist(get_ist()),
        "version": "3.0 - Fixed Double Webhook"
    }), 200


@app.route('/webhook/stats', methods=['GET'])
def webhook_stats():
    """Get webhook statistics"""
    try:
        total_webhooks = orders_col.count_documents({'webhook_received': {'$exists': True}})
        completed_via_webhook = orders_col.count_documents({'webhook_received': {'$exists': True}, 'status': 'completed'})
        duplicate_detected = orders_col.count_documents({'duplicate': True}) if 'duplicate' in orders_col.index_information() else 0
        
        return jsonify({
            "total_webhooks_received": total_webhooks,
            "completed_via_webhook": completed_via_webhook,
            "cache_size": len(processed_webhooks),
            "duplicate_prevented": duplicate_detected,
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
    print("🌐 PAYMENT WEBHOOK SERVER STARTED (FIXED - NO DOUBLE POINTS)")
    print("=" * 50)
    print(f"🕐 Time: {format_ist(get_ist())} IST")
    print(f"📡 Webhook URL: http://your-server:5000/webhook")
    print(f"💓 Health Check: http://your-server:5000/health")
    print(f"📊 Stats URL: http://your-server:5000/webhook/stats")
    print(f"👑 Admin: {OWNER_USERNAME}")
    print("=" * 50)
    print("✅ FIXES APPLIED:")
    print("   ✓ Webhook ID Generation for duplicate detection")
    print("   ✓ In-memory cache for recent webhooks")
    print("   ✓ Database duplicate check")
    print("   ✓ Order status verification before adding points")
    print("   ✓ Transaction existence check")
    print("=" * 50)
    
    # Run Flask app
    app.run(host='0.0.0.0', port=5000, debug=False)