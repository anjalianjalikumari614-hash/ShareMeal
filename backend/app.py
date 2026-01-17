from flask import Flask, send_from_directory, request, jsonify, redirect
import sys
import os
import datetime
import sqlite3
from werkzeug.utils import secure_filename
import random

# Add project root to sys.path to import from database folder
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from database.db import get_db_connection, init_db

app = Flask(__name__, static_folder='../frontend', static_url_path='')

# Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '../frontend/uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Ensure DB is initialized
init_db()

@app.route('/')
def home():
    return send_from_directory('../frontend/user', 'index.html')

@app.route('/donor-home')
def donor_home():
    return send_from_directory('../frontend/donor', 'home-donor.html')

@app.route('/donate')
def donate():
    return send_from_directory('../frontend/donor', 'donate.html')

@app.route('/find-food')
def find_food():
    return send_from_directory('../frontend/ngos', 'find-food.html')

@app.route('/delivery')
def delivery_redirect():
    return redirect('/delivery/dashboard')

@app.route('/delivery/dashboard')
def delivery_dashboard():
    return send_from_directory('../frontend/delivery', 'dashboard.html')

@app.route('/login')
def login():
    return send_from_directory('../frontend/user', 'login.html')

@app.route('/signup')
def signup():
    return send_from_directory('../frontend/user', 'signup.html')

@app.route('/admin')
def admin():
    return send_from_directory('../frontend/admin', 'admin.html')

@app.route('/donor')
def donor_dashboard():
    return send_from_directory('../frontend/donor', 'donor.html')

# --- API Routes ---

@app.route('/api/chat/send', methods=['POST'])
def send_message():
    data = request.json
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Use .get() to avoid KeyError if key is missing
        cursor.execute('''
            INSERT INTO messages (donation_id, sender_id, receiver_id, message, timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (data.get('donation_id'), data.get('sender_id'), data.get('receiver_id'), data.get('message'), timestamp))
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        print(f"Error sending message: {e}") # Debug log
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/chat/<int:donation_id>', methods=['GET'])
def get_messages(donation_id):
    try:
        conn = get_db_connection()
        # Join with users to get sender names
        messages = conn.execute('''
            SELECT m.*, u.name as sender_name, u.role as sender_role
            FROM messages m
            JOIN users u ON m.sender_id = u.id
            WHERE m.donation_id = ?
            ORDER BY m.id ASC
        ''', (donation_id,)).fetchall()
        conn.close()
        return jsonify([dict(row) for row in messages])
    except Exception as e:
        print(f"Error fetching messages: {e}")
        return jsonify([]), 200 # Return empty list on error to prevent frontend crash

@app.route('/api/notifications/<int:user_id>', methods=['GET'])
def get_notifications(user_id):
    try:
        conn = get_db_connection()
        # Count unread messages
        count = conn.execute('SELECT COUNT(*) FROM messages WHERE receiver_id = ? AND is_read = 0', (user_id,)).fetchone()[0]
        conn.close()
        return jsonify({'unread_count': count})
    except Exception as e:
        return jsonify({'unread_count': 0})

@app.route('/api/chat/mark-read', methods=['POST'])
def mark_messages_read():
    data = request.json
    try:
        conn = get_db_connection()
        conn.execute('''
            UPDATE messages 
            SET is_read = 1 
            WHERE donation_id = ? AND receiver_id = ?
        ''', (data.get('donation_id'), data.get('user_id')))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False})

@app.route('/api/signup', methods=['POST'])
def api_signup():
    data = request.json
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO users (name, email, password, phone, role) VALUES (?, ?, ?, ?, ?)',
                       (data['name'], data['email'], data['password'], data['phone'], data['role']))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'User created successfully'})
    except sqlite3.IntegrityError:
        return jsonify({'success': False, 'message': 'Email already exists'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE email = ? AND password = ?', (data['email'], data['password']))
    user = cursor.fetchone()
    conn.close()

    if user:
        requested_role = data.get('role')
        if requested_role and user['role'].lower() != requested_role.lower():
             return jsonify({'success': False, 'message': f'Account exists but is not a {requested_role.capitalize()} account.'}), 401

        return jsonify({
            'success': True, 
            'role': user['role'], 
            'name': user['name'],
            'id': user['id']
        })
    else:
        return jsonify({'success': False, 'message': 'Invalid credentials'}), 401

@app.route('/api/donate', methods=['POST'])
def api_donate():
    # Handle Form Data (Multipart)
    data = request.form
    file = request.files.get('image')
    
    timestamp_dt = datetime.datetime.now()
    timestamp = timestamp_dt.strftime("%Y-%m-%d %H:%M:%S")
    
    # Default expiry: 6 hours from now
    expiry_dt = timestamp_dt + datetime.timedelta(hours=6)
    expiry_datetime = expiry_dt.strftime("%Y-%m-%d %H:%M:%S")

    image_path = None

    if file and allowed_file(file.filename):
        filename = secure_filename(f"{timestamp_dt.timestamp()}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        image_path = f"uploads/{filename}"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO donations (food_type, quantity, pickup_address, instructions, status, timestamp, donor_id, image_path, diet_type, preparation_time, expiry_datetime, food_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        data.get('foodType'), 
        data.get('quantity'), 
        data.get('address'), 
        data.get('instructions') or data.get('description'), 
        'Available', 
        timestamp,
        data.get('donorId'),
        image_path,
        data.get('dietType'),
        data.get('preparationTime'),
        expiry_datetime,
        data.get('foodName')
    ))
    
    conn.commit()
    donation_id = cursor.lastrowid
    conn.close()
    
    print("New Donation Added:", data)
    return jsonify({'message': 'Donation received successfully!', 'id': donation_id})

@app.route('/api/donate/<int:donation_id>', methods=['DELETE'])
def delete_donation(donation_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM donations WHERE id = ?', (donation_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Donation deleted successfully'})

@app.route('/api/donate/<int:donation_id>', methods=['PUT', 'POST'])
def update_donation(donation_id):
    if request.is_json:
        data = request.json
    else:
        data = request.form

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE donations 
        SET food_type = ?, quantity = ?, pickup_address = ?, instructions = ?, diet_type = ?
        WHERE id = ?
    ''', (
        data.get('foodType'),
        data.get('quantity'),
        data.get('address') or data.get('pickup_address'),
        data.get('instructions'),
        data.get('dietType') or data.get('diet_type'),
        donation_id
    ))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Donation updated successfully'})

