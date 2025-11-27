import streamlit as st
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import io, os, random
import qrcode
from PIL import Image
import hashlib, smtplib
from email.message import EmailMessage
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from st_aggrid import AgGrid, GridOptionsBuilder, GridUpdateMode

# ---------- CONFIG ----------
DB_FILE = 'data/membership_erp.db'
DEFAULT_ADMIN_EMAIL = 'admin@local'
DEFAULT_ADMIN_PASSWORD = 'admin123'

# ---------- DATABASE ----------
def get_conn():
    os.makedirs('data', exist_ok=True)
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # USERS
    cur.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        name TEXT,
        password_hash TEXT,
        role TEXT
    )''')
    # MEMBERS
    cur.execute('''CREATE TABLE IF NOT EXISTS members (
        member_id INTEGER PRIMARY KEY AUTOINCREMENT,
        membership_no TEXT UNIQUE,
        parent_name TEXT,
        phone_number TEXT,
        child_name TEXT,
        child_dob TEXT,
        member_since TEXT
    )''')
    # PLANS
    cur.execute('''CREATE TABLE IF NOT EXISTS plans (
        plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_type TEXT,
        entitled_visits INTEGER,
        per_visit_hours INTEGER,
        price REAL,
        validity_days INTEGER
    )''')
    # MEMBER_PLAN
    cur.execute('''CREATE TABLE IF NOT EXISTS member_plan (
        mp_id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER,
        plan_id INTEGER,
        start_date TEXT,
        end_date TEXT,
        visits_used INTEGER DEFAULT 0,
        FOREIGN KEY(member_id) REFERENCES members(member_id),
        FOREIGN KEY(plan_id) REFERENCES plans(plan_id)
    )''')
    # VISITS
    cur.execute('''CREATE TABLE IF NOT EXISTS visits (
        visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER,
        visit_date TEXT,
        hours_used INTEGER,
        notes TEXT,
        FOREIGN KEY(member_id) REFERENCES members(member_id)
    )''')
    # SETTINGS
    cur.execute('''CREATE TABLE IF NOT EXISTS settings (
        k TEXT PRIMARY KEY,
        v TEXT
    )''')
    conn.commit()
    cur.execute('SELECT COUNT(*) FROM users')
    if cur.fetchone()[0]==0:
        add_user(DEFAULT_ADMIN_EMAIL, 'Administrator', DEFAULT_ADMIN_PASSWORD, role='admin')
    conn.close()

# ---------- PASSWORD ----------
def hash_password(password: str) -> str:
    salt = 'streamlit_salt_v1'
    return hashlib.sha256((salt + password).encode()).hexdigest()

def add_user(email, name, password, role='staff'):
    conn = get_conn()
    cur = conn.cursor()
    pwd_hash = hash_password(password)
    try:
        cur.execute('INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)', (email, name, pwd_hash, role))
        conn.commit()
    except:
        pass
    conn.close()

def verify_user(email, password):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT password_hash, role, name FROM users WHERE email=?', (email,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False, None, None
    stored_hash, role, name = row
    return (stored_hash == hash_password(password), role, name)

# ---------- MEMBER FUNCTIONS ----------
def generate_membership_no(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM members")
    count = cur.fetchone()[0] or 0
    return f"ZPHSI-{count+1:04d}"

def add_member(parent_name, phone, child_name, child_dob):
    conn = get_conn()
    cur = conn.cursor()
    membership_no = generate_membership_no(conn)
    member_since = datetime.now().date().isoformat()
    cur.execute('''INSERT INTO members (membership_no, parent_name, phone_number, child_name, child_dob, member_since)
                   VALUES (?, ?, ?, ?, ?, ?)''', (membership_no, parent_name, phone, child_name, child_dob, member_since))
    conn.commit()
    conn.close()
    return membership_no

def update_member(member_id, parent_name, phone, child_name, child_dob):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''UPDATE members SET parent_name=?, phone_number=?, child_name=?, child_dob=? WHERE member_id=?''',
                (parent_name, phone, child_name, child_dob, member_id))
    conn.commit()
    conn.close()

