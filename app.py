from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, send_from_directory
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import json
import datetime
import requests
import uuid
import pickle
from PIL import Image
import io
import base64

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'doc', 'docx', 'txt'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Setup login manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# In-memory database (for simplicity)
users = {}
files = {}
file_counter = 0

# Sample NVIDIA API Key for image descriptions (replace with your key in production)
NVIDIA_API_KEY = "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"

# User class
class User(UserMixin):
    def __init__(self, id, email, username, password_hash, first_name="", last_name=""):
        self.id = id
        self.email = email
        self.username = username
        self.password_hash = password_hash
        self.first_name = first_name
        self.last_name = last_name
        self.date_joined = datetime.datetime.now()

@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_file_extension(filename):
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ""

def generate_image_description(image_url):
    """Generate a description for an image using NVIDIA API"""
    try:
        # Download the image
        response = requests.get(image_url)
        if response.status_code != 200:
            return "No description available"
        
        # Convert to base64
        image_b64 = base64.b64encode(response.content).decode()
        
        # Call NVIDIA API
        invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {NVIDIA_API_KEY}",
            "Accept": "text/event-stream"
        }
        
        payload = {
            "model": 'microsoft/phi-3.5-vision-instruct',
            "messages": [
                {
                    "role": "user",
                    "content": f'Describe the image. <img src="data:image/jpeg;base64,{image_b64}" />'
                }
            ],
            "max_tokens": 512,
            "temperature": 0.20,
            "top_p": 0.70,
            "stream": True
        }
        
        response = requests.post(invoke_url, headers=headers, json=payload)
        message = ""
        for line in response.iter_lines():
            if line:
                decoded = line.decode("utf-8")
                for ln in decoded.strip().split("\n"):
                    if ln.startswith("data: "):
                        msg = ln[len("data: "):]
                        if msg != "[DONE]":
                            try:
                                entry = json.loads(msg)
                                content = entry["choices"][0]["delta"].get("content", "")
                                if content:
                                    message += content
                            except:
                                pass
                                
        return message or "No description available"
    except Exception as e:
        print(f"Error generating image description: {e}")
        return "Error generating description"

def search_similar_images(query_image_path, all_files):
    """Simplified version of image similarity search (without actual ML model)"""
    # This is a simplified placeholder - in production use a real model like CLIP
    image_files = [f for f in all_files.values() if f['file_type'].lower() in ['png', 'jpg', 'jpeg', 'webp', 'gif']]
    
    # Sort by upload date as a placeholder for similarity
    # In a real implementation, calculate embedding similarity
    sorted_files = sorted(image_files, key=lambda x: x['share_time'], reverse=True)
    
    # Return with mock similarity scores
    return [(f['file'], round(90 - i * 5)) for i, f in enumerate(sorted_files[:5])]

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Find user by email
        user = next((u for u in users.values() if u.email == email), None)
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Invalid email or password')
    
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        username = request.form.get('username')
        password = request.form.get('password')
        password2 = request.form.get('password2')
        first_name = request.form.get('first_name', '')
        last_name = request.form.get('last_name', '')
        
        # Check if email already exists
        if any(u.email == email for u in users.values()):
            flash('Email already registered')
            return render_template('signup.html')
        
        # Check if username already exists
        if any(u.username == username for u in users.values()):
            flash('Username already taken')
            return render_template('signup.html')
        
        # Check if passwords match
        if password != password2:
            flash('Passwords do not match')
            return render_template('signup.html')
        
        # Create new user
        user_id = str(uuid.uuid4())
        users[user_id] = User(
            id=user_id,
            email=email,
            username=username,
            password_hash=generate_password_hash(password),
            first_name=first_name,
            last_name=last_name
        )
        
        flash('Account created successfully')
        return redirect(url_for('login'))
    
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Get file type filter
    file_type = request.args.get('type', 'all')
    
    # Filter user's files
    user_files = [f for f in files.values() if f['shared_by'] == current_user.id]
    
    if file_type != 'all':
        if file_type == 'images':
            user_files = [f for f in user_files if f['file_type'].lower() in ['png', 'jpg', 'jpeg', 'webp', 'gif']]
        elif file_type == 'documents':
            user_files = [f for f in user_files if f['file_type'].lower() in ['pdf', 'doc', 'docx', 'txt']]
        elif file_type == 'videos':
            user_files = [f for f in user_files if f['file_type'].lower() in ['mp4', 'mov', 'avi']]
    
    return render_template('dashboard.html', shared_files=user_files)

