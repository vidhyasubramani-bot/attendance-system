
import pymysql
from flask import Flask, render_template, request, redirect, session, url_for, flash, send_file, jsonify
from datetime import date
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
import os

# --- FIXED: Added DictCursor as default connection mapping ---
# --- SARIYAANA DATABASE CONNECTION CONFIG ---
def get_connection():
    return pymysql.connect(
        host="localhost",
        user="root",
        password="Vidhya@2007",
        database="attendance",  # <-- 'attendance_db'க்கு பதிலா 'attendance'னு மாத்துங்க!
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor
    )
    

app = Flask(__name__)
app.secret_key = "smart_attendance_secret"

def calculate_percentage(student_id):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM attendance WHERE student_id=%s", (student_id,))
    total = cursor.fetchone()
    total_val = total["COUNT(*)"] if isinstance(total, dict) else total[0]

    cursor.execute("SELECT COUNT(*) FROM attendance WHERE student_id=%s AND status='Present'", (student_id,))
    present = cursor.fetchone()
    present_val = present["COUNT(*)"] if isinstance(present, dict) else present[0]

    conn.close()
    if total_val == 0:
        return 0

    return round((present_val / total_val) * 100, 2)


# ==========================================================
# 📡 NEW FEATURE: CORE API INTEGRATION PIPELINES (JSON DATA)
# ==========================================================

# 1. API to Fetch All Students
@app.route("/api/students", methods=["GET"])
def api_get_students():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, register_number, department, year, email, phone FROM students")
    data = cursor.fetchall()
    conn.close()
    return jsonify({"status": "success", "total_records": len(data), "data": data})

