from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
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
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'doc', 'docx', 'txt', 'mp4', 'mov', 'avi', 'mkv', 'webm'}
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# In-memory file storage (for simplicity)
files = {}
file_counter = 0

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def get_file_extension(filename):
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ""

# Routes
@app.route('/')
def index():
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    # Get file type filter
    file_type = request.args.get('type', 'all')
    
    # Filter files
    user_files = list(files.values())
    
    if file_type != 'all':
        if file_type == 'images':
            user_files = [f for f in user_files if f['file_type'].lower() in ['png', 'jpg', 'jpeg', 'webp', 'gif']]
        elif file_type == 'documents':
            user_files = [f for f in user_files if f['file_type'].lower() in ['pdf', 'doc', 'docx', 'txt']]
        elif file_type == 'videos':
            user_files = [f for f in user_files if f['file_type'].lower() in ['mp4', 'mov', 'avi']]
    
    return render_template('dashboard.html', shared_files=user_files)

@app.route('/image-search', methods=['GET'])
def image_search():
    # Check if there's a search query
    image_url = request.args.get('image_url')
    similar_images = []
    
    if image_url:
        # Just return some example files as "similar" for testing
        image_files = [f for f in files.values() if f['file_type'].lower() in ['png', 'jpg', 'jpeg', 'webp', 'gif']]
        similar_images = [(f['file'], 90 - i * 5) for i, f in enumerate(image_files[:5])]
    
    return render_template('image_search.html', similar_images=similar_images)

@app.route('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# API Routes
@app.route('/api/shared-files', methods=['GET', 'POST'])
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
            filename = file.filename
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
            
            new_file = {
                'id': file_id,
                'file': file_url,
                'file_name': filename,
                'file_size': human_file_size,
                'shared_by': 'user',
                'share_type': request.form.get('share_type', 'public'),
                'share_time': datetime.datetime.now(),
                'share_expiry': datetime.datetime.now() + datetime.timedelta(days=30),
                'file_type': file_type,
                'shared_to': [],
                'file_description': f"File uploaded on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}",
                'metadata': {},
                'feature_vector': None
            }
            
            files[file_id] = new_file
            
            return jsonify(new_file), 201
        
        return jsonify({"error": "File type not allowed"}), 400
    
    # GET - Return all files
    return jsonify(list(files.values()))

@app.route('/api/shared-files/<int:file_id>', methods=['GET', 'PUT', 'DELETE'])
def api_shared_file_detail(file_id):
    file = files.get(file_id)
    
    if not file:
        return jsonify({"error": "File not found"}), 404
    
    if request.method == 'GET':
        return jsonify(file)
    
    elif request.method == 'PUT':
        data = request.json
        # Update allowed fields
        for field in ['share_type', 'shared_to', 'file_description']:
            if field in data:
                file[field] = data[field]
        
        return jsonify(file)
    
    elif request.method == 'DELETE':
        # Remove the file
        del files[file_id]
        
        # Delete the actual file from disk
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], os.path.basename(file['file']))
        if os.path.exists(file_path):
            os.remove(file_path)
        
        return "", 204

@app.route('/api/similar-images', methods=['GET'])
def api_similar_images():
    image_url = request.args.get("image_url")
    if not image_url:
        return jsonify({"error": "image_url parameter is required"}), 400
    
    # Just return some test files as "similar"
    image_files = [f for f in files.values() if f['file_type'].lower() in ['png', 'jpg', 'jpeg', 'webp', 'gif']]
    similar_images = [(f['file'], 90 - i * 5) for i, f in enumerate(image_files[:5])]
    
    return jsonify(similar_images)

@app.route('/api/generate-description/<int:file_id>', methods=['POST'])
def api_generate_description(file_id):
    file = files.get(file_id)
    
    if not file:
        return jsonify({"error": "File not found"}), 404
    
    # Check if it's an image
    if file['file_type'].lower() not in ['png', 'jpg', 'jpeg', 'webp', 'gif']:
        return jsonify({"error": "Description generation only available for images"}), 400
    
    # Generate a simple description (you could integrate with an AI service here)
    description = f"This appears to be a {file['file_type']} image named {file['file_name']}. It shows what looks like visual content that might be useful for your project or collection. The image was uploaded on {file['share_time'].strftime('%Y-%m-%d')}."
    
    # Update file
    file['file_description'] = description
    
    return jsonify({"file_description": description})

if __name__ == '__main__':
    app.run(debug=True, port=5000)