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
    """Database model representing an image in the comparison system.
    
    Attributes:
        id: Unique identifier for the image
        filename: Name of the image file in the images directory
    """
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)

class Comparison(db.Model):
    """Database model representing a comparison between two images.
    
    Attributes:
        id: Unique identifier for the comparison
        winner_id: ID of the image that won the comparison
        loser_id: ID of the image that lost the comparison
        timestamp: When the comparison was made (UTC)
    """
    id = db.Column(db.Integer, primary_key=True)
    winner_id = db.Column(db.Integer, db.ForeignKey('image.id'), nullable=False)
    loser_id = db.Column(db.Integer, db.ForeignKey('image.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@app.route('/')
def home():
    """Render the main page of the application."""
    return render_template('index.html')

@app.route('/get_pair')
def get_pair():
    """Get a pair of images for comparison using an active learning strategy.
    
    The strategy prioritizes:
    1. Images with fewer comparisons to ensure balanced data
    2. Close matches based on win/loss ratio to refine uncertain rankings
    3. Falls back to random selection if no clear priorities
    
    Returns:
        JSON response with either:
        - Two images (id and filename) if a valid pair is found
        - Finished status if all possible pairs have been compared
        - Error message if there aren't enough images or no valid pairs
    """
    # Get all images
    images = Image.query.all()
    if len(images) < 2:
        return jsonify({'error': 'Not enough images'}), 400
    
    # Get all image IDs and calculate total possible pairs
    image_ids = [img.id for img in images]
    total_possible_pairs = len(image_ids) * (len(image_ids) - 1) // 2
    
    # Get existing comparisons
    existing_comparisons = set()
    # Track win/loss counts for each image
    win_counts = defaultdict(int)
    loss_counts = defaultdict(int)
    comparison_counts = defaultdict(int)
    
    comparisons = Comparison.query.all()
    for comp in comparisons:
        pair = (min(comp.winner_id, comp.loser_id), max(comp.winner_id, comp.loser_id))
        existing_comparisons.add(pair)
        win_counts[comp.winner_id] += 1
        loss_counts[comp.loser_id] += 1
        comparison_counts[comp.winner_id] += 1
        comparison_counts[comp.loser_id] += 1
    
    if len(existing_comparisons) >= total_possible_pairs:
        return jsonify({'status': 'finished'})
    
    # Calculate win ratio for each image
    win_ratios = {}
    for img_id in image_ids:
        total = win_counts[img_id] + loss_counts[img_id]
        if total > 0:
            win_ratios[img_id] = win_counts[img_id] / total
        else:
            win_ratios[img_id] = 0.5  # Default for new images
    
    # Get valid pairs and score them
    valid_pairs = []
    for i1 in image_ids:
        for i2 in image_ids:
            if i1 < i2 and (i1, i2) not in existing_comparisons:
                # Score based on:
                # 1. Prioritize images with fewer comparisons
                comparison_priority = -max(comparison_counts[i1], comparison_counts[i2])
                # 2. Prioritize close matches (similar win ratios)
                ratio_difference = abs(win_ratios[i1] - win_ratios[i2])
                
                score = comparison_priority - ratio_difference
                valid_pairs.append((score, i1, i2))
    
    if not valid_pairs:
        return jsonify({'error': 'No valid pairs available'}), 400
    
    # Sort by score and add some randomization to prevent getting stuck
    valid_pairs.sort(reverse=True)  # Higher scores first
    # Take top 20% of pairs and randomly select from them
    top_pairs = valid_pairs[:max(1, len(valid_pairs) // 5)]
    score, img1_id, img2_id = random.choice(top_pairs)
    
    img1 = Image.query.get(img1_id)
    img2 = Image.query.get(img2_id)
    
    return jsonify({
        'status': 'success',
        'image1': {'id': img1.id, 'filename': img1.filename},
        'image2': {'id': img2.id, 'filename': img2.filename}
    })

@app.route('/submit_comparison', methods=['POST'])
def submit_comparison():
    """Submit a comparison between two images.
    
    Expects JSON data with:
        winner_id: ID of the winning image
        loser_id: ID of the losing image
    
    Returns:
        JSON response indicating success status
    """
    data = request.json
    winner_id = data.get('winner_id')
    loser_id = data.get('loser_id')
    
    comparison = Comparison(winner_id=winner_id, loser_id=loser_id)
    db.session.add(comparison)
    db.session.commit()
    
    return jsonify({'status': 'success'})

@app.route('/images/<path:filename>')
def serve_image(filename):
    """Serve an image file from the images directory.
    
    Args:
        filename: Name of the image file to serve
        
    Returns:
        The requested image file
    """
    return send_from_directory('images', filename)

@app.route('/rankings')
def rankings():
    """Generate a ranking page showing all images and their comparison counts.
    
    Returns:
        Rendered rankings.html template with sorted image results
    """
    # Get all images and their comparison counts
    images = Image.query.all()
    comparison_counts = defaultdict(int)
    
    # Count wins and losses for each image
    comparisons = Comparison.query.all()
    for comp in comparisons:
        comparison_counts[comp.winner_id] += 1
        comparison_counts[comp.loser_id] += 1
    
    # Create result objects with comparison counts
    results = []
    for img in images:
        results.append({
            'id': img.id,
            'filename': img.filename,
            'comparisons_count': comparison_counts[img.id]
        })
    
    # Sort by number of comparisons
    results.sort(key=lambda x: x['comparisons_count'], reverse=True)
    return render_template('rankings.html', images=results)

def init_db():
    """Initialize the database by creating all defined tables."""
    with app.app_context():
        db.create_all()

@app.route('/comparisons.csv')
def export_comparisons():
    """Export all comparisons as CSV file.
    
    Returns:
        CSV file containing:
        - Timestamp of comparison
        - Winner image filename
        - Loser image filename
        
    The CSV is returned as a downloadable file attachment.
    """
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

@app.route('/reset_db', methods=['POST'])
def reset_db():
    """Reset the database by dropping all comparisons while keeping images.
    
    Returns:
        JSON response indicating success status
    """
    try:
        # Delete all comparisons
        Comparison.query.delete()
        db.session.commit()
        return jsonify({'status': 'success', 'message': 'Database reset successful'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True, extra_files=extra_files) 