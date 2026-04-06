from datetime import datetime, timezone
from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy, extension
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from dotenv import load_dotenv
import os
import bcrypt
import boto3
import uuid
from botocore.client import Config
from werkzeug.utils import secure_filename

load_dotenv()

s3 = boto3.client(
    's3',
    endpoint_url=os.environ.get('R2_ENDPOINT_URL'),
    aws_access_key_id=os.environ.get('R2_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('R2_SECRET_ACCESS_KEY'),
    config=Config(signature_version='s3v4')
)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)

class Clip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    game = db.Column(db.String(150), nullable=True)
    url = db.Column(db.String(300), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    owner = db.relationship('User', backref=db.backref('clips', lazy=True))



@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if not username or not password:
            return render_template('register.html', error='All fields are required.')

        if len(password) < 8:
            return render_template('register.html', error='Password must be at least 8 characters.')
        
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return render_template('register.html', error='Username already taken.')

        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        new_user = User(username=username, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if not user or not bcrypt.checkpw(password.encode('utf-8'), user.password):
            return render_template('login.html', error='Invalid username or password.')
        if user and bcrypt.checkpw(password.encode('utf-8'), user.password):
            login_user(user)
            return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def home():
    return render_template('home.html', username=current_user.username)

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        file = request.files.get('file_upload')
        if len(file.read()) > app.config['MAX_CONTENT_LENGTH']:
            return render_template('upload.html', error='File too large. Max 50MB.')
        file.seek(0) 
        if not file or file.filename == '':
            return render_template('upload.html', error='No file selected.')
        
        extension = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{extension}"
        
        s3.upload_fileobj(
            file,
            os.environ.get('R2_BUCKET_NAME'),
            filename,
            ExtraArgs={'ContentType': file.content_type}
        )
        
        url = f"{os.environ.get('R2_ENDPOINT_URL')}/{os.environ.get('R2_BUCKET_NAME')}/{filename}"
        
        new_clip = Clip(
            title=request.form.get('title', 'Untitled Clip'),
            game=request.form.get('game', ''),
            url = f"{os.environ.get('R2_PUBLIC_URL')}/{filename}",
            user_id=current_user.id
        )
        db.session.add(new_clip)
        db.session.commit()
        return redirect(url_for('clips'))
    
    return render_template('upload.html')

@app.route('/clips')
@login_required
def clips():
    all_clips = Clip.query.filter_by(user_id=current_user.id).all()
    return render_template('clips.html', clips=all_clips)

with app.app_context():
    db.create_all()