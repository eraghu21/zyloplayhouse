-- Users (staff)
create table if not exists users (
  user_id serial primary key,
  email text unique,
  name text,
  password_hash text,
  role text
);

-- Members
create table if not exists members (
  member_id serial primary key,
  membership_no text unique,
  parent_name text,
  phone_number text,
  child_name text,
  child_dob date,
  parent_email text,
  member_since date
);

-- Plans
create table if not exists plans (
  plan_id serial primary key,
  plan_name text,
  price numeric,
  duration_days integer
);

-- Member Plan assignments
create table if not exists member_plan (
  mp_id serial primary key,
  member_id integer references members(member_id),
  plan_id integer references plans(plan_id),
  start_date date,
  end_date date,
  visits_used integer default 0
);

-- Visits
create table if not exists visits (
  visit_id serial primary key,
  member_id integer references members(member_id),
  visit_date timestamptz,
  hours_used integer,
  notes text
);

-- Invoices & payments
create table if not exists invoices (
  invoice_id serial primary key,
  member_id integer references members(member_id),
  amount numeric,
  description text,
  status text default 'unpaid',
  invoice_date date
);

create table if not exists payments (
  payment_id serial primary key,
  invoice_id integer references invoices(invoice_id),
  amount_paid numeric,
  method text,
  paid_at timestamptz,
  note text
);
