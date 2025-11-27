
import streamlit as st
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import io, os, random, string, base64
import qrcode
from PIL import Image
import hashlib, smtplib
from email.message import EmailMessage
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

DB_FILE = 'data/membership_erp.db'
DEFAULT_ADMIN_EMAIL = 'admin@local'
DEFAULT_ADMIN_PASSWORD = 'admin123'  # change in production

# ---------- Helpers ----------
def get_conn():
    os.makedirs('data', exist_ok=True)
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE,
        name TEXT,
        password_hash TEXT,
        role TEXT
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS members (
        member_id INTEGER PRIMARY KEY AUTOINCREMENT,
        membership_no TEXT UNIQUE,
        parent_name TEXT,
        phone_number TEXT,
        child_name TEXT,
        child_dob TEXT,
        member_since TEXT
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS plans (
        plan_id INTEGER PRIMARY KEY AUTOINCREMENT,
        plan_type TEXT,
        entitled_visits INTEGER,
        per_visit_hours INTEGER,
        price REAL,
        validity_days INTEGER
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS member_plan (
        mp_id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER,
        plan_id INTEGER,
        start_date TEXT,
        end_date TEXT,
        visits_used INTEGER DEFAULT 0,
        FOREIGN KEY(member_id) REFERENCES members(member_id),
        FOREIGN KEY(plan_id) REFERENCES plans(plan_id)
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS visits (
        visit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id INTEGER,
        visit_date TEXT,
        hours_used INTEGER,
        notes TEXT,
        FOREIGN KEY(member_id) REFERENCES members(member_id)
    )
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        k TEXT PRIMARY KEY,
        v TEXT
    )
    ''')
    conn.commit()

    # create default admin if not exists
    cur.execute('SELECT COUNT(*) FROM users')
    c = cur.fetchone()[0]
    if c == 0:
        add_user(DEFAULT_ADMIN_EMAIL, 'Administrator', DEFAULT_ADMIN_PASSWORD, role='admin')
    conn.close()

def hash_password(password: str) -> str:
    salt = 'streamlit_salt_v1'  # change to random in real app
    return hashlib.sha256((salt + password).encode()).hexdigest()

def add_user(email, name, password, role='staff'):
    conn = get_conn()
    cur = conn.cursor()
    pwd_hash = hash_password(password)
    try:
        cur.execute('INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)', (email, name, pwd_hash, role))
        conn.commit()
    except Exception as e:
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

def generate_membership_no(conn):
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM members")
    count = cur.fetchone()[0] or 0
    return f"ZPHSI-{count+1:04d}"

# ---------- Email (SMTP) ----------
def set_setting(k, v):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('INSERT OR REPLACE INTO settings (k, v) VALUES (?, ?)', (k, v))
    conn.commit()
    conn.close()

def get_setting(k):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT v FROM settings WHERE k=?', (k,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def send_email_smtp(to_email, subject, body, attachment_bytes=None, attachment_name='attachment.pdf'):
    smtp_host = get_setting('smtp_host')
    smtp_port = int(get_setting('smtp_port') or 587)
    smtp_user = get_setting('smtp_user')
    smtp_pass = get_setting('smtp_pass')
    if not smtp_host or not smtp_user or not smtp_pass:
        raise ValueError('SMTP not configured in Settings')
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg.set_content(body)
    if attachment_bytes:
        msg.add_attachment(attachment_bytes, maintype='application', subtype='pdf', filename=attachment_name)
    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.send_message(msg)

# OTP store (in-memory for demo). In production, use DB with TTL.
_otp_store = {}

def send_otp_email(to_email):
    otp = ''.join(str(random.randint(0,9)) for _ in range(6))
    _otp_store[to_email] = {'otp': otp, 'created': datetime.now()}
    try:
        send_email_smtp(to_email, 'Your OTP for Membership ERP', f'Your OTP is: {otp}')
    except Exception as e:
        print('Failed to send OTP email:', e)
        raise
    return otp

# ---------- Core operations ----------
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
    cur.execute('''UPDATE members SET parent_name=?, phone_number=?, child_name=?, child_dob=? WHERE member_id=?''', (parent_name, phone, child_name, child_dob, member_id))
    conn.commit()
    conn.close()

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
        raise ValueError('Plan not found')
    validity_days = row[0]
    end_date = start_date + timedelta(days=validity_days)
    cur.execute('''INSERT INTO member_plan (member_id, plan_id, start_date, end_date, visits_used)
                   VALUES (?, ?, ?, ?, 0)''', (member_id, plan_id, start_date.isoformat(), end_date.isoformat()))
    conn.commit()
    conn.close()

def record_visit(member_id, hours_used=1, notes=''):
    conn = get_conn()
    cur = conn.cursor()
    visit_date = datetime.now().isoformat()
    cur.execute('''INSERT INTO visits (member_id, visit_date, hours_used, notes)
                   VALUES (?, ?, ?, ?)''', (member_id, visit_date, hours_used, notes))
    # increment visits_used in member_plan (latest active)
    cur.execute('''SELECT mp_id, visits_used, p.entitled_visits, m.membership_no FROM member_plan mp JOIN plans p ON mp.plan_id=p.plan_id JOIN members m ON mp.member_id=m.member_id WHERE mp.member_id=? AND date(mp.end_date) >= date('now') ORDER BY mp.mp_id DESC LIMIT 1''', (member_id,))
    row = cur.fetchone()
    if row:
        mp_id, visits_used, entitled_visits, membership_no = row
        cur.execute('UPDATE member_plan SET visits_used = visits_used + 1 WHERE mp_id=?', (mp_id,))
        visits_used_new = visits_used + 1
        # If plan completed, auto-generate certificate and email
        if visits_used_new >= entitled_visits:
            try:
                pdf_bytes = generate_certificate_pdf(member_id, membership_no)
                parent_email = get_member_parent_email_by_member_id(member_id)
                if parent_email:
                    send_email_smtp(parent_email, 'Membership Completed - Certificate', 'Congratulations! Attached is your certificate.', attachment_bytes=pdf_bytes, attachment_name=f'certificate_{membership_no}.pdf')
            except Exception as e:
                print('Failed to email certificate:', e)
    conn.commit()
    conn.close()

# ---------- Query helpers ----------
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

def get_member_by_phone(phone):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT * FROM members WHERE phone_number=?', (phone,))
    row = cur.fetchone()
    conn.close()
    return row

def get_active_plan_for_member(member_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('''SELECT mp.mp_id, p.plan_type, p.entitled_visits, mp.start_date, mp.end_date, mp.visits_used, p.per_visit_hours, p.price FROM member_plan mp JOIN plans p ON mp.plan_id = p.plan_id WHERE mp.member_id=? AND date(mp.end_date) >= date('now') ORDER BY mp.mp_id DESC LIMIT 1''', (member_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_visits_for_member(member_id):
    conn = get_conn()
    df = pd.read_sql_query('SELECT * FROM visits WHERE member_id=? ORDER BY visit_date DESC', conn, params=(member_id,))
    conn.close()
    return df

def get_member_parent_email_by_member_id(member_id):
    # For this demo we use the users table email if parent provided matches a user; otherwise return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT phone_number FROM members WHERE member_id=?', (member_id,))
    row = cur.fetchone()
    conn.close()
    # In production, store parent email as a separate field. Here we'll return None.
    return None

# ---------- QR Code ----------
def generate_qr_image(membership_no):
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(membership_no)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    return img

# ---------- Certificate PDF ----------
def generate_certificate_pdf(member_id, membership_no):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute('SELECT parent_name, child_name FROM members WHERE member_id=?', (member_id,))
    row = cur.fetchone()
    conn.close()
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
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer.getvalue()

# ---------- Streamlit UI ----------
init_db()

st.set_page_config(page_title='Membership ERP - Streamlit', layout='wide')

st.markdown("<style>[data-testid='stSidebar'] {background-color: #f0f2f6} h1 {color: #0f4c81}</style>", unsafe_allow_html=True)
st.title('Membership ERP (Streamlit) - Enhanced (OTP + Certificates)')

menu = st.sidebar.selectbox('Go to', ['Home', 'Login', 'Member Lookup', 'Export Data'])

if 'user' not in st.session_state:
    st.session_state.user = None

# Home
if menu == 'Home':
    st.markdown('''#### Quick actions - Login as admin/staff to manage members and plans - Member Lookup to view membership details''')

# Login
if menu == 'Login':
    st.header('Login')
    col1, col2 = st.columns(2)
    with col1:
        st.subheader('Password Login')
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
        st.subheader('OTP Login (email)')
        otp_email = st.text_input('Email for OTP', key='otp_email')
        if st.button('Send OTP'):
            try:
                send_otp_email(otp_email)
                st.session_state['otp_email_sent'] = otp_email
                st.success('OTP sent to email (check spam if not visible).')
            except Exception as e:
                st.error(f'Failed to send OTP: {e}')
        entered_otp = st.text_input('Enter OTP', key='entered_otp')
        if st.button('Verify OTP'):
            stored = _otp_store.get(st.session_state.get('otp_email_sent'))
            if stored and entered_otp == stored.get('otp'):
                # For OTP users we create a temporary staff user if not exists
                add_user(st.session_state.get('otp_email_sent'), st.session_state.get('otp_email_sent'), 'otp-temp-password', role='staff')
                st.session_state.user = {'email': st.session_state.get('otp_email_sent'), 'role': 'staff', 'name': st.session_state.get('otp_email_sent')}
                st.success('OTP verified. Logged in.')
            else:
                st.error('Invalid or expired OTP.')

# If logged in, show admin panel
if st.session_state.user and st.session_state.user.get('role') in ('admin','staff'):
    user = st.session_state.user
    st.sidebar.markdown(f"Logged in: {user.get('name')} ({user.get('email')})")

    if st.sidebar.button('Logout'):
        st.session_state.pop('user', None)
        st.experimental_rerun()
    tab = st.tabs(['Members','Plans','Assign Plan','Record Visit','Settings','Reports'])

    # Members
    with tab[0]:
        st.subheader('Add new member')
        with st.form('add_member'):
            parent_name = st.text_input('Parent Name')
            phone = st.text_input('Phone Number')
            child_name = st.text_input('Child Name')
            child_dob = st.date_input('Child DOB')
            submitted = st.form_submit_button('Add Member')
            if submitted:
                if not parent_name or not phone or not child_name:
                    st.error('Please fill required fields')
                else:
                    membership_no = add_member(parent_name, phone, child_name, child_dob.isoformat())
                    st.success(f'Added member {membership_no}')
                    img = generate_qr_image(membership_no)
                    buf = io.BytesIO()
                    img.save(buf, format='PNG')
                    st.image(Image.open(io.BytesIO(buf.getvalue())), width=150)
                    st.download_button('Download QR', data=buf.getvalue(), file_name=f'{membership_no}.png')

        st.markdown('---')
        st.subheader('Existing members')
        df_members = get_members_df()
        st.dataframe(df_members)
        st.markdown('Edit a member')
        member_select = st.selectbox('Choose member to edit', df_members['membership_no'].tolist() if not df_members.empty else [])
        if member_select:
            row = df_members[df_members['membership_no'] == member_select].iloc[0]
            with st.form('edit_member'):
                parent_name2 = st.text_input('Parent Name', value=row['parent_name'])
                phone2 = st.text_input('Phone Number', value=row['phone_number'])
                child_name2 = st.text_input('Child Name', value=row['child_name'])
                child_dob2 = st.date_input('Child DOB', value=pd.to_datetime(row['child_dob']).date() if row['child_dob'] else None)
                submitted2 = st.form_submit_button('Update Member')
                if submitted2:
                    update_member(row['member_id'], parent_name2, phone2, child_name2, child_dob2.isoformat())
                    st.success('Member updated')

    # Plans
    with tab[1]:
        st.subheader('Manage Plans')
        with st.form('add_plan'):
            plan_type = st.text_input('Plan Type (e.g., Gold)')
            entitled_visits = st.number_input('No. of Visits Entitled', min_value=0, value=10)
            per_visit_hours = st.number_input('Hours per Visit', min_value=0, value=1)
            price = st.number_input('Price', min_value=0.0, value=0.0)
            validity_days = st.number_input('Validity (days)', min_value=1, value=30)
            addp = st.form_submit_button('Add Plan')
            if addp:
                add_plan(plan_type, int(entitled_visits), int(per_visit_hours), float(price), int(validity_days))
                st.success('Plan added')
        st.markdown('Existing plans')
        st.dataframe(get_plans_df())

    # Assign Plan
    with tab[2]:
        st.subheader('Assign Plan to Member')
        members_df = get_members_df()
        plans_df = get_plans_df()
        if members_df.empty or plans_df.empty:
            st.info('Add members and plans first')
        else:
            mem_sel = st.selectbox('Select Member', members_df['membership_no'].tolist())
            plan_sel = st.selectbox('Select Plan', plans_df['plan_id'].astype(str) + ' - ' + plans_df['plan_type'])
            start_date = st.date_input('Start Date', value=datetime.now().date())
            if st.button('Assign Plan'):
                member_row = members_df[members_df['membership_no'] == mem_sel].iloc[0]
                plan_id = int(plan_sel.split(' - ')[0])
                assign_plan_to_member(int(member_row['member_id']), plan_id, start_date.isoformat())
                st.success('Plan assigned')

    # Record Visit
    with tab[3]:
        st.subheader('Record Visit / Check-in')
        members_df = get_members_df()
        if members_df.empty:
            st.info('Add members first')
        else:
            mem_sel2 = st.selectbox('Select Member for Visit', members_df['membership_no'].tolist())
            hours_used = st.number_input('Hours Used', min_value=0, value=1)
            notes = st.text_input('Notes (optional)')
            if st.button('Record Visit'):
                member_row = members_df[members_df['membership_no'] == mem_sel2].iloc[0]
                record_visit(int(member_row['member_id']), int(hours_used), notes)
                st.success('Visit recorded')

            st.markdown('---')
            st.markdown('Or scan QR:')
            qr_input = st.text_input('Paste membership number from QR to check-in (e.g., ZPHSI-0001)')
            if st.button('Check-in via QR') and qr_input:
                row = get_member_by_membership_no(qr_input)
                if not row:
                    st.error('Member not found')
                else:
                    record_visit(row[0], 1, 'QR Check-in')
                    st.success('Checked in via QR')

    # Settings (admin only)
    with tab[4]:
        st.subheader('Settings (SMTP, App)')
        if st.session_state.user.get('role') != 'admin':
            st.info('Only admin users can modify SMTP settings.')
        smtp_host = st.text_input('SMTP Host', value=get_setting('smtp_host') or '')
        smtp_port = st.text_input('SMTP Port', value=get_setting('smtp_port') or '587')
        smtp_user = st.text_input('SMTP User (from email)', value=get_setting('smtp_user') or '')
        smtp_pass = st.text_input('SMTP Password', value=get_setting('smtp_pass') or '')
        if st.session_state.user.get('role') == 'admin' and st.button('Save Settings'):
            set_setting('smtp_host', smtp_host)
            set_setting('smtp_port', smtp_port)
            set_setting('smtp_user', smtp_user)
            set_setting('smtp_pass', smtp_pass)
            st.success('Settings saved')
        if st.button('Test SMTP (send test email to admin)'):
            try:
                admin_email = st.session_state.user.get('email')
                send_email_smtp(admin_email, 'Test SMTP', 'This is a test email from Membership ERP')
                st.success('Test email sent')
            except Exception as e:
                st.error(f'Failed to send test email: {e}')

    # Reports
    with tab[5]:
        st.subheader('Reports')
        st.markdown('Members')
        st.dataframe(get_members_df())
        st.markdown('Plans')
        st.dataframe(get_plans_df())
        st.markdown('Member Plans (all)')
        conn = get_conn()
        mp = pd.read_sql_query('''SELECT mp.*, m.membership_no, p.plan_type, p.entitled_visits FROM member_plan mp JOIN members m ON mp.member_id = m.member_id JOIN plans p ON mp.plan_id = p.plan_id ORDER BY mp.mp_id DESC''', conn)
        conn.close()
        st.dataframe(mp)
        if st.button('Export all and email to admin'):
            conn = get_conn()
            members = pd.read_sql_query('SELECT * FROM members', conn)
            plans = pd.read_sql_query('SELECT * FROM plans', conn)
            member_plan = pd.read_sql_query('SELECT * FROM member_plan', conn)
            visits = pd.read_sql_query('SELECT * FROM visits', conn)
            conn.close()
            with io.BytesIO() as buffer:
                with pd.ExcelWriter(buffer) as writer:
                    members.to_excel(writer, sheet_name='members', index=False)
                    plans.to_excel(writer, sheet_name='plans', index=False)
                    member_plan.to_excel(writer, sheet_name='member_plan', index=False)
                    visits.to_excel(writer, sheet_name='visits', index=False)
                data = buffer.getvalue()
            try:
                send_email_smtp(st.session_state.user.get('email'), 'Membership Export', 'Attached is the exported data', attachment_bytes=data, attachment_name='membership_export.xlsx')
                st.success('Export emailed')
            except Exception as e:
                st.error(f'Failed to email export: {e}')

# Member Lookup (public)
if menu == 'Member Lookup':
    st.header('Member Lookup / Customer View')
    lookup_method = st.radio('Search by', ['Membership No', 'Phone Number'])
    if lookup_method == 'Membership No':
        membership_no = st.text_input('Membership No (e.g., ZPHSI-0001)')
        if st.button('Lookup'):
            row = get_member_by_membership_no(membership_no)
            if not row:
                st.error('Member not found')
            else:
                member_id = row[0]
                st.subheader(f"{row[4]} ({row[1]})")
                st.write(f"Parent: {row[2]}")
                st.write(f"Phone: {row[3]}")
                st.write(f"Child DOB: {row[5]}")
                st.write(f"Member since: {row[6]}")
                # show QR
                img = generate_qr_image(row[1])
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                st.image(Image.open(io.BytesIO(buf.getvalue())), width=150)
                st.download_button('Download QR', data=buf.getvalue(), file_name=f'{row[1]}.png')
                active = get_active_plan_for_member(member_id)
                if active:
                    mp_id, plan_type, entitled_visits, start_date, end_date, visits_used, per_visit_hours, price = active
                    visits_pending = entitled_visits - visits_used
                    st.markdown('**Current Plan**')
                    st.write(f\"Plan: {plan_type}\")
                    st.write(f\"Entitled Visits: {entitled_visits}\")
                    st.write(f\"Visits Used: {visits_used}\")
                    st.write(f\"Visits Pending: {visits_pending}\")
                    st.write(f\"Validity: {start_date} to {end_date}\")
                    st.write(f\"Hours per visit: {per_visit_hours}\")
                    st.write(f\"Price: {price}\")
                else:
                    st.info('No active plan')
                st.markdown('Visit History')
                st.dataframe(get_visits_for_member(member_id))
    else:
        phone = st.text_input('Phone Number')
        if st.button('Lookup by Phone'):
            row = get_member_by_phone(phone)
            if not row:
                st.error('Member not found')
            else:
                member_id = row[0]
                st.subheader(f\"{row[4]} ({row[1]})\")
                st.write(f\"Parent: {row[2]}\")
                st.write(f\"Phone: {row[3]}\")
                st.write(f\"Child DOB: {row[5]}\")
                st.write(f\"Member since: {row[6]}\")
                img = generate_qr_image(row[1])
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                st.image(Image.open(io.BytesIO(buf.getvalue())), width=150)
                st.download_button('Download QR', data=buf.getvalue(), file_name=f'{row[1]}.png')
                active = get_active_plan_for_member(member_id)
                if active:
                    mp_id, plan_type, entitled_visits, start_date, end_date, visits_used, per_visit_hours, price = active
                    visits_pending = entitled_visits - visits_used
                    st.markdown('**Current Plan**')
                    st.write(f\"Plan: {plan_type}\")
                    st.write(f\"Entitled Visits: {entitled_visits}\")
                    st.write(f\"Visits Used: {visits_used}\")
                    st.write(f\"Visits Pending: {visits_pending}\")
                    st.write(f\"Validity: {start_date} to {end_date}\")
                    st.write(f\"Hours per visit: {per_visit_hours}\")
                    st.write(f\"Price: {price}\")
                else:
                    st.info('No active plan')
                st.markdown('Visit History')
                st.dataframe(get_visits_for_member(member_id))

# Export Data
if menu == 'Export Data':
    st.header('Export Data')
    if st.button('Export all to Excel'):
        conn = get_conn()
        members = pd.read_sql_query('SELECT * FROM members', conn)
        plans = pd.read_sql_query('SELECT * FROM plans', conn)
        member_plan = pd.read_sql_query('SELECT * FROM member_plan', conn)
        visits = pd.read_sql_query('SELECT * FROM visits', conn)
        conn.close()
        with io.BytesIO() as buffer:
            with pd.ExcelWriter(buffer) as writer:
                members.to_excel(writer, sheet_name='members', index=False)
                plans.to_excel(writer, sheet_name='plans', index=False)
                member_plan.to_excel(writer, sheet_name='member_plan', index=False)
                visits.to_excel(writer, sheet_name='visits', index=False)
            st.download_button('Download Excel', data=buffer.getvalue(), file_name='membership_export.xlsx')
