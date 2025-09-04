import mimetypes
import os
import urllib.parse
import uuid
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for
from werkzeug.utils import secure_filename
from watermark import apply_watermark  # your watermark function
from firebase_admin import credentials, initialize_app, storage, firestore

app = Flask(__name__)

# --- App config (static and uploads) ---
app.config['UPLOAD_FOLDER'] = 'static/images/originals'
app.config['WATERMARKED_FOLDER'] = 'static/images/watermarked'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

# --- Firebase init ---
app.config['FIREBASE_STORAGE_BUCKET'] = os.environ.get(
    "FIREBASE_STORAGE_BUCKET",
    "profileuploads-3de42.firebasestorage.app"
)

cred_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "serviceAccountKey.json")
cred = credentials.Certificate(cred_path)
initialize_app(cred, {"storageBucket": app.config['FIREBASE_STORAGE_BUCKET']})

# Firestore client (use `fs`, not `db`, to avoid confusion with prior SQLAlchemy var)
fs = firestore.client()

# --------- Helpers ---------
def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def upload_to_firebase(local_path: str, dest_path: str) -> str:
    """
    Uploads a file to Firebase Storage at dest_path and returns a durable download URL
    using a firebaseStorageDownloadTokens token.
    """
    bucket = storage.bucket()
    blob = bucket.blob(dest_path)

    # Guess content type
    ctype, _ = mimetypes.guess_type(local_path)
    if not ctype:
        ctype = "application/octet-stream"

    # Generate a token to allow direct download
    token = uuid.uuid4().hex
    blob.metadata = {"firebaseStorageDownloadTokens": token}

    # Upload file
    blob.upload_from_filename(local_path, content_type=ctype)

    # Construct public download URL (token-based)
    quoted_name = urllib.parse.quote(blob.name, safe="")
    url = f"https://firebasestorage.googleapis.com/v0/b/{bucket.name}/o/{quoted_name}?alt=media&token={token}"
    return url

def doc_to_dict(doc):
    """Convert a Firestore DocumentSnapshot to a dict with 'id'."""
    d = doc.to_dict() or {}
    d["id"] = doc.id
    return d

# --------- Routes ---------

@app.route('/')
def home():
    # featured photos only
    snaps = fs.collection('photos').where('is_featured', '==', True).stream()
    photos = [doc_to_dict(d) for d in snaps]
    return render_template('index.html', photos=photos)

@app.route('/gallery')
def gallery():
    category_filter = request.args.get('category', 'all')
    col = fs.collection('photos')

    if category_filter == 'all':
        snaps = col.stream()
    else:
        snaps = col.where('category', '==', category_filter).stream()

    photos = [doc_to_dict(d) for d in snaps]

    # Build categories dynamically from data
    cat_snaps = col.select(['category']).stream()
    categories = ['all'] + sorted({(d.to_dict() or {}).get('category') for d in cat_snaps if (d.to_dict() or {}).get('category')})

    return render_template('gallery.html',
                           photos=photos,
                           selected_category=category_filter,
                           categories=categories)

@app.route('/upload', methods=['GET', 'POST'])
def upload():
    # keep in sync with your expected categories
    categories = ['animals', 'people', 'landscape']

    if request.method == 'POST':
        if 'photo' not in request.files:
            return "No file part", 400

        file = request.files['photo']
        category = request.form.get('category')

        if not category or category not in categories:
            return "Invalid or missing category", 400
        if file.filename == '':
            return "No selected file", 400
        if not allowed_file(file.filename):
            return "Invalid file type", 400

        # Ensure temp folders exist (ephemeral OK)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        os.makedirs(app.config['WATERMARKED_FOLDER'], exist_ok=True)

        # Unique safe filename
        ext = Path(file.filename).suffix.lower()
        filename = f"{uuid.uuid4().hex}{ext}"
        safe_filename = secure_filename(filename)

        original_path = os.path.join(app.config['UPLOAD_FOLDER'], safe_filename)
        watermarked_path = os.path.join(app.config['WATERMARKED_FOLDER'], safe_filename)

        # Save original locally
        file.save(original_path)

        # Apply watermark
        apply_watermark(original_path, watermarked_path)

        # Upload watermarked to Firebase Storage
        dest_path = f"{category}/{safe_filename}"
        try:
            public_url = upload_to_firebase(watermarked_path, dest_path)
        except Exception as e:
            # Clean up and report
            try:
                os.remove(original_path)
                os.remove(watermarked_path)
            except OSError:
                pass
            return (f"Upload to Firebase failed: {e}", 500)

        # Save metadata in Firestore
        fs.collection('photos').add({
            'filename': safe_filename,
            'category': category,
            'is_featured': False,
            'price': 0.0,
            'storage_url': public_url,
        })

        # Clean up local temp files
        for p in (original_path, watermarked_path):
            try:
                os.remove(p)
            except OSError:
                pass

        return redirect(url_for('gallery'))

    return render_template('upload.html', categories=categories)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/pricing')
def pricing():
    services = [doc_to_dict(d) for d in fs.collection('prices').where('item_type', '==', 'Service').stream()]
    prints   = [doc_to_dict(d) for d in fs.collection('prices').where('item_type', '==', 'Print').stream()]
    return render_template('pricing.html', services=services, prints=prints)

@app.route("/admin/seed-prices")
def seed_prices():
    prices = [
        {"item_type": "Service", "label": "Corporate Head Shot",                 "amount": 25.00},
        {"item_type": "Service", "label": "20min Mini Session Indoor or Out",    "amount": 60.00},
        {"item_type": "Service", "label": "1hr Session 2-Locations",             "amount": 150.00},
        {"item_type": "Service", "label": "2hr Multiple Locations",              "amount": 250.00},
        {"item_type": "Print",   "label": "Digital Copy E-mail",                 "amount": 10.00},
        {"item_type": "Print",   "label": "5x7 Print",                           "amount": 15.00},
        {"item_type": "Print",   "label": "8x10 Print",                          "amount": 25.00},
        {"item_type": "Print",   "label": "11x14 Print",                         "amount": 30.00},
        {"item_type": "Print",   "label": "13x19 Print",                         "amount": 35.00},
    ]
    batch = fs.batch()
    col = fs.collection('prices')
    for p in prices:
        ref = col.document()  # auto id
        batch.set(ref, p)
    batch.commit()
    return "Seeded prices successfully!"

@app.route('/admin/prices', methods=['POST'])
def update_price():
    price_id = request.form.get('price_id')   # your form must send the Firestore doc id
    label = request.form.get('label')
    amount = float(request.form.get('amount', 0))

    if price_id:
        ref = fs.collection('prices').document(price_id)
        ref.update({"label": label, "amount": amount})

    return redirect('/admin')

@app.route('/admin', methods=['GET', 'POST'])
def admin():
    if request.method == 'POST':
        photo_id = request.form.get('photo_id')
        is_featured = request.form.get('is_featured') == '1'
        price = float(request.form.get('price', 0))
        category = request.form.get('category')

        if photo_id:
            ref = fs.collection('photos').document(photo_id)
            updates = {'is_featured': is_featured, 'price': price}
            if category:
                updates['category'] = category
            ref.update(updates)

    photos = [doc_to_dict(d) for d in fs.collection('photos').stream()]
    prices = [doc_to_dict(d) for d in fs.collection('prices').stream()]
    return render_template('admin.html', photos=photos, prices=prices)

# --- Local dev runner (Render will use gunicorn start command) ---
if __name__ == "__main__":
    # Ensure temp dirs exist (OK on local/dev)
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['WATERMARKED_FOLDER'], exist_ok=True)
    app.run(debug=True)
