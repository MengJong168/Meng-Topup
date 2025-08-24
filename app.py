from flask import Flask, render_template, request, jsonify, send_from_directory
from datetime import datetime, timedelta
import qrcode
from io import BytesIO
import base64
import requests
import time
import random
import os
from bakong_khqr import KHQR
import json
from functools import wraps

app = Flask(__name__)

# Bakong API setup
api_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiMmEyMDE3MzUxMGU4NDZhMiJ9LCJpYXQiOjE3NTEzNTk1MDQsImV4cCI6MTc1OTEzNTUwNH0.EHVbg8wD4z7wdNP4zkHmUt8VjquH4kCrJgCf_HyLK8o"
khqr = KHQR(api_token)
current_transactions = {}
# Add this after current_transactions initialization
TRANSACTIONS_FILE = '/tmp/transactions.json'  # Changed for Vercel compatibility
PACKAGES_FILE = '/tmp/packages.json'  # Changed for Vercel compatibility

# Create database directory if it doesn't exist
try:
    os.makedirs('/tmp', exist_ok=True)
except:
    pass

# Admin authentication decorator
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        password = request.args.get('pass')
        if password != "1516Coolb":
            return "Unauthorized", 401
        return f(*args, **kwargs)
    return decorated_function

# Load transactions from file
def load_transactions():
    try:
        with open(TRANSACTIONS_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"pending": [], "expired": [], "completed": []}

# Save transactions to file
def save_transactions(transactions):
    with open(TRANSACTIONS_FILE, 'w') as f:
        json.dump(transactions, f, indent=2)

# Add this route to app.py
@app.route('/admin')
@admin_required
def admin_panel():
    status_filter = request.args.get('status', 'pending')
    search_query = request.args.get('search', '').lower()
    
    transactions = load_transactions()
    filtered = transactions.get(status_filter, [])
    
    if search_query:
        filtered = [t for t in filtered if (
            search_query in t.get('transaction_id', '').lower() or
            search_query in t.get('player_id', '').lower() or
            search_query in t.get('zone_id', '').lower() or
            search_query in t.get('package', '').lower() or
            search_query in t.get('game_type', '').lower()
        )]
    
    return render_template('admin.html', 
                         transactions=filtered,
                         current_status=status_filter,
                         search_query=search_query)

# Add this before the routes
@app.template_filter('datetimeformat')
def datetimeformat(value, format='%Y-%m-%d %H:%M:%S'):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.strftime(format)

# Create static/images directory if it doesn't exist
try:
    os.makedirs('static/images', exist_ok=True)
except:
    pass

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory('static', filename)

