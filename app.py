from flask import Flask, render_template, request, redirect, url_for
import psycopg2
import os
import snapgene_reader
import html
import re
from urllib.parse import urlparse

app = Flask(__name__)

# 🔗 Load Database URL from Railway Environment Variable
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:axFMHCxrnMoJxPyVHhFJGRKDJnkPwoZi@yamanote.proxy.rlwy.net:27874/railway")

db_info = urlparse(DATABASE_URL)

DB_CONFIG = {
    'dbname': db_info.path[1:],  # Remove leading '/'
    'user': db_info.username,
    'password': db_info.password,
    'host': db_info.hostname,
    'port': db_info.port
}

def get_db_connection():
    """Establish a connection to the PostgreSQL database."""
    return psycopg2.connect(**DB_CONFIG)    

# ✅ Define SnapGene `.dna` File Directory
SNAPGENE_DIR = r"C:\Users\cdrac\OneDrive - 株式会社Dioseve\Shared Documents - Research\03 Lab management\Tokyo\Plasmid Stock\plasmid_database\snapgene"

# 🧬 Function to clean sequence data before storing/searching
def clean_sequence(sequence):
    """Remove all line breaks, spaces, and store sequence as a continuous string."""
    return re.sub(r'\s+', '', sequence)  # Remove all whitespace

# 🧬 Extract SnapGene Features
def extract_snapgene_features(file_path):
    """Extract sequence and annotated features from SnapGene .dna file."""
    try:
        snapgene_data = snapgene_reader.snapgene_file_to_dict(file_path)
        sequence = snapgene_data.get("seq", "").upper()
        features = [
            {
                "name": f.get("name", "Unknown"),
                "type": f.get("type", "misc"),
                "start": f.get("start", 0),
                "end": f.get("end", 0)
            } 
            for f in snapgene_data.get("features", [])
        ]
        return sequence, features
    except Exception as e:
        print(f"❌ ERROR: Failed to read SnapGene file: {e}")
        return None, []

# 🧬 Get Plasmids with Correct Sorting
def get_plasmids(search_query=None):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()

        query = """
            SELECT id, name, backbone, insert, selection_marker, ori, sequence, 
                   stock_concentration, preparation_date, map_link 
            FROM plasmids 
            WHERE %s IS NULL 
               OR id ILIKE %s 
               OR name ILIKE %s 
               OR insert ILIKE %s 
               OR similarity(sequence, %s) > 0.3  -- Use pg_trgm similarity search
            ORDER BY 
                LEFT(id, 1) ASC,  
                CAST(REGEXP_REPLACE(id, '[A-Za-z]', '', 'g') AS INTEGER) ASC;
        """
        cursor.execute(query, (search_query, f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", search_query))

        plasmids = cursor.fetchall()

        print("✅ Sorted Plasmids:", [p[0] for p in plasmids])

        cursor.close()
        conn.close()

        return plasmids

    except Exception as e:
        print("❌ Database Error:", str(e))
        return []

    
# 🎨 Highlight Features in Sequence
def highlight_snapgene_features(sequence, features):
    """Ensure correct feature highlighting without breaking sequence formatting."""
    sequence = html.escape(sequence)  # Prevent HTML injection
    annotations = sorted([(f["start"], f["end"], f["name"], re.sub(r"[^a-z0-9_-]", "-", f["type"].lower())) for f in features])

    # ✅ Apply spans correctly
    highlighted_sequence, last_index = [], 0
    for start, end, name, feature_type in annotations:
        highlighted_sequence.append(sequence[last_index:start])  # Unmodified sequence
        highlighted_sequence.append(
            f'<span class="snap-feature {feature_type}" title="{html.escape(name)}">{sequence[start:end]}</span>'
        )
        last_index = end
    highlighted_sequence.append(sequence[last_index:])  # Remaining sequence

    # ✅ Ensure span tags do NOT interfere with line breaks
    raw_highlighted = "".join(highlighted_sequence)
    formatted_sequence = "<br>".join([raw_highlighted[i:i+100] for i in range(0, len(raw_highlighted), 100)])

    return formatted_sequence


# 🏠 Homepage - View All Plasmids & Search Functionality
@app.route("/", methods=["GET"])
def index():
    search_query = request.args.get("search")
    plasmids = get_plasmids(search_query)  # ✅ Using the sorted function now

    return render_template("index.html", plasmids=plasmids, search_query=search_query)

# 🔍 View Plasmid Details
@app.route("/plasmid/<string:plasmid_id>")
def plasmid_detail(plasmid_id):
    conn = psycopg2.connect(**DB_CONFIG)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM plasmids WHERE id = %s", (plasmid_id,))
    plasmid = cursor.fetchone()
    cursor.close()
    conn.close()

    if plasmid is None:
        return "Plasmid not found", 404

    dna_file = os.path.join(SNAPGENE_DIR, f"{plasmid_id}.dna")
    snapgene_sequence, snapgene_features = (plasmid[6].upper(), []) if not os.path.exists(dna_file) else extract_snapgene_features(dna_file)
    highlighted_sequence = highlight_snapgene_features(snapgene_sequence, snapgene_features)

    return render_template("plasmid_detail.html", plasmid=plasmid, highlighted_sequence=highlighted_sequence)

# ✅ Update Plasmid Stock Concentration & Preparation Date
@app.route("/update_plasmid/<string:plasmid_id>", methods=["POST"])
def update_plasmid(plasmid_id):
    new_concentration = request.form.get("new_concentration")
    new_prep_date = request.form.get("new_prep_date")

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE plasmids 
            SET stock_concentration = %s, preparation_date = %s, last_updated = NOW()
            WHERE id = %s
        """, (new_concentration, new_prep_date, plasmid_id))

        conn.commit()
        cursor.close()
        conn.close()

        print(f"✅ Updated Plasmid {plasmid_id}: {new_concentration} ng/µL, {new_prep_date}")
    
    except Exception as e:
        print(f"❌ Error updating plasmid: {e}")

    return redirect(url_for('plasmid_detail', plasmid_id=plasmid_id))

# 🚀 Run Flask App
if __name__ == "__main__":
    app.run(debug=True)