@app.route('/image-search', methods=['GET'])
@login_required
def image_search():
    # Check if there's a search query
    image_url = request.args.get('image_url')
    similar_images = []
    
    if image_url:
        similar_images = search_similar_images(image_url, files)
        similar_images = [(url, score) for url, score in similar_images]
    
    return render_template('image_search.html', similar_images=similar_images)

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# API Routes
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    
    # Check if email already exists
    if any(u.email == data.get('email') for u in users.values()):
        return jsonify({"error": "Email already registered"}), 400
    
    # Create new user
    user_id = str(uuid.uuid4())
    new_user = User(
        id=user_id,
        email=data.get('email'),
        username=data.get('username'),
        password_hash=generate_password_hash(data.get('password')),
        first_name=data.get('first_name', ''),
        last_name=data.get('last_name', '')
    )
    
    users[user_id] = new_user
    
    return jsonify({
        "user": {
            "id": new_user.id,
            "email": new_user.email,
            "username": new_user.username,
        },
        "message": "User registered successfully"
    }), 201

@app.route('/api/shared-files', methods=['GET', 'POST'])
@login_required
def api_shared_files():
    global file_counter
    
    if request.method == 'POST':
        # Handle file upload
        if 'file' not in request.files:
            return jsonify({"error": "No file part"}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Ensure filename is unique
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(file_path):
                filename = f"{base}_{counter}{ext}"
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                counter += 1
            
            # Save the file
            file.save(file_path)
            
            file_type = get_file_extension(filename)
            file_size = os.path.getsize(file_path)
            human_file_size = f"{file_size/1024:.1f} KB" if file_size < 1024*1024 else f"{file_size/(1024*1024):.1f} MB"
            
            # Create file record
            file_id = file_counter
            file_counter += 1
            
            file_url = url_for('uploaded_file', filename=filename, _external=True)
            
            # Generate description for images
            file_description = None
            if file_type.lower() in ['png', 'jpg', 'jpeg', 'webp', 'gif']:
                file_description = "Image description will be generated on request"
            
            new_file = {
                'id': file_id,
                'file': file_url,
                'file_name': filename,
                'file_size': human_file_size,
                'shared_by': current_user.id,
                'share_type': request.form.get('share_type', 'private'),
                'share_time': datetime.datetime.now(),
                'share_expiry': datetime.datetime.now() + datetime.timedelta(days=30),
                'file_type': file_type,
                'shared_to': json.loads(request.form.get('shared_to', '[]')),
                'file_description': file_description,
                'metadata': {},
                'feature_vector': None
            }
            
            files[file_id] = new_file
            
            return jsonify(new_file), 201
        
        return jsonify({"error": "File type not allowed"}), 400
    
    # GET - Return user's files
    user_files = [f for f in files.values() if f['shared_by'] == current_user.id]
    return jsonify(user_files)

@app.route('/api/shared-files/<int:file_id>', methods=['GET', 'PUT', 'DELETE'])
@login_required
def api_shared_file_detail(file_id):
    file = files.get(file_id)
    
    if not file:
        return jsonify({"error": "File not found"}), 404
    
    # Check if user has access to the file
    if file['shared_by'] != current_user.id and current_user.email not in file['shared_to'] and file['share_type'] != 'public':
        return jsonify({"error": "Access denied"}), 403
    
    if request.method == 'GET':
        return jsonify(file)
    
    elif request.method == 'PUT':
        # Only file owner can update
        if file['shared_by'] != current_user.id:
            return jsonify({"error": "Only the owner can update this file"}), 403
        
        data = request.json
        # Update allowed fields
        for field in ['share_type', 'shared_to', 'file_description']:
            if field in data:
                file[field] = data[field]
        
        return jsonify(file)
    
    elif request.method == 'DELETE':
        # Only file owner can delete
        if file['shared_by'] != current_user.id:
            return jsonify({"error": "Only the owner can delete this file"}), 403
        
        # Remove the file
        del files[file_id]
        
        # Delete the actual file from disk
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(file['file']))
        if os.path.exists(file_path):
            os.remove(file_path)
        
        return "", 204

@app.route('/api/generate-description/<int:file_id>', methods=['POST'])
@login_required
def api_generate_description(file_id):
    file = files.get(file_id)
    
    if not file:
        return jsonify({"error": "File not found"}), 404
    
    # Check if user has access to the file
    if file['shared_by'] != current_user.id:
        return jsonify({"error": "Access denied"}), 403
    
    # Check if it's an image
    if file['file_type'].lower() not in ['png', 'jpg', 'jpeg', 'webp', 'gif']:
        return jsonify({"error": "Description generation only available for images"}), 400
    
    # Generate description
    description = generate_image_description(file['file'])
    
    # Update file
    file['file_description'] = description
    
    return jsonify({"file_description": description})

@app.route('/api/similar-images', methods=['GET'])
@login_required
def api_similar_images():
    image_url = request.args.get("image_url")
    if not image_url:
        return jsonify({"error": "image_url parameter is required"}), 400
    
    similar_images = search_similar_images(image_url, files)
    return jsonify(similar_images)

if __name__ == '__main__':
    # Create a demo admin user
    admin_id = 'admin'
    if admin_id not in users:
        users[admin_id] = User(
            id=admin_id,
            email='admin@example.com',
            username='admin',
            password_hash=generate_password_hash('password'),
            first_name='Admin',
            last_name='User'
        )
    
    app.run(debug=True, port=5000)