@app.route('/generate_qr', methods=['POST'])
def generate_qr():
    try:
        amount = float(request.form['amount'])
        player_id = request.form.get('player_id', '')
        zone_id = request.form.get('zone_id', '0')  # Default to 0
        package = request.form.get('package', '')
        game_type = request.form.get('game_type', 'ml')  # 'ml' or 'ff'

        if amount <= 0:
            return jsonify({'error': 'Amount must be greater than 0'}), 400
        if amount > 10000:
            return jsonify({'error': 'Maximum amount is $10,000'}), 400

        # Generate transaction ID
        transaction_id = f"TRX{int(time.time())}"
        
        # Create QR data
        qr_data = khqr.create_qr(
            bank_account='meng_topup@aclb',
            merchant_name='Meng Topup',
            merchant_city='Phnom Penh',
            amount=amount,
            currency='USD',
            store_label='MShop',
            phone_number='855976666666',
            bill_number=transaction_id,
            terminal_label='Cashier-01',
            static=False
        )
        
        # Generate MD5 hash for verification
        md5_hash = khqr.generate_md5(qr_data)
        
        # Generate QR image
        qr_img = qrcode.make(qr_data)
        img_io = BytesIO()
        qr_img.save(img_io, 'PNG')
        img_io.seek(0)
        qr_base64 = base64.b64encode(img_io.getvalue()).decode('utf-8')
        
        # Store current transaction
        expiry = datetime.now() + timedelta(minutes=3)
        # Store current transaction
        current_transactions[transaction_id] = {
            'amount': amount,
            'md5_hash': md5_hash,
            'expiry': expiry.isoformat(),
            'player_id': player_id,
            'zone_id': zone_id,
            'package': package,
            'game_type': game_type  # Add this line
        }
        
        return jsonify({
            'success': True,
            'qr_image': qr_base64,
            'transaction_id': transaction_id,
            'amount': amount,
            'expiry': expiry.isoformat()
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Updated check_payment function
@app.route('/check_payment', methods=['POST'])
def check_payment():
    try:
        transaction_id = request.form['transaction_id']
        if transaction_id not in current_transactions:
            return jsonify({'error': 'Invalid transaction ID'}), 400
            
        transaction = current_transactions[transaction_id]
        transactions = load_transactions()
        
        # Check if expired
        if datetime.now() > datetime.fromisoformat(transaction['expiry']):
            # Move to expired if not already there
            if not any(t['transaction_id'] == transaction_id for t in transactions['expired']):
                transactions['expired'].append({
                    **transaction,
                    'transaction_id': transaction_id,
                    'status': 'expired',
                    'timestamp': datetime.now().isoformat()
                })
                save_transactions(transactions)
                
            return jsonify({
                'status': 'EXPIRED',
                'message': 'QR code has expired'
            })
        
        md5_hash = transaction['md5_hash']
        
        # Use the new API endpoint to check payment status
        response = requests.get(f"https://api-bakong-by-limvisa.shop/api/check_payment?md5={md5_hash}")
        
        if response.status_code == 200:
            payment_data = response.json()
            status = payment_data.get('status', 'UNPAID')
            
            if status == "PAID":
                amount = transaction['amount']
                # Send to Telegram
                send_to_telegram(transaction)
                
                # Move to completed
                if not any(t['transaction_id'] == transaction_id for t in transactions['completed']):
                    transactions['completed'].append({
                        **transaction,
                        'transaction_id': transaction_id,
                        'status': 'completed',
                        'timestamp': datetime.now().isoformat()
                    })
                    # Remove from pending if exists
                    transactions['pending'] = [t for t in transactions['pending'] 
                                             if t['transaction_id'] != transaction_id]
                    save_transactions(transactions)
                
                return jsonify({
                    'status': 'PAID',
                    'message': f'Payment of ${amount:.2f} received!',
                    'amount': amount
                })
            elif status == "UNPAID":
                # Add to pending if not already there
                if not any(t['transaction_id'] == transaction_id for t in transactions['pending']):
                    transactions['pending'].append({
                        **transaction,
                        'transaction_id': transaction_id,
                        'status': 'pending',
                        'timestamp': datetime.now().isoformat()
                    })
                    save_transactions(transactions)
                    
                return jsonify({
                    'status': 'UNPAID',
                    'message': 'Payment not received yet'
                })
            else:
                return jsonify({
                    'status': 'ERROR',
                    'message': f'Status: {status}'
                })
        else:
            return jsonify({
                'status': 'ERROR',
                'message': 'Failed to check payment status'
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if not os.path.exists(PACKAGES_FILE):
    with open(PACKAGES_FILE, 'w') as f:
        json.dump({
            "ml": [
                {"name": "11", "price": 0.25}, 
                {"name": "56", "price": 0.89},
            ],
            "ff": [
                {"name": "25", "price": 0.30},
                {"name": "100", "price": 0.99},
            ],
            "ml_special_offers": [
                {"name": "11", "price": 0.20, "image": "ml-diamond.jpg"},
                {"name": "56", "price": 0.80, "image": "ml-diamond.jpg"},
                {"name": "86", "price": 1.10, "image": "ml-diamond.jpg"}
            ],
            "ff_special_offers": [
                {"name": "25", "price": 0.25, "image": "ff-diamond.jpg"},
                {"name": "100", "price": 0.95, "image": "ff-diamond.jpg"},
                {"name": "310", "price": 2.70, "image": "ff-diamond.jpg"}
            ]
        }, f, indent=2)

# Update the admin_packages and admin_special_offers routes to include HOK
@app.route('/admin/packages')
@admin_required
def admin_packages():
    """Admin endpoint for managing regular packages including MCGG"""
    try:
        with open(PACKAGES_FILE, 'r') as f:
            packages = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        app.logger.error(f"Error loading packages: {str(e)}")
        packages = {
            "ml": [],
            "ff": [],
            "pubg": [],
            "hok": [],
            "bloodstrike": [],
            "mcgg": []
        }
    
    # Validate package structure
    for game_type in ['ml', 'ff', 'pubg', 'hok', 'bloodstrike', 'mcgg']:
        if not isinstance(packages.get(game_type, []), list):
            packages[game_type] = []
            app.logger.warning(f"Invalid package format for {game_type}, reset to empty list")
    
    return render_template('admin_packages.html', 
                         ml_packages=packages.get('ml', []),
                         ff_packages=packages.get('ff', []),
                         pubg_packages=packages.get('pubg', []),
                         hok_packages=packages.get('hok', []),
                         bloodstrike_packages=packages.get('bloodstrike', []),
                         mcgg_packages=packages.get('mcgg', []))

@app.route('/admin/special_offers')
@admin_required
def admin_special_offers():
    """Admin endpoint for managing special offers including MCGG"""
    try:
        with open(PACKAGES_FILE, 'r') as f:
            packages = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        app.logger.error(f"Error loading special offers: {str(e)}")
        packages = {
            "ml_special_offers": [],
            "ff_special_offers": [],
            "pubg_special_offers": [],
            "hok_special_offers": [],
            "bloodstrike_special_offers": [],
            "mcgg_special_offers": []
        }
    
    # Validate special offers structure
    for game_type in ['ml', 'ff', 'pubg', 'hok', 'bloodstrike', 'mcgg']:
        offer_key = f"{game_type}_special_offers"
        if not isinstance(packages.get(offer_key, []), list):
            packages[offer_key] = []
            app.logger.warning(f"Invalid special offers format for {game_type}, reset to empty list")
    
    return render_template('admin_special_offers.html',
        ml_offers=packages.get("ml_special_offers", []),
        ff_offers=packages.get("ff_special_offers", []),
        pubg_offers=packages.get("pubg_special_offers", []),
        hok_offers=packages.get("hok_special_offers", []),
        bloodstrike_offers=packages.get("bloodstrike_special_offers", []),
        mcgg_offers=packages.get("mcgg_special_offers", [])
    )

@app.route('/admin/update_package', methods=['POST'])
@admin_required
def update_package():
    try:
        data = request.get_json() or request.form
        game_type = data.get('game_type')
        package_name = data.get('package_name')
        new_price = data.get('new_price')

        if not all([game_type, package_name, new_price]):
            return jsonify({'error': 'Missing required fields'}), 400

        try:
            new_price = float(new_price)
        except ValueError:
            return jsonify({'error': 'Price must be a number'}), 400

        # Load packages
        with open(PACKAGES_FILE, 'r') as f:
            packages = json.load(f)

        # Update package
        updated = False
        for pkg in packages.get(game_type, []):
            if pkg['name'] == package_name:
                pkg['price'] = new_price
                updated = True
                break

        if not updated:
            return jsonify({'error': 'Package not found'}), 404

        # Save changes
        with open(PACKAGES_FILE, 'w') as f:
            json.dump(packages, f, indent=2)

        return jsonify({'success': True, 'new_price': new_price})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/get_packages')
def get_packages():
    try:
        # Default package structure with PUBG packages
        default_packages = {
            "ml": [
                {"name": "11", "price": 0.25},
                {"name": "56", "price": 0.89}
            ],
            "ff": [
                {"name": "25", "price": 0.30},
                {"name": "100", "price": 0.99}
            ],
            "pubg": [  # Add PUBG packages
                {"name": "60", "price": 0.99},
                {"name": "325", "price": 4.99},
                {"name": "660", "price": 9.99}
            ],
            "hok": [
                {
                    "name": "16 TOKENS",
                    "price": 0.25,
                    "image": "",
                    "package_id": 302
                }
            ],
            "bloodstrike": [
                {"name": "Elite Pass", "price": 4.10, "image": "bs-elite_pass.jpg", "package_id": 250}
            ],
            "mcgg": [
        {
            "name": "86 Diamonds",
            "price": 1.40,
            "image": "",
            "package_id": 605
        },
        {
            "name": "172 Diamonds",
            "price": 2.60,
            "image": "",
            "package_id": 606
        }
    ],
            "ml_special_offers": [
                {"name": "11", "price": 0.20, "image": "ml-diamond.jpg"}
            ],
            "ff_special_offers": [
                {"name": "25", "price": 0.25, "image": "ff-diamond.jpg"}
            ],
            "pubg_special_offers": [  # Add PUBG special offers
                {"name": "60", "price": 0.89, "image": "pubg-uc.jpg"},
                {"name": "325", "price": 4.49, "image": "pubg-uc.jpg"}
            ],
           "hok_special_offers": [
                {
                    "name": "16 TOKENS",
                    "price": 0.25,
                    "image": "",
                    "package_id": 302
                }
            ],
            "bloodstrike_special_offers": [
                {"name": "Elite Pass", "price": 4.05, "image": "bs-elite_pass.jpg", "package_id": 250}
            ],
            "mcgg_special_offers": [
        {
            "name": "86+86 Diamonds",
            "price": 2.50,
            "image": "mcgg-diamond.jpg",
            "package_id": 607
        }
    ]
}

         # Create file if doesn't exist
        if not os.path.exists(PACKAGES_FILE):
            with open(PACKAGES_FILE, 'w') as f:
                json.dump(default_packages, f, indent=2)
            return jsonify(default_packages)

        # Load existing packages
        with open(PACKAGES_FILE, 'r') as f:
            try:
                packages = json.load(f)
                # Validate structure - ensure all game types exist
                for key in ['ml', 'ff', 'pubg', 'hok', 'bloodstrike', 'ml_special_offers', 'ff_special_offers', 'pubg_special_offers', 'hok_special_offers', 'bloodstrike_special_offers']:
                    if key not in packages:
                        packages[key] = default_packages.get(key, [])
                return jsonify(packages)
            except json.JSONDecodeError:
                # If file is corrupted, recreate it
                with open(PACKAGES_FILE, 'w') as f:
                    json.dump(default_packages, f, indent=2)
                return jsonify(default_packages)
    except Exception as e:
        print(f"Error loading packages: {str(e)}")
        return jsonify({
            "ml": [],
            "ff": [],
            "pubg": [],
            "hok": [],
            "bloodstrike": [],
            "ml_special_offers": [],
            "ff_special_offers": [],
            "pubg_special_offers": [],
            "hok_special_offers": [],
            "bloodstrike_special_offers": [],
            "error": str(e)
        }), 500
    
@app.route('/admin/update_special_offer', methods=['POST'])
@admin_required
def update_special_offer():
    try:
        data = request.get_json() or request.form
        game_type = data.get('game_type')
        offer_name = data.get('offer_name')
        new_price = data.get('new_price')

        if not all([game_type, offer_name, new_price]):
            return jsonify({'error': 'Missing required fields'}), 400

        try:
            new_price = float(new_price)
        except ValueError:
            return jsonify({'error': 'Price must be a number'}), 400

        # Load packages
        with open(PACKAGES_FILE, 'r') as f:
            packages = json.load(f)

        # Update special offer
        section = f"{game_type}_special_offers"
        updated = False
        for offer in packages.get(section, []):
            if offer['name'] == offer_name:
                offer['price'] = new_price
                updated = True
                break

        if not updated:
            return jsonify({'error': 'Special offer not found'}), 404

        # Save changes
        with open(PACKAGES_FILE, 'w') as f:
            json.dump(packages, f, indent=2)

        return jsonify({'success': True, 'new_price': new_price})

    except Exception as e:
        return jsonify({'error': str(e)}), 500

def send_to_telegram(transaction):
    """Send transaction details to Telegram"""
    # Generate invoice number
    invoice_number = f"INVNO-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # Load packages data
    try:
        with open(PACKAGES_FILE, 'r') as f:
            packages_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        packages_data = {}
    
    # Get package_id from database
    package_id = "UNKNOWN"
    game_type = transaction.get('game_type', 'ml')
    package_name = transaction.get('package', '')
    
    # Search for package in regular packages
    for pkg in packages_data.get(game_type, []):
        if pkg.get('name') == package_name:
            package_id = pkg.get('package_id', package_name)
            break
    else:
        # If not found in regular packages, check special offers
        for pkg in packages_data.get(f"{game_type}_special_offers", []):
            if pkg.get('name') == package_name:
                package_id = pkg.get('package_id', package_name)
                break
    
    # Determine processing channel and format
    if game_type == 'ff':  # Free Fire
       process_chat_id = '-1002809349921'
       process_text = f"{transaction['player_id']} 0 {package_id}"
    elif game_type == 'bloodstrike':
       process_chat_id = '-1002796371372'  # Update with your actual channel ID
       process_text = f"{transaction['player_id']} 0000 {package_id}"
    elif game_type == 'pubg':  # PUBG Mobile
       process_chat_id = '-1002796371372' 
       process_text = f"{transaction['player_id']} 0000 {package_id}"
    elif game_type == 'hok':  # HONOR OF KING
       process_chat_id = '-1002796371372'  # Update with your actual channel ID
       process_text = f"{transaction['player_id']} 0000 {package_id}"
    elif game_type == 'mcgg':  # Magic Chess: Go Go
       process_chat_id = '-1002796371372'  # Update with your actual channel ID
       process_text = f"{transaction['player_id']} {transaction['zone_id']} {package_id}"
    else:  # Mobile Legends (default)
       process_chat_id = '-1002796371372'
       process_text = f"{transaction['player_id']} {transaction['zone_id']} {package_id}"
    
    # Create invoice message               
    invoice_text = (
        "Payment Successful\n"
        f"📄 Invoice: {invoice_number}\n"
        f"👤 Player ID: {transaction['player_id']}\n"
        f"🌐 Zone ID: {transaction['zone_id']}\n"
        f"🎮 Package: {package_name} (ID: {package_id})\n"
        f"💵 Amount: ${float(transaction['amount']):.2f}\n"
        f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    try:
        # Send to processing channel
        requests.post(
            'https://api.telegram.org/bot8039794961:AAHsZCVdd9clK7uYtCJaUKH8JKjlLLWefOM/sendMessage',
            json={
                'chat_id': process_chat_id,
                'text': process_text
            }
        )
        
        # Send to invoice channel
        requests.post(
            'https://api.telegram.org/bot8039794961:AAHsZCVdd9clK7uYtCJaUKH8JKjlLLWefOM/sendMessage',
            json={
                'chat_id': '-1002765171217',
                'text': invoice_text,
                'parse_mode': 'Markdown'
            }
        )
        
        return invoice_number
        
    except Exception as e:
        print(f"Error sending to Telegram: {e}")
        return None

# This is required for Vercel
if __name__ == '__main__':
    app.run(debug=True)
