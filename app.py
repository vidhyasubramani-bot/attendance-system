import os
from datetime import date
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file, jsonify
import pandas as pd
from  sqlalchemy import create_engine  # Excel Export-க்காக சேர்க்கப்பட்டுள்ளது
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors

# --- SARIYAANA POSTGRESQL DATABASE CONNECTION CONFIG ---
def get_connection():
    try:
        # Vercel-ல் உள்ள DATABASE_URL-ஐ எடுக்கும், லோக்கலில் டெஸ்ட் செய்ய fallback லிங்க் பயன்படுத்தும்.
        DATABASE_URL = os.environ.get(
            "DATABASE_URL", 
            "postgresql://postgres:password@localhost:5432/attendance_db"
        )
        # RealDictCursor பயன்படுத்துவதால் HTML கோடுகளில் எந்த மாற்றமும் தேவையில்லை!
        return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    except Exception as e:
        print("PostgreSQL Connection Failed:", e)
        return None

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "smart_attendance_secret")

app.debug = os.environ.get("FLASK_ENV") == "development"

# --- Percentage Calculation Logic ---
def calculate_percentage(student_id):
    conn = get_connection()
    if conn is None:
        return 0

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as total FROM attendance WHERE student_id=%s", (student_id,))
        total = cursor.fetchone()
        total_val = total["total"] if total else 0

        cursor.execute("SELECT COUNT(*) as present FROM attendance WHERE student_id=%s AND status='Present'", (student_id,))
        present = cursor.fetchone()
        present_val = present["present"] if present else 0
        
        if total_val == 0:
            return 0

        return round((present_val / total_val) * 100, 2)
    except Exception as e:
        print("Error calculating percentage:", e)
        return 0
    finally:
        cursor.close()
        conn.close()


# ==========================================================
# 📡 CORE API INTEGRATION PIPELINES (JSON DATA)
# ==========================================================

# 1. API to Fetch All Students
@app.route("/api/students", methods=["GET"])
def api_get_students():
    conn = get_connection()
    if conn is None:
        return jsonify({"status": "error", "message": "Database Connection Failed"}), 500
    
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, register_number, department, year, email, phone FROM students")
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({"status": "success", "total_records": len(data), "data": data})

# 2. API to Fetch Attendance Logs
@app.route("/api/attendance_logs", methods=["GET"])
def api_get_attendance():
    conn = get_connection()
    if conn is None:
        return jsonify({"status": "error", "message": "Database Connection Failed"}), 500
        
    cursor = conn.cursor()
    cursor.execute("""
        SELECT attendance.id, students.name, students.register_number, attendance.date, attendance.status 
        FROM attendance 
        JOIN students ON attendance.student_id = students.id
    """)
    data = cursor.fetchall()
    cursor.close()
    conn.close()
    
    for row in data:
        if 'date' in row and row['date']:
            row['date'] = str(row['date'])
            
    return jsonify({"status": "success", "total_logs": len(data), "data": data})


# ==========================================================
# 🎛️ CORE WEB PLATFORM GATEWAYS (WEB ROUTES)
# ==========================================================

@app.route("/")
def home():
    return render_template("index.html", date=date)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

# --- STUDENT LOGIN BACKEND ---
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        register_number = request.form["register_number"]
        password = request.form["password"]

        conn = get_connection()
        if conn is None:
            flash("Database Connection Failed!")
            return redirect(url_for("login"))
            
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE register_number=%s AND password=%s", (register_number, password))
        student = cursor.fetchone()
        cursor.close()
        conn.close()

        if student:
            session["student"] = register_number
            session["student_id"] = student["id"]  
            session["student_name"] = student["name"]
            session["student_dept"] = student.get("department", "CSE")
            session["student_year"] = student.get("year", "3rd Year")
            session["student_email"] = student.get("email", "student@college.edu")
            session["student_phone"] = student.get("phone", "+91 98765 43210")
            
            flash("Login Successful!")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid Register Number or Password!")
            return redirect(url_for("login"))

    return render_template("login.html")

