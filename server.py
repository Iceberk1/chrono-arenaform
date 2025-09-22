from flask import Flask, render_template, request, jsonify, redirect, url_for, send_file
import sqlite3
import re
from openpyxl import Workbook
import io
import pandas as pd
from datetime import datetime

app = Flask(__name__)
DB_FILE = 'chrono_event.db'

# --- Database setup ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL;")
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number INTEGER UNIQUE,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            phone TEXT,
            UNIQUE(first_name, last_name)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_number INTEGER,
            circuit INTEGER,
            time REAL,
            touches INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT (DATE('now')),
            UNIQUE(candidate_number, circuit, created_at)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- Routes ---
@app.route('/')
def index():
    return redirect(url_for('chrono'))

@app.route('/add_candidate', methods=['GET','POST'])
def add_candidate():
    if request.method == 'POST':
        data = request.get_json()
        email_pattern = r'^\S+@\S+\.\S+$'
        phone_pattern = r'^\d{10}$'
        if not re.match(email_pattern, data['email']):
            return jsonify(success=False, error='Email mal formaté')
        if not re.match(phone_pattern, data['phone']):
            return jsonify(success=False, error='Téléphone mal formaté')
        conn = sqlite3.connect(DB_FILE)
        conn.execute("PRAGMA journal_mode=WAL;")
        c = conn.cursor()
        c.execute('SELECT COUNT(*) FROM candidates WHERE first_name=? AND last_name=?',
                  (data['first_name'], data['last_name']))
        if c.fetchone()[0] > 0:
            conn.close()
            return jsonify(success=False, error='Candidat déjà existant')
        c.execute('SELECT COALESCE(MAX(number),0)+1 FROM candidates')
        next_number = c.fetchone()[0]
        c.execute('INSERT INTO candidates (number, first_name, last_name, email, phone) VALUES (?,?,?,?,?)',
                  (next_number, data['first_name'], data['last_name'], data['email'], data['phone']))
        conn.commit()
        conn.close()
        return jsonify(success=True, number=next_number)
    return render_template("add_candidates.html")

@app.route('/chrono')
def chrono():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL;")
    c = conn.cursor()
    c.execute('SELECT number, first_name, last_name FROM candidates ORDER BY number')
    candidates = c.fetchall()
    conn.close()
    return render_template("chrono.html", candidates=candidates)

@app.route('/save_time', methods=['POST'])
def save_time():
    data = request.json
    number = data['number']
    circuit = int(data['circuit'])
    time = float(data['time'])
    touches = int(data.get('touches', 0))

    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL;")
    c = conn.cursor()
    c.execute('''
        INSERT OR REPLACE INTO results (candidate_number, circuit, time, touches)
        VALUES (?, ?, ?, ?)
    ''', (number, circuit, time, touches))
    conn.commit()
    conn.close()
    return jsonify(success=True)

