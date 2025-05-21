import os
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory
from flask_pymongo import PyMongo
from werkzeug.utils import secure_filename
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from bson import ObjectId

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'supersecretkey')
app.config['MONGO_URI'] = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/suraksha')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

mongo = PyMongo(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        address = request.form['address']
        password = request.form['password']
        kyc_doc = request.files['kyc_doc']
        if mongo.db.volunteers.find_one({'phone': phone}):
            flash('Phone number already registered!')
            return redirect(url_for('register'))
        filename = secure_filename(kyc_doc.filename)
        kyc_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        kyc_doc.save(kyc_path)
        mongo.db.volunteers.insert_one({
            'name': name,
            'phone': phone,
            'address': address,
            'password': generate_password_hash(password),
            'kyc_doc': filename,
            'kyc_status': 'approved',
            'created_at': datetime.utcnow()
        })
        flash('Registration successful! You can now log in.')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        phone = request.form['phone']
        password = request.form['password']
        volunteer = mongo.db.volunteers.find_one({'phone': phone})
        if volunteer and check_password_hash(volunteer['password'], password):
            session['volunteer_id'] = str(volunteer['_id'])
            session['volunteer_name'] = volunteer['name']
            flash('Login successful!')
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid credentials!')
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'volunteer_id' not in session:
        return redirect(url_for('login'))
    profile = mongo.db.volunteers.find_one({'_id': ObjectId(session['volunteer_id'])})
    contacts = list(mongo.db.contacts.find({'volunteer_id': session['volunteer_id']}))
    media_files = list(mongo.db.media.find({'volunteer_id': session['volunteer_id']}))
    # All other volunteers
    volunteers = list(mongo.db.volunteers.find({'_id': {'$ne': ObjectId(session['volunteer_id'])}}))
    # Alerts received by this user
    alerts = list(mongo.db.alerts.find({'to_id': session['volunteer_id']}))
    return render_template('dashboard.html', profile=profile, contacts=contacts, media_files=media_files, volunteers=volunteers, alerts=alerts)

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('Logged out!')
    return redirect(url_for('login'))

@app.route('/sos', methods=['POST'])
def sos():
    if 'volunteer_id' not in session:
        return redirect(url_for('login'))
    lat = request.form.get('lat')
    lon = request.form.get('lon')
    # Save SOS alert
    mongo.db.alerts.insert_one({
        'volunteer_id': session['volunteer_id'],
        'name': session['volunteer_name'],
        'lat': lat,
        'lon': lon,
        'timestamp': datetime.utcnow(),
        'type': 'sos',
        'status': 'active'
    })
    # Notify all other volunteers
    other_volunteers = mongo.db.volunteers.find({'_id': {'$ne': ObjectId(session['volunteer_id'])}})
    for v in other_volunteers:
        mongo.db.alerts.insert_one({
            'from_id': session['volunteer_id'],
            'to_id': str(v['_id']),
            'from_name': session['volunteer_name'],
            'type': 'sos',
            'lat': lat,
            'lon': lon,
            'status': 'pending',
            'created_at': datetime.utcnow()
        })
    flash('SOS alert sent to all volunteers!')
    return redirect(url_for('dashboard'))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/add_contact', methods=['POST'])
def add_contact():
    if 'volunteer_id' not in session:
        return redirect(url_for('login'))
    name = request.form['contact_name']
    phone = request.form['contact_phone']
    mongo.db.contacts.insert_one({
        'volunteer_id': session['volunteer_id'],
        'name': name,
        'phone': phone
    })
    flash('Contact added!')
    return redirect(url_for('dashboard'))

@app.route('/upload_media', methods=['POST'])
def upload_media():
    if 'volunteer_id' not in session:
        return redirect(url_for('login'))
    media_file = request.files['media_file']
    media_type = request.form['media_type']
    if not media_file:
        flash('No file uploaded!')
        return redirect(url_for('dashboard'))
    filename = secure_filename(media_file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    media_file.save(save_path)
    mongo.db.media.insert_one({
        'volunteer_id': session['volunteer_id'],
        'filename': filename,
        'media_type': media_type,
        'uploaded_at': datetime.utcnow()
    })
    flash('Media uploaded!')
    return redirect(url_for('dashboard'))

@app.route('/delete_media', methods=['POST'])
def delete_media():
    if 'volunteer_id' not in session:
        return redirect(url_for('login'))
    media_id = request.form['media_id']
    filename = request.form['filename']
    # Remove from DB
    mongo.db.media.delete_one({'_id': ObjectId(media_id), 'volunteer_id': session['volunteer_id']})
    # Remove file from disk
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(file_path):
        os.remove(file_path)
    flash('Media deleted!')
    return redirect(url_for('dashboard'))

@app.route('/send_alert', methods=['POST'])
def send_alert():
    if 'volunteer_id' not in session:
        return redirect(url_for('login'))
    target_id = request.form['target_id']
    mongo.db.alerts.insert_one({
        'from_id': session['volunteer_id'],
        'to_id': target_id,
        'from_name': session['volunteer_name'],
        'status': 'pending',
        'created_at': datetime.utcnow()
    })
    flash('Alert sent!')
    return redirect(url_for('dashboard'))

@app.route('/respond_alert', methods=['POST'])
def respond_alert():
    if 'volunteer_id' not in session:
        return redirect(url_for('login'))
    alert_id = request.form['alert_id']
    mongo.db.alerts.update_one({'_id': ObjectId(alert_id), 'to_id': session['volunteer_id']}, {'$set': {'status': 'responded'}})
    flash('You have responded to the alert!')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True) 