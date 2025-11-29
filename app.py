# Membership ERP Streamlit app
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

DB_FILE = 'data/membership_erp.db'
DEFAULT_ADMIN_EMAIL = 'admin@local'
DEFAULT_ADMIN_PASSWORD = 'admin123'

# ---------- Helpers ----------
def get_conn():
    os.makedirs('data', exist_ok=True)
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE, name TEXT, password_hash TEXT, role TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS members (member_id INTEGER PRIMARY KEY AUTOINCREMENT, membership_no TEXT UNIQUE, parent_name TEXT, phone_number TEXT, child_name TEXT, child_dob TEXT, member_since TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS plans (plan_id INTEGER PRIMARY KEY AUTOINCREMENT, plan_type TEXT, entitled_visits INTEGER, per_visit_hours INTEGER, price REAL, validity_days INTEGER)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS member_plan (mp_id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER, plan_id INTEGER, start_date TEXT, end_date TEXT, visits_used INTEGER DEFAULT 0, FOREIGN KEY(member_id) REFERENCES members(member_id), FOREIGN KEY(plan_id) REFERENCES plans(plan_id))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS visits (visit_id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER, visit_date TEXT, hours_used INTEGER, notes TEXT, FOREIGN KEY(member_id) REFERENCES members(member_id))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY, v TEXT)''')
    conn.commit()
    cur.execute('SELECT COUNT(*) FROM users')
    if cur.fetchone()[0] == 0:
        add_user(DEFAULT_ADMIN_EMAIL, 'Administrator', DEFAULT_ADMIN_PASSWORD, role='admin')
    conn.close()

import hashlib

def hash_password(password):
    salt = 'streamlit_salt_v1'
    return hashlib.sha256((salt + password).encode()).hexdigest()

# ---------- User functions ----------
def add_user(email, name, password, role='staff'):
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute('INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)', (email, name, hash_password(password), role))
        conn.commit()
    except Exception:
        pass
    conn.close()

def verify_user(email, password):
    conn = get_conn(); cur = conn.cursor()
    cur.execute('SELECT password_hash, role, name FROM users WHERE email=?', (email,))
    row = cur.fetchone(); conn.close()
    if not row: return False, None, None
    stored, role, name = row
    return stored == hash_password(password), role, name

# ---------- Membership functions ----------
def generate_membership_no():
    conn = get_conn(); cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM members')
    count = cur.fetchone()[0] or 0
    conn.close()
    return f'ZPHSI-{count+1:04d}'

def add_member(parent_name, phone, child_name, child_dob):
    conn = get_conn(); cur = conn.cursor()
    membership_no = generate_membership_no()
    member_since = datetime.now().date().isoformat()
    cur.execute('INSERT INTO members (membership_no, parent_name, phone_number, child_name, child_dob, member_since) VALUES (?,?,?,?,?,?)',
                (membership_no, parent_name, phone, child_name, child_dob, member_since))
    conn.commit(); conn.close()
    return membership_no

def update_member(member_id, parent_name, phone, child_name, child_dob):
    conn = get_conn(); cur = conn.cursor()
    cur.execute('UPDATE members SET parent_name=?, phone_number=?, child_name=?, child_dob=? WHERE member_id=?',
                (parent_name, phone, child_name, child_dob, member_id))
    conn.commit(); conn.close()

def delete_member(member_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute('DELETE FROM members WHERE member_id=?', (member_id,))
    conn.commit(); conn.close()

def get_members_df():
    conn = get_conn()
    df = pd.read_sql_query('SELECT * FROM members', conn)
    conn.close()
    # Ensure membership_no is string to preserve formatting in Excel
    if 'membership_no' in df.columns:
        df['membership_no'] = df['membership_no'].astype(str)
    return df

def get_member_by_id(member_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute('SELECT * FROM members WHERE member_id=?', (member_id,))
    row = cur.fetchone(); conn.close()
    return row

# ---------- Plans & Assignments ----------
def add_plan(plan_type, entitled_visits, per_visit_hours, price, validity_days):
    conn = get_conn(); cur = conn.cursor()
    cur.execute('INSERT INTO plans (plan_type, entitled_visits, per_visit_hours, price, validity_days) VALUES (?,?,?,?,?)',
                (plan_type, entitled_visits, per_visit_hours, price, validity_days))
    conn.commit(); conn.close()

def get_plans_df():
    conn = get_conn(); df = pd.read_sql_query('SELECT * FROM plans', conn); conn.close(); return df

def assign_plan_to_member(member_id, plan_id, start_date=None):
    conn = get_conn(); cur = conn.cursor()
    if start_date is None:
        start_date = datetime.now().date()
    else:
        start_date = datetime.fromisoformat(start_date).date()
    cur.execute('SELECT validity_days FROM plans WHERE plan_id=?', (plan_id,))
    row = cur.fetchone()
    if not row:
        conn.close(); return
    validity_days = row[0]
    end_date = start_date + timedelta(days=validity_days)
    cur.execute('INSERT INTO member_plan (member_id, plan_id, start_date, end_date, visits_used) VALUES (?,?,?,?,0)',
                (member_id, plan_id, start_date.isoformat(), end_date.isoformat()))
    conn.commit(); conn.close()

def get_member_plans_df():
    conn = get_conn()
    df = pd.read_sql_query('''SELECT mp.*, m.membership_no AS membership_no, p.plan_type AS plan_type, p.entitled_visits AS entitled_visits
                              FROM member_plan mp
                              JOIN members m ON mp.member_id = m.member_id
                              JOIN plans p ON mp.plan_id = p.plan_id
                              ORDER BY mp.mp_id DESC''', conn)
    conn.close()
    if 'membership_no' in df.columns: df['membership_no'] = df['membership_no'].astype(str)
    return df

# ---------- Visits and certificates ----------
def record_visit(member_id, hours_used=1, notes=''):
    conn = get_conn(); cur = conn.cursor()
    visit_date = datetime.now().isoformat()
    cur.execute('INSERT INTO visits (member_id, visit_date, hours_used, notes) VALUES (?,?,?,?)', (member_id, visit_date, hours_used, notes))
    # increment visits_used for active plan
    cur.execute('''SELECT mp.mp_id, mp.visits_used, p.entitled_visits, m.membership_no
                   FROM member_plan mp
                   JOIN plans p ON mp.plan_id = p.plan_id
                   JOIN members m ON mp.member_id = m.member_id
                   WHERE mp.member_id=? AND date(mp.end_date) >= date('now')
                   ORDER BY mp.mp_id DESC LIMIT 1''', (member_id,))
    row = cur.fetchone()
    if row:
        mp_id, visits_used, entitled_visits, membership_no = row
        visits_used_new = visits_used + 1
        cur.execute('UPDATE member_plan SET visits_used = ? WHERE mp_id=?', (visits_used_new, mp_id))
        # if plan completed, generate certificate
        if visits_used_new >= entitled_visits:
            try:
                pdf_bytes = generate_certificate_pdf(member_id, membership_no)
                parent_email = get_parent_email_by_member_id(member_id)
                if parent_email:
                    send_email_smtp(parent_email, 'Membership Completed - Certificate', 'Congratulations! Attached is your certificate.', attachment_bytes=pdf_bytes, attachment_name=f'certificate_{membership_no}.pdf')
            except Exception as e:
                print('Certificate/email failed', e)
    conn.commit(); conn.close()

def get_visits_df():
    conn = get_conn(); df = pd.read_sql_query('SELECT v.*, m.membership_no as membership_no FROM visits v JOIN members m ON v.member_id = m.member_id ORDER BY v.visit_date DESC', conn); conn.close()
    if 'membership_no' in df.columns: df['membership_no'] = df['membership_no'].astype(str)
    return df

# placeholder for parent email — extend schema if you want to store parent email
def get_parent_email_by_member_id(member_id):
    return None

# ---------- QR Code ----------
def generate_qr_image(membership_no):
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(membership_no)
    qr.make(fit=True)
    return qr.make_image(fill_color='black', back_color='white')

# ---------- PDF Certificate ----------
def generate_certificate_pdf(member_id, membership_no):
    conn = get_conn(); cur = conn.cursor()
    cur.execute('SELECT parent_name, child_name FROM members WHERE member_id=?', (member_id,))
    row = cur.fetchone(); conn.close()
    parent_name = row[0] if row else ''
    child_name = row[1] if row else ''
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    c.setFont('Helvetica-Bold', 24)
    c.drawCentredString(width/2, height - 150, 'Certificate of Completion')
    c.setFont('Helvetica', 16)
    c.drawCentredString(width/2, height - 200, f'Presented to: {child_name}')
    c.setFont('Helvetica', 12)
    c.drawCentredString(width/2, height - 230, f'Parent: {parent_name}')
    c.drawCentredString(width/2, height - 260, f'Membership No: {membership_no}')
    c.drawCentredString(width/2, height - 290, f'Date: {datetime.now().date().isoformat()}')
    c.showPage(); c.save(); buffer.seek(0)
    return buffer.getvalue()

# ---------- Streamlit UI ----------
init_db()
st.set_page_config(page_title='Membership ERP', layout='wide')
st.markdown("""<style>[data-testid='stSidebar']{background-color:#f0f2f6}h1{color:#0f4c81}</style>""", unsafe_allow_html=True)
st.title('Membership ERP (Streamlit)')

# session
if 'user' not in st.session_state: st.session_state.user = None

menu = st.sidebar.selectbox('Go to', ['Home', 'Login', 'Members', 'Plans', 'Assign Plan', 'Record Visit', 'Reports', 'Export Data'])

# --- Home ---
if menu == 'Home':
    st.markdown('### Quick actions')
    st.markdown('- Login to manage the ERP')

# --- Login ---
if menu == 'Login':
    st.header('Login')
    col1, col2 = st.columns(2)
    with col1:
        email = st.text_input('Email')
        pwd = st.text_input('Password', type='password')
        if st.button('Login'):
            ok, role, name = verify_user(email, pwd)
            if ok:
                st.session_state.user = {'email': email, 'role': role, 'name': name}
                st.success(f'Logged in as {name} ({role})')
            else:
                st.error('Invalid credentials')
    with col2:
        st.info('OTP login and user creation can be added here')

# protected area
if menu in ['Members', 'Plans', 'Assign Plan', 'Record Visit', 'Reports', 'Export Data'] and not st.session_state.get('user'):
    st.error('Please login first via the Login page')

# --- Members ---
if menu == 'Members' and st.session_state.get('user'):
    user = st.session_state.get('user')
    st.sidebar.markdown(f"Logged in: **{user.get('name')}** ({user.get('email')})")
    if st.sidebar.button('Logout'):
        st.session_state.user = None
        st.experimental_rerun()

    st.subheader('➕ Add New Member')
    with st.form('add_member'):
        parent_name = st.text_input('Parent Name *')
        phone = st.text_input('Phone Number *')
        child_name = st.text_input('Child Name *')
        child_dob = st.date_input('Child DOB')
        submitted = st.form_submit_button('Add Member')
        if submitted:
            if not parent_name or not phone or not child_name:
                st.error('Please fill required fields')
            else:
                membership_no = add_member(parent_name, phone, child_name, child_dob.isoformat())
                st.success(f'Member added: {membership_no}')
                img = generate_qr_image(membership_no)
                buf = io.BytesIO(); img.save(buf, format='PNG')
                st.image(Image.open(io.BytesIO(buf.getvalue())), width=150)
                st.download_button('Download QR', data=buf.getvalue(), file_name=f'{membership_no}.png')

    st.markdown('---')
    st.subheader('👥 Existing Members')
    df = get_members_df()
    if df.empty:
        st.info('No members yet')
    else:
        # selection by membership number
        member_list = df['membership_no'].tolist()
        sel = st.selectbox('Select member to view/edit', member_list)
        if sel:
            row = df[df['membership_no'] == sel].iloc[0]
            col1, col2 = st.columns([2,1])
            with col1:
                parent_new = st.text_input('Parent Name', value=row['parent_name'], key='parent_edit')
                phone_new = st.text_input('Phone Number', value=row['phone_number'], key='phone_edit')
                child_new = st.text_input('Child Name', value=row['child_name'], key='child_edit')
                dob_new = st.date_input('Child DOB', value=pd.to_datetime(row['child_dob']).date(), key='dob_edit')
                if st.button('Update Member'):
                    update_member(row['member_id'], parent_new, phone_new, child_new, dob_new.isoformat())
                    st.success('Member updated')
                    st.rerun()
            with col2:
                st.write('Membership No:')
                st.code(row['membership_no'])
                if st.button('Delete Member'):
                    delete_member(row['member_id'])
                    st.success('Member deleted')
                    st.experimental_rerun()

# --- Plans ---
if menu == 'Plans' and st.session_state.get('user'):
    st.subheader('Manage Plans')
    with st.form('add_plan'):
        plan_type = st.text_input('Plan Type')
        entitled_visits = st.number_input('No. of Visits Entitled', min_value=1, value=10)
        per_visit_hours = st.number_input('Hours per Visit', min_value=1, value=1)
        price = st.number_input('Price', min_value=0.0, value=0.0)
        validity_days = st.number_input('Validity (days)', min_value=1, value=30)
        if st.form_submit_button('Add Plan'):
            add_plan(plan_type, int(entitled_visits), int(per_visit_hours), float(price), int(validity_days))
            st.success('Plan added')
    st.markdown('---')
    st.subheader('Existing Plans')
    st.dataframe(get_plans_df())

# --- Assign Plan ---
if menu == 'Assign Plan' and st.session_state.get('user'):
    st.subheader('Assign Plan to Member')
    members_df = get_members_df(); plans_df = get_plans_df()
    if members_df.empty or plans_df.empty:
        st.info('Add members and plans first')
    else:
        mem = st.selectbox('Select Member', members_df['membership_no'].tolist())
        plan_opt = plans_df.apply(lambda r: f"{r['plan_id']} - {r['plan_type']} (Visits: {r['entitled_visits']})", axis=1).tolist()
        plan_sel = st.selectbox('Select Plan', plan_opt)
        start_date = st.date_input('Start Date', value=datetime.now().date())
        if st.button('Assign Plan'):
            plan_id = int(plan_sel.split(' - ')[0])
            member_row = members_df[members_df['membership_no'] == mem].iloc[0]
            assign_plan_to_member(member_row['member_id'], plan_id, start_date.isoformat())
            st.success('Plan assigned')

# --- Record Visit ---
if menu == 'Record Visit' and st.session_state.get('user'):
    st.subheader('Record Visit / Check-in')
    members_df = get_members_df()
    if members_df.empty:
        st.info('Add members first')
    else:
        mem = st.selectbox('Select Member for Visit', members_df['membership_no'].tolist())
        hours_used = st.number_input('Hours Used', min_value=1, value=1)
        notes = st.text_input('Notes (optional)')
        if st.button('Record Visit'):
            member_row = members_df[members_df['membership_no'] == mem].iloc[0]
            record_visit(member_row['member_id'], int(hours_used), notes)
            st.success('Visit recorded')

# --- Reports ---
if menu == 'Reports' and st.session_state.get('user'):
    st.subheader('Member Plans')
    st.dataframe(get_member_plans_df())
    st.subheader('Visits')
    st.dataframe(get_visits_df())

# --- Export Data ---
if menu == 'Export Data' and st.session_state.get('user'):
    st.header('Export Data')
    if st.button('Export all to Excel'):
        conn = get_conn()
        members = pd.read_sql_query('SELECT * FROM members', conn)
        plans = pd.read_sql_query('SELECT * FROM plans', conn)
        member_plan = pd.read_sql_query('SELECT mp.*, m.membership_no FROM member_plan mp JOIN members m ON mp.member_id = m.member_id', conn)
        visits = pd.read_sql_query('SELECT v.*, m.membership_no FROM visits v JOIN members m ON v.member_id = m.member_id', conn)
        conn.close()
        # Ensure membership_no is string to avoid Excel formatting issues
        if 'membership_no' in member_plan.columns: member_plan['membership_no'] = member_plan['membership_no'].astype(str)
        if 'membership_no' in visits.columns: visits['membership_no'] = visits['membership_no'].astype(str)
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer) as writer:
                members.to_excel(writer, sheet_name='members', index=False)
                plans.to_excel(writer, sheet_name='plans', index=False)
                member_plan.to_excel(writer, sheet_name='member_plan', index=False)
                visits.to_excel(writer, sheet_name='visits', index=False)
            st.download_button('Download Excel', data=buffer.getvalue(), file_name='membership_export.xlsx')

# End of file