def delete_member(member_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('DELETE FROM members WHERE member_id=?', (member_id,))
    conn.commit()
    conn.close()

# ---------- PLAN FUNCTIONS ----------
def add_plan(plan_type, entitled_visits, per_visit_hours, price, validity_days):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''INSERT INTO plans (plan_type, entitled_visits, per_visit_hours, price, validity_days)
                   VALUES (?, ?, ?, ?, ?)''', (plan_type, entitled_visits, per_visit_hours, price, validity_days))
    conn.commit()
    conn.close()

def assign_plan_to_member(member_id, plan_id, start_date=None):
    conn = get_conn()
    cur = conn.cursor()
    if start_date is None:
        start_date = datetime.now().date()
    else:
        start_date = datetime.fromisoformat(start_date).date()
    cur.execute('SELECT validity_days FROM plans WHERE plan_id=?', (plan_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return
    validity_days = row[0]
    end_date = start_date + timedelta(days=validity_days)
    cur.execute('''INSERT INTO member_plan (member_id, plan_id, start_date, end_date)
                   VALUES (?, ?, ?, ?)''', (member_id, plan_id, start_date.isoformat(), end_date.isoformat()))
    conn.commit()
    conn.close()

def record_visit(member_id, hours_used=1, notes=''):
    conn = get_conn()
    cur = conn.cursor()
    visit_date = datetime.now().isoformat()
    cur.execute('''INSERT INTO visits (member_id, visit_date, hours_used, notes)
                   VALUES (?, ?, ?, ?)''', (member_id, visit_date, hours_used, notes))
    conn.commit()
    conn.close()

# ---------- QUERIES ----------
def get_members_df():
    conn = get_conn()
    df = pd.read_sql_query('SELECT * FROM members', conn)
    conn.close()
    return df

def get_plans_df():
    conn = get_conn()
    df = pd.read_sql_query('SELECT * FROM plans', conn)
    conn.close()
    return df

def get_member_by_membership_no(membership_no):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM members WHERE membership_no=?', (membership_no,))
    row = cur.fetchone()
    conn.close()
    return row

# ---------- QR CODE ----------
def generate_qr_image(membership_no):
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(membership_no)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return img

# ---------- STREAMLIT UI ----------
init_db()
st.set_page_config(page_title='Membership ERP', layout='wide')
st.title("Membership ERP - Full Version")

# Login
if 'user' not in st.session_state:
    st.session_state.user = None

if st.session_state.user:
    st.sidebar.markdown(f"Logged in as: **{st.session_state.user['name']}**")
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.experimental_rerun()
else:
    st.subheader("Login")
    email = st.text_input("Email")
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        ok, role, name = verify_user(email, pwd)
        if ok:
            st.session_state.user = {'email': email, 'role': role, 'name': name}
            st.experimental_rerun()
        else:
            st.error("Invalid credentials")
    st.stop()

tabs = st.tabs(["Members","Plans","Assign Plan","Record Visit","Export/Reports"])

# ----------------- MEMBERS TAB -----------------
with tabs[0]:
    st.subheader("Add Member")
    with st.form("add_member_form"):
        parent = st.text_input("Parent Name")
        phone = st.text_input("Phone Number")
        child = st.text_input("Child Name")
        dob = st.date_input("Child DOB")
        submitted = st.form_submit_button("Add Member")
        if submitted:
            membership_no = add_member(parent, phone, child, dob.isoformat())
            st.success(f"Added member {child} (Membership No: {membership_no})")

    st.subheader("Existing Members")
    df = get_members_df()
    if not df.empty:
        gb = GridOptionsBuilder.from_dataframe(df)
        gb.configure_selection('single')
        grid = AgGrid(df, gb.build(), height=300, update_mode=GridUpdateMode.MODEL_CHANGED)
        sel = grid['selected_rows']
        if sel:
            sel = sel[0]
            st.write("Edit Member:")
            with st.form("edit_form"):
                parent2 = st.text_input("Parent Name", sel['parent_name'])
                phone2 = st.text_input("Phone", sel['phone_number'])
                child2 = st.text_input("Child Name", sel['child_name'])
                dob2 = st.date_input("Child DOB", datetime.strptime(sel['child_dob'], '%Y-%m-%d').date())
                if st.form_submit_button("Update Member"):
                    update_member(sel['member_id'], parent2, phone2, child2, dob2.isoformat())
                    st.success("Member updated")
                    st.experimental_rerun()
            if st.button("Delete Member"):
                delete_member(sel['member_id'])
                st.warning("Member deleted")
                st.experimental_rerun()

# ----------------- PLANS TAB -----------------
with tabs[1]:
    st.subheader("Add Plan")
    with st.form("add_plan_form"):
        plan_type = st.text_input("Plan Type")
        visits = st.number_input("Entitled Visits", min_value=1, value=10)
        hours = st.number_input("Hours per visit", min_value=1, value=1)
        price = st.number_input("Price", min_value=0.0, value=1000.0)
        validity = st.number_input("Validity Days", min_value=1, value=30)
        if st.form_submit_button("Add Plan"):
            add_plan(plan_type, visits, hours, price, validity)
            st.success("Plan added")
    st.subheader("Existing Plans")
    st.dataframe(get_plans_df())

# ----------------- ASSIGN PLAN TAB -----------------
with tabs[2]:
    st.subheader("Assign Plan to Member")
    members_df = get_members_df()
    plans_df = get_plans_df()
    if not members_df.empty and not plans_df.empty:
        mem = st.selectbox("Select Member", members_df['membership_no'])
        plan = st.selectbox("Select Plan", plans_df['plan_type'] + " (ID:" + plans_df['plan_id'].astype(str) + ")")
        start_date = st.date_input("Start Date", datetime.now().date())
        if st.button("Assign Plan"):
            member_row = members_df[members_df['membership_no']==mem].iloc[0]
            plan_id = int(plan.split("ID:")[1].replace(")",""))
            assign_plan_to_member(member_row['member_id'], plan_id, start_date.isoformat())
            st.success("Plan assigned")

# ----------------- RECORD VISIT TAB -----------------
with tabs[3]:
    st.subheader("Record Visit")
    members_df = get_members_df()
    if not members_df.empty:
        mem = st.selectbox("Select Member for Visit", members_df['membership_no'])
        hours_used = st.number_input("Hours Used", min_value=1, value=1)
        notes = st.text_input("Notes")
        if st.button("Record Visit"):
            member_row = members_df[members_df['membership_no']==mem].iloc[0]
            record_visit(member_row['member_id'], hours_used, notes)
            st.success("Visit recorded")

# ----------------- EXPORT/REPORTS TAB -----------------
with tabs[4]:
    st.subheader("Export Data")
    if st.button("Export all to Excel"):
        conn = get_conn()
        members = pd.read_sql_query("SELECT * FROM members", conn)
        plans = pd.read_sql_query("SELECT * FROM plans", conn)
        member_plan = pd.read_sql_query("SELECT * FROM member_plan", conn)
        visits = pd.read_sql_query("SELECT * FROM visits", conn)
        conn.close()
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer) as writer:
                members.to_excel(writer, sheet_name='members', index=False)
                plans.to_excel(writer, sheet_name='plans', index=False)
                member_plan.to_excel(writer, sheet_name='member_plan', index=False)
                visits.to_excel(writer, sheet_name='visits', index=False)
            st.download_button("Download Excel", buffer.getvalue(), "membership_data.xlsx")
