import os
import random
import csv
from io import StringIO
from flask import Flask, render_template, request, jsonify, send_from_directory, Response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy import or_, and_, func
from collections import defaultdict

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///comparisons.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Enable hot reloading for templates
extra_dirs = ['templates']
extra_files = extra_dirs[:]
for extra_dir in extra_dirs:
    for dirname, dirs, files in os.walk(extra_dir):
        for filename in files:
            filename = os.path.join(dirname, filename)
            if os.path.isfile(filename):
                extra_files.append(filename)

class Image(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)

class Comparison(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    winner_id = db.Column(db.Integer, db.ForeignKey('image.id'), nullable=False)
    loser_id = db.Column(db.Integer, db.ForeignKey('image.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

def calculate_ratings():
    # Get all images and comparisons
    images = Image.query.all()
    comparisons = Comparison.query.all()
    
    # Initialize scores and comparison counts
    scores = {img.id: 0.5 for img in images}  # Start at 0.5
    comparison_counts = defaultdict(int)
    
    # Count comparisons per image
    for comp in comparisons:
        comparison_counts[comp.winner_id] += 1
        comparison_counts[comp.loser_id] += 1
    
    # Calculate ratings using ELO-like system
    k = 0.05  # Learning rate
    
    # Sort comparisons by timestamp to apply them in order
    sorted_comparisons = sorted(comparisons, key=lambda x: x.timestamp)
    
    for comp in sorted_comparisons:
        winner_score = scores[comp.winner_id]
        loser_score = scores[comp.loser_id]
        
        # Calculate expected probability of winning
        expected_winner = 1 / (1 + 10 ** ((loser_score - winner_score) / 0.1))
        
        # Update scores
        scores[comp.winner_id] += k * (1 - expected_winner)
        scores[comp.loser_id] += k * (0 - expected_winner)
        
        # Keep scores between 0 and 1
        scores[comp.winner_id] = min(1, max(0, scores[comp.winner_id]))
        scores[comp.loser_id] = min(1, max(0, scores[comp.loser_id]))
    
    # Create result objects with all needed information
    results = []
    for img in images:
        results.append({
            'id': img.id,
            'filename': img.filename,
            'quality_score': scores[img.id],
            'comparisons_count': comparison_counts[img.id]
        })
    
    # Sort by quality score
    results.sort(key=lambda x: x['quality_score'], reverse=True)
    return results

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/get_pair')
def get_pair():
    # Get all images
    images = Image.query.all()
    if len(images) < 2:
        return jsonify({'error': 'Not enough images'}), 400
    
    # Get all image IDs
    image_ids = [img.id for img in images]
    
    # Calculate total possible pairs
    total_possible_pairs = len(image_ids) * (len(image_ids) - 1) // 2
    
    # Get all existing comparisons
    existing_comparisons = set()
    comparisons = Comparison.query.all()
    for comp in comparisons:
        pair = (min(comp.winner_id, comp.loser_id), max(comp.winner_id, comp.loser_id))
        existing_comparisons.add(pair)
    
    # If all possible pairs have been compared, return finished status
    if len(existing_comparisons) >= total_possible_pairs:
        return jsonify({'status': 'finished'})
    
    # Try to find a pair that hasn't been compared yet
    all_possible_pairs = [(i1, i2) for i1 in image_ids for i2 in image_ids if i1 < i2]
    random.shuffle(all_possible_pairs)
    
    for img1_id, img2_id in all_possible_pairs:
        if (img1_id, img2_id) not in existing_comparisons:
            # Found a pair that hasn't been compared
            img1 = Image.query.get(img1_id)
            img2 = Image.query.get(img2_id)
            return jsonify({
                'status': 'success',
                'image1': {'id': img1.id, 'filename': img1.filename},
                'image2': {'id': img2.id, 'filename': img2.filename}
            })
    
    # This should never happen as we checked total pairs earlier
    return jsonify({'error': 'No valid pairs available'}), 400

@app.route('/submit_comparison', methods=['POST'])
def submit_comparison():
    data = request.json
    winner_id = data.get('winner_id')
    loser_id = data.get('loser_id')
    
    comparison = Comparison(winner_id=winner_id, loser_id=loser_id)
    db.session.add(comparison)
    db.session.commit()
    
    return jsonify({'status': 'success'})

@app.route('/images/<path:filename>')
def serve_image(filename):
    return send_from_directory('images', filename)

@app.route('/rankings')
def rankings():
    # Calculate current ratings based on all comparisons
    ranked_images = calculate_ratings()
    return render_template('rankings.html', images=ranked_images)

def scan_for_new_images():
    """Scan the images directory and add any new images to the database."""
    new_images = []
    for filename in os.listdir('images'):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif')):
            if not Image.query.filter_by(filename=filename).first():
                image = Image(filename=filename)
                db.session.add(image)
                new_images.append(filename)
    db.session.commit()
    return new_images

@app.route('/scan_images', methods=['POST'])
def scan_images():
    """Endpoint to trigger scanning for new images."""
    new_images = scan_for_new_images()
    return jsonify({
        'status': 'success',
        'new_images': new_images,
        'count': len(new_images)
    })

def init_db():
    with app.app_context():
        db.create_all()
        scan_for_new_images()

@app.route('/export')
def export_page():
    """Show the export page with available export options."""
    return render_template('export.html')

@app.route('/export/comparisons.csv')
def export_comparisons():
    """Export all comparisons as CSV file."""
    # Create a string buffer to write CSV data
    si = StringIO()
    writer = csv.writer(si)
    
    # Write header
    writer.writerow(['Timestamp', 'Winner Image', 'Loser Image'])
    
    # Get all comparisons with image filenames
    # Create an alias for the second join to Image table
    LoserImage = db.aliased(Image)
    
    comparisons = db.session.query(
        Comparison.timestamp,
        Image.filename.label('winner_filename'),
        LoserImage.filename.label('loser_filename')
    ).join(
        Image, Comparison.winner_id == Image.id
    ).join(
        LoserImage, Comparison.loser_id == LoserImage.id
    ).order_by(Comparison.timestamp).all()
    
    # Write data rows
    for comp in comparisons:
        writer.writerow([
            comp.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            comp.winner_filename,
            comp.loser_filename
        ])
    
    # Create the response
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=comparisons.csv'}
    )

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True, extra_files=extra_files) 