@app.route('/results')
def results():
    
    
    # DATE DU JOUR
    date_str = request.args.get('date')

    if date_str:
        try:
            # Convertir la chaîne en date (sans l'heure)
            selected_date = datetime.strptime(date_str, "%d/%m/%Y").date()
        except ValueError:
            # Format invalide, utiliser la date du jour
            selected_date = datetime.now().date()
    else:
        # Si aucune date fournie, utiliser la date du jour
        selected_date = datetime.now().date()
    # Affichage pour results
    display_date = selected_date.strftime("%d/%m/%Y")
    
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL;")

    c = conn.cursor()
    results_dict = {}

    # Récupérer toutes les dates uniques présentes dans la table results
    c.execute("SELECT DISTINCT DATE(created_at) FROM results ORDER BY DATE(created_at) DESC")
    available_dates = [row[0] for row in c.fetchall()]

    for circuit in range(1, 5):
        if circuit == 3:
            # Circuit 3 : touches réussies puis temps
            c.execute('''
                SELECT r.candidate_number, c.last_name, c.first_name,
                       printf("%02d:%02d.%02d", r.time/60, r.time%60, (r.time*100)%100),
                       r.touches
                FROM results r
                JOIN candidates c ON r.candidate_number = c.number
                WHERE r.circuit = ?
                    AND DATE(r.created_at) = DATE('now', 'localtime')
                ORDER BY r.touches DESC, r.time ASC
            ''', (circuit,))
        elif circuit == 4:
            # Circuit 4 : celui qui reste le plus longtemps gagne (temps DESC)
            c.execute('''
                SELECT r.candidate_number, c.last_name, c.first_name,
                       printf("%02d:%02d.%02d", r.time/60, r.time%60, (r.time*100)%100)
                FROM results r
                JOIN candidates c ON r.candidate_number = c.number
                WHERE r.circuit = ?
                    AND DATE(r.created_at) = DATE('now', 'localtime')
                ORDER BY r.time DESC
            ''', (circuit,))
        else:
            # Circuits 1 et 2 : classement normal par temps
            c.execute('''
                SELECT r.candidate_number, c.last_name, c.first_name,
                       printf("%02d:%02d.%02d", r.time/60, r.time%60, (r.time*100)%100)
                FROM results r
                JOIN candidates c ON r.candidate_number = c.number
                WHERE r.circuit = ?
                    AND DATE(r.created_at) = DATE('now', 'localtime')
                ORDER BY r.time ASC
            ''', (circuit,))

        rows = c.fetchall()

        # Meilleurs 3
        best = rows[:3]

        # Derniers 5 en ordre d'insertion
        c.execute('''
            SELECT r.candidate_number, c.last_name, c.first_name,
                   printf("%02d:%02d.%02d", r.time/60, r.time%60, (r.time*100)%100)
                   {extra}
            FROM results r
            JOIN candidates c ON r.candidate_number = c.number
            WHERE r.circuit = ?
                AND DATE(r.created_at) = DATE('now', 'localtime')
            ORDER BY r.id DESC
            LIMIT 5
        '''.format(extra=', r.touches' if circuit==3 else ''), (circuit,))
        last = c.fetchall()

        # Liste des jours disponibles dans la base
        c.execute('SELECT DISTINCT DATE(created_at) as d FROM results ORDER BY d DESC')
        dates = [row[0] for row in c.fetchall()]

        results_dict[circuit] = {'best': best, 'last': last}

    conn.close()
    return render_template("results.html", results=results_dict, selected_date=selected_date, available_dates=available_dates, display_date=display_date)


@app.route('/export_excel')
def export_excel():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA journal_mode=WAL;")
    c = conn.cursor()

    # Créer le classeur Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Candidats"

    # En-têtes
    headers = ["Numéro", "Nom", "Prénom", "Email", "Téléphone",
               "Circuit 1", "Circuit 2", "Circuit 3 (temps)", "Circuit 3 (touches)", "Circuit 4"]
    ws.append(headers)

    # Récupérer tous les candidats
    c.execute("SELECT number, last_name, first_name, email, phone FROM candidates")
    candidates = c.fetchall()

    for cand in candidates:
        number = cand[0]
        row = list(cand)

        # Pour chaque circuit, récupérer le temps
        for circuit in range(1, 5):
            if circuit == 3:
                c.execute('''
                    SELECT time, touches
                    FROM results
                    WHERE candidate_number=? AND circuit=3
                ''', (number,))
                res = c.fetchone()
                if res:
                    time_str = f"{int(res[0]//60):02d}:{int(res[0]%60):02d}.{int(res[0]*100%100):02d}"
                    touches = res[1]
                else:
                    time_str = ""
                    touches = ""
                row.extend([time_str, touches])
            else:
                c.execute('''
                    SELECT time
                    FROM results
                    WHERE candidate_number=? AND circuit=?
                ''', (number, circuit))
                res = c.fetchone()
                if res:
                    time_str = f"{int(res[0]//60):02d}:{int(res[0]%60):02d}.{int(res[0]*100%100):02d}"
                else:
                    time_str = ""
                row.append(time_str)

        ws.append(row)

    conn.close()

    # Sauvegarder dans un flux mémoire et renvoyer le fichier
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(output,
                     download_name="candidats.xlsx",
                     as_attachment=True,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                     
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)