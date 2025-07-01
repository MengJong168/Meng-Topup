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

app = Flask(__name__)

# Bakong API setup
api_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJkYXRhIjp7ImlkIjoiNmFmM2FlMWU3Yzg4NDQ3OCJ9LCJpYXQiOjE3NDM1MTE4MjUsImV4cCI6MTc1MTI4NzgyNX0.ShQ-iQ96VKcqktZZnigUgqaDuooeuPGpnduzdtNxBGA"
khqr = KHQR(api_token)
current_transactions = {}

# Create static/images directory if it doesn't exist
os.makedirs('static/images', exist_ok=True)

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

@app.route('/check_payment', methods=['POST'])
def check_payment():
    try:
        transaction_id = request.form['transaction_id']
        if transaction_id not in current_transactions:
            return jsonify({'error': 'Invalid transaction ID'}), 400
            
        transaction = current_transactions[transaction_id]
        
        # Check if expired
        if datetime.now() > datetime.fromisoformat(transaction['expiry']):
            return jsonify({
                'status': 'EXPIRED',
                'message': 'QR code has expired'
            })
        
        md5_hash = transaction['md5_hash']
        status = khqr.check_payment(md5_hash)
        
        if status == "PAID":
            amount = transaction['amount']
            # Send to Telegram
            send_to_telegram(transaction)
            return jsonify({
                'status': 'PAID',
                'message': f'Payment of ${amount:.2f} received!',
                'amount': amount
            })
        elif status == "UNPAID":
            return jsonify({
                'status': 'UNPAID',
                'message': 'Payment not received yet'
            })
        else:
            return jsonify({
                'status': 'ERROR',
                'message': f'Status: {status}'
            })
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def send_to_telegram(transaction):
    """Send transaction details to Telegram"""
    # Generate invoice number with seconds (INVNO-YYYYMMDDHHMMSS)
    invoice_number = f"INVNO-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    # Rest of the function remains the same...
    if transaction.get('game_type') == 'ff':  # Free Fire
        process_chat_id = '-1002591110258'  # Free Fire channel
        process_text = f"{transaction['player_id']} 0 {transaction['package']}"
    else:  # Mobile Legends
        process_chat_id = '-1002796371372'  # Mobile Legends channel
        process_text = f"{transaction['player_id']} {transaction['zone_id']} {transaction['package']}"
    
    invoice_text = (
        "Payment Successful\n"
        f"📄 Invoice: {invoice_number}\n"
        f"👤 Player ID: {transaction['player_id']}\n"
        f"🌐 Zone ID: {transaction['zone_id']}\n"
        f"🎮 Package: {transaction['package']}\n"
        f"💵 Amount: ${float(transaction['amount']):.2f}\n"
        f"📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    try:
        import requests
        requests.post(
            'https://api.telegram.org/bot8039794961:AAHsZCVdd9clK7uYtCJaUKH8JKjlLLWefOM/sendMessage',
            json={
                'chat_id': process_chat_id,
                'text': process_text
            }
        )
        
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