# --- STUDENT DASHBOARD BACKEND ---
@app.route("/dashboard")
def dashboard():
    if "student" not in session:
        return redirect(url_for("login"))

    student_id = session.get("student_id")
    conn = get_connection()
    if conn is None:
        flash("Database connection failed!")
        return redirect(url_for("login"))
        
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM students")
    total_students = cursor.fetchone()["count"]

    today = date.today()
    cursor.execute("SELECT COUNT(*) as count FROM attendance WHERE status='Present' AND date=%s", (today,))
    present = cursor.fetchone()["count"]

    cursor.execute("SELECT COUNT(*) as count FROM attendance WHERE status='Absent' AND date=%s", (today,))
    absent = cursor.fetchone()["count"]

    cursor.execute("""
        SELECT date, 'Regular Class' as subject, status 
        FROM attendance 
        WHERE student_id=%s 
        ORDER BY date DESC LIMIT 5
    """, (student_id,))
    attendance_records = cursor.fetchall()
    
    for row in attendance_records:
        row['date'] = str(row['date'])

    cursor.close()
    conn.close()
    
    attendance_percentage = f"{calculate_percentage(student_id)}%"

    return render_template(
        "dashboard.html",
        total_students=total_students,
        present=present,
        absent=absent,
        attendance_percentage=attendance_percentage,
        attendance_records=attendance_records
    )

# --- STUDENT MARK ATTENDANCE ---
@app.route("/mark_attendance", methods=["GET", "POST"])
def mark_attendance():
    if "student" not in session:
        flash("Please login first!")
        return redirect(url_for("login"))
        
    if request.method == "POST":
        student_id = session.get("student_id")
        today = date.today()
        
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM attendance WHERE student_id=%s AND date=%s", (student_id, today))
        already_marked = cursor.fetchone()
        
        if already_marked:
            cursor.close()
            conn.close()
            flash("Attendance already marked for today!")
            return redirect(url_for("dashboard"))
            
        cursor.execute("INSERT INTO attendance (student_id, date, status) VALUES (%s, %s, 'Present')", (student_id, today))
        conn.commit()
        cursor.close()
        conn.close()
        
        flash("Attendance Marked Successfully for Today!")
        return redirect(url_for("dashboard"))
        
    return render_template("mark_attendance.html")

# --- STUDENT ATTENDANCE HISTORY LOGS ---
@app.route("/my_attendance")
def my_attendance():
    if "student" not in session:
        flash("Please login first!")
        return redirect(url_for("login"))
    
    student_id = session.get("student_id")
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT date, 'Regular Class' as subject, status 
        FROM attendance 
        WHERE student_id=%s 
        ORDER BY date DESC
    """, (student_id,))
    history = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template("my_attendance.html", history=history)

# --- STUDENT USER PROFILE ACCOUNT ---
@app.route("/profile")
def profile():
    if "student" not in session:
        flash("Please login first!")
        return redirect(url_for("login"))
        
    user_data = {
        "name": session.get("student_name", "Student"),
        "register_number": session.get("student"),
        "department": session.get("student_dept", "CSE"),
        "year": session.get("student_year", "3rd Year"),
        "email": session.get("student_email", "student@college.edu"),
        "phone": session.get("student_phone", "+91 98765 43210")
    }
    return render_template("profile.html", user=user_data)

# --- LOGOUT SECURE ---
@app.route("/logout")
def logout():
    session.clear() 
    flash("You have been logged out successfully.")
    return redirect(url_for("login"))

# --- ADMIN LOGIN CONTROL SYSTEM ---
@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == "admin" and password == "admin123":
            session["admin"] = "root_admin"
            flash("Welcome back, Chief Administrator!")
            return redirect(url_for("admin_dashboard")) 
        else:
            flash("Invalid Admin Credentials! Please Try Again.")
            return redirect(url_for("admin_login"))

    return render_template("admin_login.html")

# --- ADMIN DASHBOARD ---
@app.route("/admin_dashboard")
def admin_dashboard():
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) as total_students FROM students")
    students_result = cursor.fetchone()
    ts_val = students_result["total_students"] if students_result else 0

    cursor.execute("SELECT COUNT(*) as total_att FROM attendance")
    attendance_result = cursor.fetchone()
    ta_val = attendance_result["total_att"] if attendance_result else 0
    
    cursor.close()
    conn.close()

    return render_template(
        "admin_dashboard.html",
        total_students=ts_val,
        total_attendance=ta_val
    )

# --- ADMIN BLOCK: EXCEL & PDF REPORTS GENERATOR ---
@app.route("/download_pdf")
def download_pdf():
    if "admin" not in session and "student" not in session:
        return redirect(url_for("login"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT students.id, students.name, attendance.date, attendance.status
        FROM attendance
        JOIN students ON attendance.student_id = students.id
        ORDER BY attendance.date DESC
    """)
    data = cursor.fetchall()
    cursor.close()
    conn.close()

    file_path = "/tmp/attendance_report.pdf"  
    pdf = SimpleDocTemplate(file_path, pagesize=letter)
    table_data = [["Student ID", "Name", "Date", "Status"]]

    for row in data:
        table_data.append([row['id'], row['name'], str(row['date']), row['status']])

    table = Table(table_data)
    style = TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("BACKGROUND", (0, 1), (-1, -1), colors.beige),
    ])
    table.setStyle(style)
    pdf.build([table])

    return send_file(file_path, as_attachment=True)