# 2. API to Fetch Attendance Logs
@app.route("/api/attendance_logs", methods=["GET"])
def api_get_attendance():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT attendance.id, students.name, students.register_number, attendance.date, attendance.status 
        FROM attendance 
        JOIN students ON attendance.student_id = students.id
    """)
    data = cursor.fetchall()
    conn.close()
    
    # Python date objects cannot be serialized directly to JSON, string-ah convert panrom
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
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM students WHERE register_number=%s AND password=%s", (register_number, password))
        student = cursor.fetchone()
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
            conn.close()
            flash("Attendance already marked for today!")
            return redirect(url_for("dashboard"))
            
        cursor.execute("INSERT INTO attendance (student_id, date, status) VALUES (%s, %s, 'Present')", (student_id, today))
        conn.commit()
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

# --- FIXED ADMIN LOGIN CONTROL SYSTEM ---
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
# --- ADMIN DASHBOARD (FIXED KEYERROR) ---
@app.route("/admin_dashboard")
def admin_dashboard():
    if "admin" not in session:
        return redirect(url_for("admin_login"))

    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. 'as total_students' என்று மாற்றுவதால் Key பெயர் 'total_students' என்று தெளிவாகும்
    cursor.execute("SELECT COUNT(*) as total_students FROM students")
    students_result = cursor.fetchone()
    ts_val = students_result["total_students"] if isinstance(students_result, dict) else students_result[0]

    # 2. 'as total_att' என்று மாற்றுவதால் Key பெயர் 'total_att' என்று தெளிவாகும்
    cursor.execute("SELECT COUNT(*) as total_att FROM attendance")
    attendance_result = cursor.fetchone()
    ta_val = attendance_result["total_att"] if isinstance(attendance_result, dict) else attendance_result[0]
    
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
    conn.close()

    file_path = "attendance_report.pdf"
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
    conn = get_connection()
    query = """
    SELECT students.name, students.register_number, attendance.date, attendance.status
    FROM attendance
    JOIN students ON students.id = attendance.student_id
    """
    df = pd.read_sql(query, conn)
    file_name = "attendance_report.xlsx"
    df.to_excel(file_name, index=False)
    conn.close()

    return send_file(file_name, as_attachment=True)

@app.route("/attendance")
def attendance():
    if "student" not in session:
        return redirect(url_for("login"))

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, register_number FROM students")
    students_list = cursor.fetchall()
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
        query = "SELECT * FROM students WHERE name LIKE %s OR email LIKE %s"
        cursor.execute(query, (f"%{search_query}%", f"%{search_query}%"))
    else:
        cursor.execute("SELECT * FROM students")
    
    students_data = cursor.fetchall()
    cursor.close()
    conn.close()

    # இங்கதான் ட்ரிக் இருக்கு! 'students' என்ற பெயரிலேயே 
    # டேட்டாவை HTML-க்கு அப்படியே பாஸ் பண்றோம்.
    return render_template("students.html", students=students_data, search_query=search_query)
@app.route("/student_dashboard")
def student_dashboard():
    if "student_id" not in session and "user_id" not in session:
        return redirect(url_for("login"))

    student_id = session.get("student_id") or session.get("user_id")

    conn = get_connection()
    cursor = conn.cursor()

    # 1. மாணவர் விபரங்களை எடுக்கிறோம்
    cursor.execute("SELECT * FROM students WHERE id = %s", (student_id,))
    current_student = cursor.fetchone()

    # 2. அட்டெண்டன்ஸ் விபரங்களை எடுக்கிறோம்
    cursor.execute("SELECT * FROM attendance WHERE student_id = %s ORDER BY date DESC", (student_id,))
    attendance_history = cursor.fetchall()

    cursor.close()
    conn.close()

    if not current_student:
        session.clear()
        return redirect(url_for("login"))

    # 🔥 [SAFETY TRICK]: தரவு Tuple-ஆக இருந்தால், அதை நாம் கைமுறையாக Dictionary-ஆக மாற்றுகிறோம்
    if isinstance(current_student, (tuple, list)):
        # உங்க டேபிள் ஸ்ட்ரக்சர் படி: id, name, email, phone, department, year, password...
        # ஒருவேளை ஆர்டர் மாறினால், உங்க டேட்டாபேஸ் ஆர்டருக்கு ஏற்ப மாற்றி அமைத்துக் கொள்ளவும்
        current_student = {
            "id": current_student[0],
            "name": current_student[1],
            "email": current_student[2],
            "phone": current_student[3] if len(current_student) > 3 else "N/A",
            "department": current_student[4] if len(current_student) > 4 else "N/A"
        }

    # இப்போது HTML-க்கு அனுப்புகிறோம்
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
    conn.close()

    return redirect(url_for("students"))

@app.route("/present/<int:id>")
def present(id):
    today = date.today()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO attendance (student_id, date, status) VALUES(%s,%s,%s)", (id, today, "Present"))
    conn.commit()
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
        conn.close()
        return redirect(url_for("students"))

    cursor.execute("SELECT * FROM students WHERE id=%s", (id,))
    student = cursor.fetchone()
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
    conn.close()

    return render_template("reports.html", reports=reports_list)   

@app.route("/absent/<int:id>")
def absent(id):
    today = date.today()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO attendance (student_id, date, status) VALUES(%s,%s,%s)", (id, today, "Absent"))
    conn.commit()
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
            conn.close()
            flash("Register Number Already Exists!")
            return redirect(url_for('register'))

        cursor.execute("""
            INSERT INTO students (name, register_number, department, year, email, phone, password)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
        """, (name, reg_no, department, year, email, phone, password))
        conn.commit()
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
            conn.close()
            flash("Employee ID Already Registered!")
            return redirect(url_for('teacher_register'))

        cursor.execute("""
            INSERT INTO teachers (name, employee_id, department, email, password)
            VALUES (%s,%s,%s,%s,%s)
        """, (name, emp_id, department, email, password))
        conn.commit()
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
        student_id = row['id']  # Correct Dict Reference
        status_key = f"status_{student_id}"
        status_value = request.form.get(status_key, "Absent") 
        
        cursor.execute("SELECT id FROM attendance WHERE student_id=%s AND date=%s", (student_id, today))
        exists = cursor.fetchone()
        
        if exists:
            cursor.execute("UPDATE attendance SET status=%s WHERE student_id=%s AND date=%s", (status_value, student_id, today))
        else:
            cursor.execute("INSERT INTO attendance (student_id, date, status) VALUES (%s, %s, %s)", (status_value, student_id, today))
            
    conn.commit()
    conn.close()
    
    flash("Bulk Class Attendance Manifested Successfully for Today!")
    return redirect(url_for("teacher_dashboard"))

if __name__ == "__main__":
    app.run(debug=True)