@app.route('/api/update-status', methods=['POST'])
def update_status():
    data = request.json
    donation_id = data.get('id')
    status = data.get('status')
    ngo_id = data.get('ngo_id')  # Optional, sent when claiming
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    if status == 'Claimed' and ngo_id:
        timestamp = datetime.datetime.now().isoformat()
        otp = str(random.randint(1000, 9999))
        
        # Check if delivery_req is passed (default True)
        delivery_req = data.get('delivery_req', True)
        delivery_val = 1 if delivery_req else 0
        
        cursor.execute('''
            UPDATE donations 
            SET status = ?, claimed_by = ?, claimed_at = ?, otp = ?, delivery_req = ? 
            WHERE id = ?
        ''', (status, ngo_id, timestamp, otp, delivery_val, donation_id))
    else:

        cursor.execute('UPDATE donations SET status = ? WHERE id = ?', (status, donation_id))
    
    if cursor.rowcount > 0:
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': f'Status updated to {status}'})
    else:
        conn.close()
        return jsonify({'success': False, 'message': 'Donation not found'}), 404

@app.route('/api/cancel-claim', methods=['POST'])
def cancel_claim():
    data = request.json
    donation_id = data.get('id')
    ngo_id = data.get('ngo_id')

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check current claim status
    row = cursor.execute('SELECT claimed_at, claimed_by, status FROM donations WHERE id = ?', (donation_id,)).fetchone()
    
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Donation not found'}), 404
        
    claimed_at_str, claimed_by, status = row['claimed_at'], row['claimed_by'], row['status']
    
    if str(claimed_by) != str(ngo_id):
        conn.close()
        return jsonify({'success': False, 'message': 'Not authorized to cancel this claim'}), 403

    if status != 'Claimed':
         conn.close()
         return jsonify({'success': False, 'message': 'Item is not currently in claimed status'}), 400

    # Calculate time difference
    try:
        if claimed_at_str:
            claimed_at = datetime.datetime.fromisoformat(claimed_at_str)
            time_diff = datetime.datetime.now() - claimed_at
            if time_diff.total_seconds() > 20 * 60: # 20 minutes
                conn.close()
                return jsonify({'success': False, 'message': 'Cancellation period expired (20 mins)'}), 400
    except Exception as e:
        print(f"Time parse error: {e}")
        # If no time found, maybe allow or disallow. Let's assume strict.
        pass

    # Success: Revert
    cursor.execute('''
        UPDATE donations 
        SET status = 'Available', claimed_by = NULL, claimed_at = NULL 
        WHERE id = ?
    ''', (donation_id,))
    
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Claim cancelled successfully'})


