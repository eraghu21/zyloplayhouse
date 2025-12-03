# Membership ERP Streamlit app with Supabase
import streamlit as st
import pandas as pd
import io
from datetime import datetime, timedelta
from supabase import create_client, Client
import qrcode
from PIL import Image
import hashlib
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# ----------------- CONFIG -----------------
SUPABASE_URL = "your_supabase_url"
SUPABASE_SERVICE_ROLE_KEY = "your_service_role_key"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

# ----------------- HELPERS -----------------
def hash_password(password: str) -> str:
    salt = "streamlit_salt_v1"
    return hashlib.sha256((salt + password).encode()).hexdigest()

def safe_select(table: str, select_fields: str, eq_field=None, eq_value=None):
    """Safe Supabase select to prevent API errors"""
    try:
        query = supabase.table(table).select(select_fields)
        if eq_field and eq_value:
            query = query.eq(eq_field, eq_value)
        res = query.execute()
        if res.error:
            st.error(f"Supabase API error: {res.error}")
            return []
        return res.data
    except Exception as e:
        st.error(f"Supabase request failed: {e}")
        return []

# ----------------- USER FUNCTIONS -----------------
def verify_staff(email, password):
    users = safe_select("users", "user_id,password_hash,role,name", "email", email)
    if not users:
        return False, None, None
    user = users[0]
    if user["password_hash"] == hash_password(password):
        return True, user["role"], user["name"]
    return False, None, None

def create_admin_if_not_exists():
    """Option D admin creator"""
    users = safe_select("users", "email,role")
    if not any(u["role"] == "admin" for u in users):
        supabase.table("users").insert({
            "email": "admin@local",
            "name": "Administrator",
            "password_hash": hash_password("admin123"),
            "role": "admin"
        }).execute()
create_admin_if_not_exists()

# ----------------- MEMBERSHIP FUNCTIONS -----------------
def generate_membership_no():
    count_data = safe_select("members", "count(*)")
    count = count_data[0]["count"] if count_data else 0
    return f"ZPHSI-{int(count)+1:04d}"

def add_member(parent_name, phone, child_name, child_dob):
    membership_no = generate_membership_no()
    member_since = datetime.now().date().isoformat()
    supabase.table("members").insert({
        "membership_no": membership_no,
        "parent_name": parent_name,
        "phone_number": phone,
        "child_name": child_name,
        "child_dob": child_dob,
        "member_since": member_since
    }).execute()
    return membership_no

def get_members_df():
    data = safe_select("members", "*")
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if "membership_no" in df.columns:
        df["membership_no"] = df["membership_no"].astype(str)
    return df

# ----------------- QR CODE -----------------
def generate_qr_image(membership_no):
    qr = qrcode.QRCode(version=1, box_size=6, border=2)
    qr.add_data(membership_no)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white")

# ----------------- STREAMLIT UI -----------------
st.set_page_config(page_title="Membership ERP", layout="wide")
st.title("Membership ERP (Supabase)")

# session
if "user" not in st.session_state:
    st.session_state.user = None

menu = st.sidebar.selectbox("Go to", ["Home", "Login", "Members"])

# --- Home ---
if menu == "Home":
    st.markdown("### Quick Actions")
    st.markdown("- Login to manage the ERP")

# --- Login ---
if menu == "Login":
    st.header("Login")
    email = st.text_input("Email")
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        ok, role, name = verify_staff(email, pwd)
        if ok:
            st.session_state.user = {"email": email, "role": role, "name": name}
            st.success(f"Logged in as {name} ({role})")
        else:
            st.error("Invalid credentials or API error")

# --- Members ---
if menu == "Members" and st.session_state.get("user"):
    st.sidebar.markdown(f"Logged in: **{st.session_state.user['name']}**")
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.experimental_rerun()

    st.subheader("➕ Add New Member")
    parent_name = st.text_input("Parent Name *")
    phone = st.text_input("Phone Number *")
    child_name = st.text_input("Child Name *")
    child_dob = st.date_input("Child DOB")
    if st.button("Add Member"):
        if not parent_name or not phone or not child_name:
            st.error("Fill all required fields")
        else:
            membership_no = add_member(parent_name, phone, child_name, child_dob.isoformat())
            st.success(f"Member added: {membership_no}")
            img = generate_qr_image(membership_no)
            buf = io.BytesIO(); img.save(buf, format="PNG")
            st.image(Image.open(io.BytesIO(buf.getvalue())), width=150)
            st.download_button("Download QR", data=buf.getvalue(), file_name=f"{membership_no}.png")

    st.markdown("---")
    st.subheader("👥 Existing Members")
    df = get_members_df()
    st.dataframe(df)
