from flask import Flask, request, jsonify
import hashlib
import hmac
import os
from datetime import datetime

app = Flask(__name__)

# Replace with your actual bot token
BOT_TOKEN = os.getenv('BOT_TOKEN', '7696316358:AAGZw4OUGAT628QX2DBleIVV2JWQTfiQu88')

@app.route('/auth', methods=['GET'])
def auth():
    try:
        # Get all the required parameters from Telegram
        init_data = request.args.to_dict()
        
        # Verify the data (important for security)
        if not verify_telegram_data(init_data):
            return jsonify({'error': 'Invalid authentication'}), 401
        
        # Extract user data
        user_data = {
            'id': init_data.get('id'),
            'first_name': init_data.get('first_name'),
            'last_name': init_data.get('last_name'),
            'username': init_data.get('username'),
            'photo_url': init_data.get('photo_url'),
            'auth_date': int(init_data.get('auth_date')),
            'language_code': init_data.get('language_code'),
            'is_premium': init_data.get('is_premium', 'false').lower() == 'true'
        }
        
        # Return the user data to be displayed in the frontend
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Redirecting...</title>
            <script>
                window.location.hash = encodeURIComponent(JSON.stringify({user_data}));
                window.location.href = window.location.origin;
            </script>
        </head>
        <body>
            Redirecting...
        </body>
        </html>
        """
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def verify_telegram_data(init_data):
    """
    Verify the integrity of the data received from Telegram Widget
    """
    try:
        # Extract hash from the data
        received_hash = init_data.pop('hash')
        
        # Sort all received parameters alphabetically by key
        data_check_string = '\n'.join(
            f"{key}={value}"
            for key, value in sorted(init_data.items())
        )
        
        # Calculate the secret key
        secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
        
        # Calculate HMAC signature
        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # Compare the calculated hash with the received hash
        return calculated_hash == received_hash
    
    except Exception:
        return False

if __name__ == '__main__':
    app.run(debug=True)