@app.route('/api/donations')
def get_donations():
    conn = get_db_connection()
    donations = conn.execute('SELECT * FROM donations ORDER BY id DESC').fetchall()
    conn.close()
    return jsonify([dict(row) for row in donations])

@app.route('/api/donations/ngo/<int:ngo_id>')
def get_ngo_claims(ngo_id):
    conn = get_db_connection()
    donations = conn.execute('SELECT * FROM donations WHERE claimed_by = ? ORDER BY id DESC', (ngo_id,)).fetchall()
    conn.close()
    return jsonify([dict(row) for row in donations])

@app.route('/api/assign-delivery', methods=['POST'])
def assign_delivery():
    data = request.json
    donation_id = data.get('donation_id')
    delivery_id = data.get('delivery_id')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    # Ensure it is currently Claimed and not assigned
    cursor.execute('UPDATE donations SET delivery_by = ? WHERE id = ? AND status = ?', (delivery_id, donation_id, 'Claimed'))
    
    if cursor.rowcount > 0:
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    else:
        conn.close()
        return jsonify({'success': False, 'message': 'Task unavailable or already assigned'}), 400

@app.route('/api/verify-delivery', methods=['POST'])
def verify_delivery_otp():
    data = request.json
    donation_id = data.get('donation_id')
    provided_otp = data.get('otp')
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get the actual OTP
    row = cursor.execute('SELECT otp, status FROM donations WHERE id = ?', (donation_id,)).fetchone()
    
    if not row:
        conn.close()
        return jsonify({'success': False, 'message': 'Donation not found'}), 404
        
    actual_otp = row['otp']
    status = row['status']
    
    if status == 'Delivered':
        conn.close()
        return jsonify({'success': False, 'message': 'Already delivered'}), 400
        
    if str(provided_otp).strip() == str(actual_otp).strip():
        # Success
        cursor.execute("UPDATE donations SET status = 'Delivered' WHERE id = ?", (donation_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'OTP Verified! Delivery Complete.'})
    else:
        conn.close()
        return jsonify({'success': False, 'message': 'Invalid OTP. Please check with the NGO.'}), 400

@app.route('/api/donations/delivery/<int:delivery_id>')
def get_delivery_tasks(delivery_id):
    conn = get_db_connection()
    donations = conn.execute('SELECT * FROM donations WHERE delivery_by = ? ORDER BY id DESC', (delivery_id,)).fetchall()
    conn.close()
    return jsonify([dict(row) for row in donations])

@app.route('/api/donations/user/<int:user_id>')
def get_user_donations(user_id):
    conn = get_db_connection()
    donations = conn.execute('SELECT * FROM donations WHERE donor_id = ? ORDER BY id DESC', (user_id,)).fetchall()
    conn.close()
    return jsonify([dict(row) for row in donations])

@app.route('/api/user/<int:user_id>', methods=['GET'])
def get_user_profile(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT id, name, email, phone, role, address, bio, profile_pic FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    if user:
        return jsonify(dict(user))
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/user/stats/<int:user_id>', methods=['GET'])
def get_user_stats(user_id):
    conn = get_db_connection()
    donations = conn.execute('SELECT quantity FROM donations WHERE donor_id = ?', (user_id,)).fetchall()
    conn.close()

    total_meals = 0
    for d in donations:
        try:
            # Extract number from string like "50 servings" or "50kg"
            q_str = str(d['quantity'])
            num = ''.join(filter(str.isdigit, q_str))
            if num:
                total_meals += int(num)
        except:
            pass
    
    # Logic: 1 Meal = 1 Person. 
    # Logic: 1 Meal = 2.5kg CO2 saved (approx) or let's say 0.5kg to be safe.
    return jsonify({
        'meals_donated': total_meals,
        'people_fed': total_meals, 
        'co2_saved': round(total_meals * 0.5, 1)
    })

@app.route('/api/user/update', methods=['POST'])
def update_user_profile():
    # Handle both Form Data and potentially Files
    data = request.form
    file = request.files.get('profile_pic')
    
    user_id = data.get('id')
    name = data.get('name')
    phone = data.get('phone')
    address = data.get('address')
    bio = data.get('bio')
    
    profile_pic_path = None
    if file and allowed_file(file.filename):
        filename = secure_filename(f"profile_{user_id}_{datetime.datetime.now().timestamp()}_{file.filename}")
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        profile_pic_path = f"/uploads/{filename}"

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        if profile_pic_path:
            cursor.execute('''
                UPDATE users SET name = ?, phone = ?, address = ?, bio = ?, profile_pic = ? WHERE id = ?
            ''', (name, phone, address, bio, profile_pic_path, user_id))
        else:
             cursor.execute('''
                UPDATE users SET name = ?, phone = ?, address = ?, bio = ? WHERE id = ?
            ''', (name, phone, address, bio, user_id))
            
        conn.commit()
        conn.close()
        return jsonify({'success': True, 'message': 'Profile updated', 'profile_pic': profile_pic_path})
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/admin/stats')
def admin_stats():
    conn = get_db_connection()
    
    # User Stats
    users_count = conn.execute('SELECT role, COUNT(*) as count FROM users GROUP BY role').fetchall()
    stats = {
        'total_users': 0,
        'donors': 0,
        'ngos': 0,
        'delivery': 0,
        'total_donations': 0 
    }
    
    for row in users_count:
        role = row['role'].lower()
        count = row['count']
        stats['total_users'] += count
        if role in stats:
            stats[role] = count
            
    # Donation Stats
    donations_count = conn.execute('SELECT COUNT(*) as count FROM donations').fetchone()['count']
    stats['total_donations'] = donations_count
    
    conn.close()
    return jsonify(stats)

@app.route('/api/admin/users')
def admin_users():
    conn = get_db_connection()
    users = conn.execute('SELECT id, name, email, phone, role FROM users').fetchall()
    conn.close()
    return jsonify([dict(row) for row in users])

@app.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    if user_id == 1:
        return jsonify({'success': False, 'message': 'Cannot delete System Admin'}), 403
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'User deleted successfully'})