@app.route("/export_excel")
def export_excel():
    # PostgreSQL-ல் pandas sql இன்டகிரேஷனுக்கு SQLAlchemy அத்தியாவசியம்
    db_url = os.environ.get("DATABASE_URL", "postgresql://postgres:password@localhost:5432/attendance_db")
    engine = create_engine(db_url)
    
    query = """
    SELECT students.name, students.register_number, attendance.date, attendance.status
    FROM attendance
    JOIN students ON students.id = attendance.student_id
    """
    df = pd.read_sql(query, engine)
    file_name = "/tmp/attendance_report.xlsx"  
    df.to_excel(file_name, index=False)

    return send_file(file_name, as_attachment=True)

@app.route("/attendance")
def attendance():
    if "student" not in session:
        return redirect(url_for("login"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, register_number FROM students")
    students_list = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template("attendance.html", students=students_list)

@app.route("/students")
def students():
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    search_query = request.args.get("search", "").strip()
    conn = get_connection()
    cursor = conn.cursor()

    if search_query:
        # PostgreSQL-ல் 'ILIKE' பயன்படுத்தி அசால்ட்டாக தேடலாம்
        query = "SELECT * FROM students WHERE name ILIKE %s OR email ILIKE %s"
        cursor.execute(query, (f"%{search_query}%", f"%{search_query}%"))
    else:
        cursor.execute("SELECT * FROM students ORDER BY id ASC")
    
    students_data = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template("students.html", students=students_data, search_query=search_query)

@app.route("/student_dashboard")
def student_dashboard():
    if "student_id" not in session and "user_id" not in session:
        return redirect(url_for("login"))

    student_id = session.get("student_id") or session.get("user_id")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM students WHERE id = %s", (student_id,))
    current_student = cursor.fetchone()

    cursor.execute("SELECT * FROM attendance WHERE student_id = %s ORDER BY date DESC", (student_id,))
    attendance_history = cursor.fetchall()

    cursor.close()
    conn.close()

    if not current_student:
        session.clear()
        return redirect(url_for("login"))

    return render_template(
        "student_dashboard.html", 
        student=current_student, 
        attendance_list=attendance_history
    )

@app.route("/delete_student/<int:id>")
def delete_student(id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM attendance WHERE student_id=%s", (id,))
    cursor.execute("DELETE FROM students WHERE id=%s", (id,))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("students"))

@app.route("/present/<int:id>")
def present(id):
    today = date.today()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO attendance (student_id, date, status) VALUES(%s,%s,%s)", (id, today, "Present"))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("attendance"))

@app.route("/edit_student/<int:id>", methods=["GET","POST"])
def edit_student(id):
    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        cursor.execute("UPDATE students SET name=%s, email=%s WHERE id=%s", (name, email, id))
        conn.commit()
        cursor.close()
        conn.close()
        return redirect(url_for("students"))

    cursor.execute("SELECT * FROM students WHERE id=%s", (id,))
    student = cursor.fetchone()
    cursor.close()
    conn.close()

    return render_template("edit_student.html", student=student)

@app.route("/reports")
def reports():
    if "student" not in session and "admin" not in session:
        return redirect(url_for("login"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT students.name, students.register_number, attendance.date, attendance.status
        FROM attendance
        JOIN students ON students.id = attendance.student_id
        ORDER BY attendance.date DESC
    """)
    reports_list = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template("reports.html", reports=reports_list)   

@app.route("/absent/<int:id>")
def absent(id):
    today = date.today()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO attendance (student_id, date, status) VALUES(%s,%s,%s)", (id, today, "Absent"))
    conn.commit()
    cursor.close()
    conn.close()

    return redirect(url_for("attendance"))

# --- STUDENT REGISTRATION ---
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"]
        reg_no = request.form["register_number"]
        department = request.form["department"]
        year = request.form["year"]
        email = request.form["email"]
        phone = request.form["phone"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            flash("Passwords do not match!")
            return redirect(url_for('register'))

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE register_number=%s", (reg_no,))
        existing = cursor.fetchone()

        if existing:
            cursor.close()
            conn.close()
            flash("Register Number Already Exists!")
            return redirect(url_for('register'))

        cursor.execute("""
            INSERT INTO students (name, register_number, department, year, email, phone, password)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (name, reg_no, department, year, email, phone, password))
        conn.commit()
        cursor.close()
        conn.close()

        flash("Registration Successful! Please Login.")
        return redirect(url_for('login'))

    return render_template("register.html")

# --- TEACHER REGISTRATION BACKEND ---
@app.route("/teacher_register", methods=["GET", "POST"])
def teacher_register():
    if request.method == "POST":
        name = request.form["name"]
        emp_id = request.form["employee_id"]
        department = request.form["department"]
        email = request.form["email"]
        password = request.form["password"]

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teachers WHERE employee_id=%s", (emp_id,))
        existing = cursor.fetchone()

        if existing:
            cursor.close()
            conn.close()
            flash("Employee ID Already Registered!")
            return redirect(url_for('teacher_register'))

        cursor.execute("""
            INSERT INTO teachers (name, employee_id, department, email, password)
            VALUES (%s,%s,%s,%s,%s)
        """, (name, emp_id, department, email, password))
        conn.commit()
        cursor.close()
        conn.close()

        flash("Teacher Registration Successful! Please Login.")
        return redirect(url_for('teacher_login'))

    return render_template("teacher_register.html")

# --- TEACHER LOGIN BACKEND ---
@app.route("/teacher_login", methods=["GET", "POST"])
def teacher_login():
    if request.method == "POST":
        emp_id = request.form["employee_id"]
        password = request.form["password"]

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM teachers WHERE employee_id=%s AND password=%s", (emp_id, password))
        teacher = cursor.fetchone()
        cursor.close()
        conn.close()

        if teacher:
            session["teacher"] = emp_id
            session["teacher_name"] = teacher["name"]
            session["teacher_dept"] = teacher["department"]
            return redirect(url_for("teacher_dashboard"))
        else:
            flash("Invalid Employee ID or Password!")
            return redirect(url_for("teacher_login"))

    return render_template("teacher_login.html")

# --- TEACHER DASHBOARD WINDOW ---
@app.route("/teacher_dashboard")
def teacher_dashboard():
    if "teacher" not in session:
        return redirect(url_for("teacher_login"))

    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, name, register_number, department FROM students WHERE department=%s", (session["teacher_dept"],))
    students_list = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template("teacher_dashboard.html", students=students_list, date=date)

# --- TEACHER SUBMIT BULK ATTENDANCE ACTION ---
@app.route("/teacher_submit_attendance", methods=["POST"])
def teacher_submit_attendance():
    if "teacher" not in session:
        return redirect(url_for("teacher_login"))
        
    today = date.today()
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id FROM students WHERE department=%s", (session["teacher_dept"],))
    students_list = cursor.fetchall()
    
    for row in students_list:
        student_id = row['id']
        status_key = f"status_{student_id}"
        status_value = request.form.get(status_key, "Absent") 
        
        cursor.execute("SELECT id FROM attendance WHERE student_id=%s AND date=%s", (student_id, today))
        exists = cursor.fetchone()
        
        if exists:
            cursor.execute("UPDATE attendance SET status=%s WHERE student_id=%s AND date=%s", (status_value, student_id, today))
        else:
            cursor.execute("INSERT INTO attendance (student_id, date, status) VALUES (%s, %s, %s)", (student_id, today, status_value))
            
    conn.commit()
    cursor.close()
    conn.close()
    
    flash("Bulk Class Attendance Manifested Successfully for Today!")
    return redirect(url_for("teacher_dashboard"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))