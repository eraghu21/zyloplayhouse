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
    cur.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE,name TEXT,password_hash TEXT,role TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS members (member_id INTEGER PRIMARY KEY AUTOINCREMENT,membership_no TEXT UNIQUE,parent_name TEXT,phone_number TEXT,child_name TEXT,child_dob TEXT,member_since TEXT)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS plans (plan_id INTEGER PRIMARY KEY AUTOINCREMENT,plan_type TEXT,entitled_visits INTEGER,per_visit_hours INTEGER,price REAL,validity_days INTEGER)''')
    cur.execute('''CREATE TABLE IF NOT EXISTS member_plan (mp_id INTEGER PRIMARY KEY AUTOINCREMENT,member_id INTEGER,plan_id INTEGER,start_date TEXT,end_date TEXT,visits_used INTEGER DEFAULT 0,FOREIGN KEY(member_id) REFERENCES members(member_id),FOREIGN KEY(plan_id) REFERENCES plans(plan_id))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS visits (visit_id INTEGER PRIMARY KEY AUTOINCREMENT,member_id INTEGER,visit_date TEXT,hours_used INTEGER,notes TEXT,FOREIGN KEY(member_id) REFERENCES members(member_id))''')
    cur.execute('''CREATE TABLE IF NOT EXISTS settings (k TEXT PRIMARY KEY,v TEXT)''')
    conn.commit()
    # create default admin if not exists
    cur.execute('SELECT COUNT(*) FROM users')
    if cur.fetchone()[0] == 0:
        add_user(DEFAULT_ADMIN_EMAIL, 'Administrator', DEFAULT_ADMIN_PASSWORD, role='admin')
    conn.close()

def hash_password(password):
    salt = 'streamlit_salt_v1'
    return hashlib.sha256((salt+password).encode()).hexdigest()

def add_user(email, name, password, role='staff'):
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO users (email,name,password_hash,role) VALUES (?,?,?,?)',(email,name,hash_password(password),role))
        conn.commit()
    except:
        pass
    conn.close()

def verify_user(email,password):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT password_hash,role,name FROM users WHERE email=?',(email,))
    row = cur.fetchone()
    conn.close()
    if not row: return False,None,None
    stored,role,name = row
    return stored==hash_password(password),role,name

def generate_membership_no():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM members')
    count = cur.fetchone()[0] or 0
    conn.close()
    return f'ZPHSI-{count+1:04d}'

# ---------- SMTP ----------
def set_setting(k,v):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO settings (k,v) VALUES (?,?)',(k,v))
    conn.commit()
    conn.close()

def get_setting(k):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT v FROM settings WHERE k=?',(k,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def send_email_smtp(to_email,subject,body,attachment_bytes=None,attachment_name='attachment.pdf'):
    smtp_host = get_setting('smtp_host')
    smtp_port = int(get_setting('smtp_port') or 587)
    smtp_user = get_setting('smtp_user')
    smtp_pass = get_setting('smtp_pass')
    if not smtp_host or not smtp_user or not smtp_pass: raise ValueError('SMTP not configured')
    msg = EmailMessage()
    msg['Subject']=subject
    msg['From']=smtp_user
    msg['To']=to_email
    msg.set_content(body)
    if attachment_bytes: msg.add_attachment(attachment_bytes, maintype='application',subtype='pdf',filename=attachment_name)
    with smtplib.SMTP(smtp_host,smtp_port) as s:
        s.starttls()
        s.login(smtp_user,smtp_pass)
        s.send_message(msg)

# ---------- Core ----------
def add_member(parent_name,phone,child_name,child_dob):
    conn=get_conn();cur=conn.cursor()
    membership_no=generate_membership_no()
    member_since=datetime.now().date().isoformat()
    cur.execute('INSERT INTO members (membership_no,parent_name,phone_number,child_name,child_dob,member_since) VALUES (?,?,?,?,?,?)',
                (membership_no,parent_name,phone,child_name,child_dob,member_since))
    conn.commit();conn.close()
    return membership_no

def update_member(member_id,parent_name,phone,child_name,child_dob):
    conn=get_conn();cur=conn.cursor()
    cur.execute('UPDATE members SET parent_name=?,phone_number=?,child_name=?,child_dob=? WHERE member_id=?',
                (parent_name,phone,child_name,child_dob,member_id))
    conn.commit();conn.close()

def delete_member(member_id):
    conn=get_conn();cur=conn.cursor()
    cur.execute('DELETE FROM members WHERE member_id=?',(member_id,))
    conn.commit();conn.close()

def get_members_df():
    conn=get_conn()
    df=pd.read_sql_query('SELECT * FROM members',conn)
    conn.close()
    df['membership_no']=df['membership_no'].astype(str)  # fix for Excel
    return df

def generate_qr_image(membership_no):
    qr=qrcode.QRCode(version=1,box_size=6,border=2)
    qr.add_data(membership_no)
    qr.make(fit=True)
    return qr.make_image(fill_color='black',back_color='white')

# ---------- Streamlit ----------
init_db()
st.set_page_config(page_title='Membership ERP',layout='wide')
st.title('Membership ERP (Streamlit)')

if 'user' not in st.session_state: st.session_state.user=None

menu = st.sidebar.selectbox('Go to',['Home','Login','Members','Export Data'])

# --- Home ---
if menu=='Home':
    st.markdown('Login as admin/staff to manage members and plans')

# --- Login ---
if menu=='Login':
    email = st.text_input('Email')
    pwd = st.text_input('Password',type='password')
    if st.button('Login'):
        ok,role,name=verify_user(email,pwd)
        if ok:
            st.session_state.user={'email':email,'role':role,'name':name}
            st.success(f'Logged in as {name} ({role})')
        else:
            st.error('Invalid credentials')

# --- Members ---
if menu=='Members':
    if not st.session_state.user:
        st.error('Login first')
    else:
        user=st.session_state.user
        st.sidebar.markdown(f"Logged in: **{user.get('name')}** ({user.get('email')})")
        if st.sidebar.button('Logout'):
            st.session_state.user=None
            st.experimental_rerun()

        st.subheader('Add New Member')
        with st.form('add_member_form'):
            parent_name=st.text_input('Parent Name *')
            phone=st.text_input('Phone Number *')
            child_name=st.text_input('Child Name *')
            child_dob=st.date_input('Child DOB')
            submitted=st.form_submit_button('Add')
            if submitted:
                if not parent_name or not phone or not child_name:
                    st.error('Fill all fields')
                else:
                    membership_no=add_member(parent_name,phone,child_name,child_dob.isoformat())
                    st.success(f'Member added: {membership_no}')
                    img=generate_qr_image(membership_no)
                    buf=io.BytesIO();img.save(buf,format='PNG')
                    st.image(Image.open(io.BytesIO(buf.getvalue())),width=150)
                    st.download_button('Download QR',data=buf.getvalue(),file_name=f'{membership_no}.png')

        st.markdown('---')
        st.subheader('Existing Members')
        df=get_members_df()
        member_list=df['membership_no'].tolist() if not df.empty else []
        member_select=st.selectbox('Select member',member_list)
        if member_select:
            row=df[df['membership_no']==member_select].iloc[0]
            col1,col2=st.columns(2)
            with col1:
                st.text_input('Parent Name',value=row['parent_name'],key='edit_parent')
                st.text_input('Phone',value=row['phone_number'],key='edit_phone')
                st.text_input('Child Name',value=row['child_name'],key='edit_child')
                st.date_input('Child DOB',value=pd.to_datetime(row['child_dob']).date(),key='edit_dob')
            with col2:
                if st.button('Update Member'):
                    update_member(row['member_id'],st.session_state['edit_parent'],st.session_state['edit_phone'],st.session_state['edit_child'],st.session_state['edit_dob'].isoformat())
                    st.success('Member updated')
                    st.experimental_rerun()
                if st.button('Delete Member'):
                    delete_member(row['member_id'])
                    st.success('Member deleted')
                    st.experimental_rerun()

# --- Export Data ---
if menu=='Export Data':
    st.header('Export Data')
    if st.button('Export all to Excel'):
        conn=get_conn()
        members=pd.read_sql_query('SELECT * FROM members',conn)
        plans=pd.read_sql_query('SELECT * FROM plans',conn)
        member_plan=pd.read_sql_query('SELECT * FROM member_plan',conn)
        visits=pd.read_sql_query('SELECT * FROM visits',conn)
        conn.close()
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer) as writer:
                members.to_excel(writer,sheet_name='members',index=False)
                plans.to_excel(writer,sheet_name='plans',index=False)
                member_plan['member_id']=member_plan['member_id'].astype(str)
                member_plan.to_excel(writer,sheet_name='member_plan',index=False)
                visits.to_excel(writer,sheet_name='visits',index=False)
            st.download_button('Download Excel',data=buffer.getvalue(),file_name='membership_export.xlsx')