@app.route('/api/admin/analytics/donations')
def admin_donation_analytics():
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    
    # 1. Total & Breakdown
    donations = conn.execute('''
        SELECT d.*, u.name as donor_name 
        FROM donations d 
        LEFT JOIN users u ON d.donor_id = u.id 
        ORDER BY d.timestamp DESC
    ''').fetchall()
    
    conn.close()
    
    data = [dict(row) for row in donations]
    
    # Process Stats in Python for flexibility
    stats = {
        'total': len(data),
        'status': {},
        'diet': {'Veg': 0, 'Non-Veg': 0},
        'timeline': {}, # date -> count
        'recent': data[:20] # Top 20 for table
    }
    
    for d in data:
        # Status
        s = d['status']
        stats['status'][s] = stats['status'].get(s, 0) + 1
        
        # Diet
        dt = d['diet_type']
        if dt: 
            stats['diet'][dt] = stats['diet'].get(dt, 0) + 1
            
        # Timeline (YYYY-MM-DD from timestamp)
        # Timestamp format: YYYY-MM-DD HH:MM:SS
        if d['timestamp']:
            date = d['timestamp'].split(' ')[0]
            stats['timeline'][date] = stats['timeline'].get(date, 0) + 1

    return jsonify(stats)

if __name__ == '__main__':
    print("\n--------------------------------------------")
    print("   ShareMeal Python Server is Live!")
    print("   Database: SQLite (sharemeal.db)")
@app.route('/api/admin/export/donations')
def export_donations_csv():
    import csv
    import io
    from flask import make_response
    
    conn = get_db_connection()
    cursor = conn.cursor()
    # Get all donations with donor info
    donations = cursor.execute('''
        SELECT d.id, d.food_name, d.food_type, d.quantity, d.status, d.timestamp, u.name as donor_name, d.pickup_address
        FROM donations d
        LEFT JOIN users u ON d.donor_id = u.id
        ORDER BY d.timestamp DESC
    ''').fetchall()
    conn.close()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['ID', 'Food Name', 'Category', 'Quantity', 'Status', 'Date', 'Donor', 'Address'])
    
    for d in donations:
        cw.writerow([
            d['id'], 
            d['food_name'] or 'N/A', 
            d['food_type'], 
            d['quantity'], 
            d['status'], 
            d['timestamp'], 
            d['donor_name'], 
            d['pickup_address']
        ])
        
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = "attachment; filename=sharemeal_donations.csv"
    output.headers["Content-type"] = "text/csv"
    output.headers["Content-type"] = "text/csv"
    return output

@app.route('/api/admin/upload-certificate', methods=['POST'])
def upload_certificate():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file part'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'}), 400
        
    if file:
        # Save as a fixed filename to easily overwrite and reference
        filename = 'certificate_template.png'
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(path)
        return jsonify({'success': True, 'message': 'Certificate template updated successfully!', 'path': f'/uploads/{filename}?t={datetime.datetime.now().timestamp()}'})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    print("\n--------------------------------------------")
    print("   ShareMeal Python Server is Live!")
    print("   Database: SQLite (sharemeal.db)")
    print("   Open your browser at: http://localhost:3000")
    print("--------------------------------------------\n")
    app.run(port=3000, debug=False)
