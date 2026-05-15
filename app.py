import os
import io
import csv
import sqlite3
import json
import secrets
from datetime import datetime, timedelta, date
from functools import wraps
from collections import defaultdict

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, g, send_file, make_response, jsonify)
from werkzeug.security import generate_password_hash, check_password_hash

# ── App Setup ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
DB_PATH    = os.path.join(BASE_DIR, 'data', 'finance.db')
CHART_DIR  = os.path.join(BASE_DIR, 'static', 'charts')
os.makedirs(CHART_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

# Categories for expenses
CATEGORIES = {
    'Essential':   ['Rent', 'Food', 'Transport', 'Utilities'],
    'Recreation':  ['Entertainment', 'Hobbies', 'Eating out', 'Shopping'],
    'Savings':     ['Emergency Fund', 'Investment', 'Goals'],
    'Income':      ['Salary', 'Business', 'Investment Returns', 'Gifts']
}

SHOPPING_CATEGORIES = ['Groceries', 'Household', 'Electronics', 'Personal Care', 'Clothing', 'Other']

# Account configuration - 4 specific accounts
ACCOUNTS_CONFIG = [
    {'name': 'Mpesa',    'type': 'mobile_money', 'color': '#2ecc71'},
    {'name': 'i&m1',     'type': 'checking',      'color': '#3498db'},
    {'name': 'i&m2',     'type': 'checking',      'color': '#2980b9'},
    {'name': 'Britam',   'type': 'savings',       'color': '#f39c12'}
]

CURRENCY        = 'KES'
CURRENCY_SYMBOL = 'KES'

PERIOD_OPTIONS = [
    ('7days',   'Last 7 Days'),
    ('month',   'This Month'),
    ('3months', 'Last 3 Months'),
    ('year',    'This Year'),
    ('all',     'All Time'),
    ('custom',  'Custom Range'),
]

PERIOD_OPTIONS_BUDGET = ['monthly', 'weekly', 'yearly']

PRIORITY_OPTIONS = [(1, 'High'), (2, 'Medium'), (3, 'Low')]

# ── Database Functions ────────────────────────────────────────────────────────
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db:
        db.close()

def init_db():
    """Initialize database with all tables including accounts"""
    db = sqlite3.connect(DB_PATH)
    db.executescript('''
        -- Users table
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- ACCOUNTS table with specific accounts
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            color TEXT,
            currency TEXT DEFAULT 'KES',
            balance REAL DEFAULT 0,
            initial_balance REAL DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- Expenses table
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            category TEXT NOT NULL,
            subcategory TEXT NOT NULL,
            expense_date TEXT NOT NULL,
            account_id INTEGER,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (account_id) REFERENCES accounts(id)
        );

        -- Income table
        CREATE TABLE IF NOT EXISTS income (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            source TEXT NOT NULL,
            description TEXT,
            income_date TEXT NOT NULL,
            account_id INTEGER,
            category TEXT DEFAULT 'Income',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (account_id) REFERENCES accounts(id)
        );

        -- Transfers between accounts
        CREATE TABLE IF NOT EXISTS transfers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            from_account_id INTEGER NOT NULL,
            to_account_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            transfer_date TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (from_account_id) REFERENCES accounts(id),
            FOREIGN KEY (to_account_id) REFERENCES accounts(id)
        );

        -- Shopping list table
        CREATE TABLE IF NOT EXISTS shopping_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            category TEXT DEFAULT 'Uncategorized',
            priority INTEGER DEFAULT 2,
            estimated_price REAL,
            bought INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            last_modified_by TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- Budgets table
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            monthly_limit REAL NOT NULL,
            period_type TEXT DEFAULT 'monthly',
            rollover_enabled INTEGER DEFAULT 0,
            alert_threshold INTEGER DEFAULT 80,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- Budget alerts
        CREATE TABLE IF NOT EXISTS budget_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            alert_type TEXT,
            sent_at TEXT DEFAULT (datetime('now')),
            acknowledged INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- Shopping templates
        CREATE TABLE IF NOT EXISTS shopping_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            template_name TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        -- Shopping template items
        CREATE TABLE IF NOT EXISTS shopping_template_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            category TEXT DEFAULT 'Uncategorized',
            priority INTEGER DEFAULT 2,
            estimated_price REAL,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY (template_id) REFERENCES shopping_templates(id) ON DELETE CASCADE
        );

        -- Shopping shares
        CREATE TABLE IF NOT EXISTS shopping_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            share_token TEXT UNIQUE NOT NULL,
            access_type TEXT DEFAULT 'view',
            expires_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    ''')
    db.commit()
    db.close()

def migrate_database():
    """Add new columns to existing tables if they don't exist"""
    db = sqlite3.connect(DB_PATH)
    cursor = db.cursor()

    # Check and add account_id to expenses
    cursor.execute("PRAGMA table_info(expenses)")
    expense_columns = [col[1] for col in cursor.fetchall()]
    if 'account_id' not in expense_columns:
        cursor.execute("ALTER TABLE expenses ADD COLUMN account_id INTEGER")

    # Check and add columns to shopping_list
    cursor.execute("PRAGMA table_info(shopping_list)")
    columns = [col[1] for col in cursor.fetchall()]
    for col, defn in [
        ('category',         "TEXT DEFAULT 'Uncategorized'"),
        ('priority',         "INTEGER DEFAULT 2"),
        ('estimated_price',  "REAL"),
        ('last_modified_by', "TEXT"),
    ]:
        if col not in columns:
            cursor.execute(f"ALTER TABLE shopping_list ADD COLUMN {col} {defn}")

    # Check and add columns to budgets
    cursor.execute("PRAGMA table_info(budgets)")
    budget_columns = [col[1] for col in cursor.fetchall()]
    for col, defn in [
        ('period_type',      "TEXT DEFAULT 'monthly'"),
        ('rollover_enabled', "INTEGER DEFAULT 0"),
        ('alert_threshold',  "INTEGER DEFAULT 80"),
    ]:
        if col not in budget_columns:
            cursor.execute(f"ALTER TABLE budgets ADD COLUMN {col} {defn}")

    # Ensure shopping_shares table exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS shopping_shares (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            share_token TEXT UNIQUE NOT NULL,
            access_type TEXT DEFAULT 'view',
            expires_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')

    db.commit()
    db.close()

def setup_default_accounts(user_id):
    """Create the 4 specific accounts for a new user"""
    db = get_db()
    existing = db.execute('SELECT COUNT(*) as count FROM accounts WHERE user_id=?', (user_id,)).fetchone()
    if existing['count'] > 0:
        return
    for account in ACCOUNTS_CONFIG:
        db.execute(
            'INSERT INTO accounts (user_id, name, type, color, currency, balance, initial_balance) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (user_id, account['name'], account['type'], account['color'], CURRENCY, 0, 0)
        )
    db.commit()

# Initialize database
init_db()
migrate_database()

# ── Auth Helpers ──────────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def current_user_id():
    return session.get('user_id')

# ── Account Helpers ───────────────────────────────────────────────────────────
def get_user_accounts(user_id):
    db = get_db()
    accounts = db.execute('''
        SELECT a.*, 
               COALESCE(a.balance, 0) as current_balance
        FROM accounts a
        WHERE a.user_id=? AND a.is_active=1
        ORDER BY
            CASE a.type
                WHEN 'mobile_money' THEN 1
                WHEN 'checking' THEN 2
                WHEN 'savings' THEN 3
                ELSE 4
            END,
            a.name
    ''', (user_id,)).fetchall()
    
    # Add formatted balance to each account
    result = []
    for acc in accounts:
        acc_dict = dict(acc)
        acc_dict['formatted_balance'] = f"{CURRENCY_SYMBOL} {acc_dict['current_balance']:,.2f}"
        result.append(acc_dict)
    return result

def update_account_balance(account_id, user_id):
    """Recalculate and update account balance based on all transactions"""
    db = get_db()
    account = db.execute(
        'SELECT initial_balance FROM accounts WHERE id=? AND user_id=?',
        (account_id, user_id)
    ).fetchone()
    if not account:
        return 0

    balance = account['initial_balance']

    income_total = db.execute(
        'SELECT COALESCE(SUM(amount), 0) as total FROM income WHERE account_id=? AND user_id=?',
        (account_id, user_id)
    ).fetchone()['total']
    balance += income_total

    expense_total = db.execute(
        'SELECT COALESCE(SUM(amount), 0) as total FROM expenses WHERE account_id=? AND user_id=?',
        (account_id, user_id)
    ).fetchone()['total']
    balance -= expense_total

    transfers_out = db.execute(
        'SELECT COALESCE(SUM(amount), 0) as total FROM transfers WHERE from_account_id=? AND user_id=?',
        (account_id, user_id)
    ).fetchone()['total']
    balance -= transfers_out

    transfers_in = db.execute(
        'SELECT COALESCE(SUM(amount), 0) as total FROM transfers WHERE to_account_id=? AND user_id=?',
        (account_id, user_id)
    ).fetchone()['total']
    balance += transfers_in

    db.execute('UPDATE accounts SET balance=? WHERE id=?', (balance, account_id))
    db.commit()
    return balance

def get_all_account_balances(user_id):
    accounts = get_user_accounts(user_id)
    balances = []
    total = 0
    for account in accounts:
        balance = update_account_balance(account['id'], user_id)
        balances.append({
            'id':               account['id'],
            'name':             account['name'],
            'type':             account['type'],
            'color':            account['color'],
            'balance':          balance,
            'initial_balance':  account.get('initial_balance', 0),
            'formatted_balance': f"{CURRENCY_SYMBOL} {balance:,.2f}"
        })
        total += balance
    return balances, total

def get_net_worth(user_id):
    _, total = get_all_account_balances(user_id)
    return total

def get_account_transactions(account_id, user_id, limit=100):
    """Get combined expense + income transactions for an account, sorted by date."""
    db = get_db()

    expenses = db.execute('''
        SELECT id, amount, description, expense_date as date,
               'expense' as type, category, subcategory
        FROM expenses
        WHERE account_id=? AND user_id=?
        ORDER BY expense_date DESC
        LIMIT ?
    ''', (account_id, user_id, limit)).fetchall()

    incomes = db.execute('''
        SELECT id, amount, source as description, income_date as date,
               'income' as type, category, '' as subcategory
        FROM income
        WHERE account_id=? AND user_id=?
        ORDER BY income_date DESC
        LIMIT ?
    ''', (account_id, user_id, limit)).fetchall()

    all_tx = [dict(r) for r in expenses] + [dict(r) for r in incomes]
    all_tx.sort(key=lambda x: x['date'], reverse=True)
    return all_tx[:limit]

def record_transfer(user_id, from_account_id, to_account_id, amount, description, transfer_date):
    db = get_db()
    db.execute(
        'INSERT INTO transfers (user_id, from_account_id, to_account_id, amount, description, transfer_date) '
        'VALUES (?, ?, ?, ?, ?, ?)',
        (user_id, from_account_id, to_account_id, amount, description, transfer_date)
    )
    db.commit()
    update_account_balance(from_account_id, user_id)
    update_account_balance(to_account_id, user_id)
    flash(f'Transferred {CURRENCY_SYMBOL} {amount:,.2f} successfully.', 'success')

# ── Date Filter Helpers ────────────────────────────────────────────────────────
def date_range_for_period(period, custom_start=None, custom_end=None):
    today = date.today()
    if period == '7days':
        return (today - timedelta(days=6)).isoformat(), today.isoformat()
    elif period == 'month':
        return today.replace(day=1).isoformat(), today.isoformat()
    elif period == '3months':
        start = (today.replace(day=1) - timedelta(days=60)).replace(day=1)
        return start.isoformat(), today.isoformat()
    elif period == 'year':
        return today.replace(month=1, day=1).isoformat(), today.isoformat()
    elif period == 'custom' and custom_start and custom_end:
        return custom_start, custom_end
    else:  # 'all'
        return '2000-01-01', today.isoformat()

# ── Chart Generation ──────────────────────────────────────────────────────────
PALETTE = {
    'Essential':       '#4f8ef7',
    'Recreation':      '#f7874f',
    'Savings':         '#2ecc71',
    'Income':          '#9b59b6',
    'Rent':            '#3a6fd8',
    'Food':            '#5bbf8a',
    'Transport':       '#9b6bdb',
    'Entertainment':   '#f7d74f',
    'Hobbies':         '#f7534f',
    'Eating out':      '#4fd6f7',
    'Utilities':       '#e67e22',
    'Shopping':        '#e74c3c',
    'Emergency Fund':  '#1abc9c',
    'Investment':      '#8e44ad',
    'Goals':           '#27ae60',
}
BG = '#0f1117'
FG = '#e8eaf6'

def generate_charts(user_id, period='month', custom_start=None, custom_end=None):
    db = get_db()
    start, end = date_range_for_period(period, custom_start, custom_end)

    rows = db.execute(
        'SELECT category, subcategory, amount FROM expenses '
        'WHERE user_id=? AND expense_date BETWEEN ? AND ?',
        (user_id, start, end)
    ).fetchall()

    pie_path = os.path.join(CHART_DIR, f'pie_{user_id}.png')
    bar_path = os.path.join(CHART_DIR, f'bar_{user_id}.png')

    if not rows:
        for p in (pie_path, bar_path):
            _empty_chart(p)
        return

    # Pie chart – by category
    cat_totals = {}
    for r in rows:
        cat_totals[r['category']] = cat_totals.get(r['category'], 0) + r['amount']

    fig, ax = plt.subplots(figsize=(5, 4), facecolor=BG)
    ax.set_facecolor(BG)
    labels = list(cat_totals.keys())
    sizes  = list(cat_totals.values())
    colors = [PALETTE.get(l, '#888') for l in labels]
    wedges, texts, autotexts = ax.pie(
        sizes, labels=None, colors=colors,
        autopct='%1.1f%%', startangle=140,
        wedgeprops=dict(width=0.6, edgecolor=BG, linewidth=2),
        pctdistance=0.75,
    )
    for at in autotexts:
        at.set_color(BG); at.set_fontsize(11); at.set_fontweight('bold')
    legend_patches = [
        mpatches.Patch(color=colors[i], label=f'{labels[i]}  {CURRENCY_SYMBOL} {sizes[i]:,.2f}')
        for i in range(len(labels))
    ]
    ax.legend(handles=legend_patches, loc='lower center', bbox_to_anchor=(0.5, -0.12),
              ncol=2, frameon=False, labelcolor=FG, fontsize=10)
    ax.set_title('Spending by Category', color=FG, fontsize=13, pad=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig(pie_path, dpi=130, bbox_inches='tight', facecolor=BG)
    plt.close()

    # Bar chart – by sub-category
    sub_totals = {}
    for r in rows:
        sub_totals[r['subcategory']] = sub_totals.get(r['subcategory'], 0) + r['amount']

    subs    = list(sub_totals.keys())
    amounts = [sub_totals[s] for s in subs]
    colors2 = [PALETTE.get(s, '#888') for s in subs]

    fig, ax = plt.subplots(figsize=(6, 4), facecolor=BG)
    ax.set_facecolor(BG)
    bars = ax.bar(subs, amounts, color=colors2, edgecolor=BG, linewidth=1.5, width=0.6)
    ax.set_xlabel('Sub-category', color=FG, fontsize=10)
    ax.set_ylabel(f'Amount ({CURRENCY_SYMBOL})', color=FG, fontsize=10)
    ax.set_title('Spending by Sub-category', color=FG, fontsize=13, pad=14, fontweight='bold')
    ax.tick_params(colors=FG, labelsize=9)
    ax.spines[['top', 'right', 'left', 'bottom']].set_color('#2a2d3e')
    ax.yaxis.grid(True, color='#2a2d3e', linewidth=0.8)
    ax.set_axisbelow(True)
    if amounts:
        for bar, val in zip(bars, amounts):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(amounts) * 0.01,
                    f'{CURRENCY_SYMBOL} {val:,.0f}', ha='center', va='bottom', color=FG, fontsize=8)
    plt.xticks(rotation=25, ha='right')
    plt.tight_layout()
    plt.savefig(bar_path, dpi=130, bbox_inches='tight', facecolor=BG)
    plt.close()

def _empty_chart(path):
    fig, ax = plt.subplots(figsize=(5, 3), facecolor=BG)
    ax.set_facecolor(BG)
    ax.text(0.5, 0.5, 'No data for this period', transform=ax.transAxes,
            ha='center', va='center', color='#555', fontsize=13)
    ax.axis('off')
    plt.tight_layout()
    plt.savefig(path, dpi=100, bbox_inches='tight', facecolor=BG)
    plt.close()

# ── Budget Helpers ────────────────────────────────────────────────────────────
def get_budget_status(user_id):
    db = get_db()
    today = date.today()
    month_start = today.replace(day=1).isoformat()

    budgets_rows = db.execute(
        'SELECT category, monthly_limit, period_type, rollover_enabled, alert_threshold '
        'FROM budgets WHERE user_id=?',
        (user_id,)
    ).fetchall()

    if not budgets_rows:
        return []

    spent = {}
    for r in db.execute(
        'SELECT category, SUM(amount) as total FROM expenses '
        'WHERE user_id=? AND expense_date >= ? GROUP BY category',
        (user_id, month_start)
    ):
        spent[r['category']] = r['total']

    status = []
    for budget in budgets_rows:
        cat   = budget['category']
        limit = budget['monthly_limit']
        used  = spent.get(cat, 0)
        pct   = round((used / limit * 100) if limit > 0 else 0, 1)
        level = 'over' if pct >= 100 else ('warn' if pct >= budget['alert_threshold'] else 'ok')
        status.append({
            'category':  cat,
            'limit':     limit,
            'spent':     used,
            'pct':       pct,
            'level':     level,
            'remaining': limit - used,
            'rollover':  0,
        })
    return status

def check_budget_alerts(user_id):
    status = get_budget_status(user_id)
    alerts = []
    for s in status:
        if s['pct'] >= 100:
            alerts.append(
                f"⚠️  {s['category']} is OVER budget by {CURRENCY_SYMBOL} {s['spent'] - s['limit']:,.2f}"
            )
        elif s['pct'] >= 80:
            alerts.append(
                f"📢  {s['category']} is at {s['pct']}% of budget "
                f"({CURRENCY_SYMBOL} {s['remaining']:,.2f} remaining)"
            )
    return alerts

# ── Shopping Helpers ──────────────────────────────────────────────────────────
def get_shopping_total(user_id):
    db = get_db()
    result = db.execute(
        'SELECT COALESCE(SUM(estimated_price), 0) as total, COUNT(*) as count '
        'FROM shopping_list WHERE user_id=? AND bought=0',
        (user_id,)
    ).fetchone()
    return result['total'], result['count']

def get_frequent_items(user_id, limit=8):
    """Return items frequently bought as expenses (used for shopping suggestions)."""
    db = get_db()
    rows = db.execute('''
        SELECT description, COUNT(*) as frequency, AVG(amount) as avg_price
        FROM expenses
        WHERE user_id=? AND description IS NOT NULL AND description != ''
        GROUP BY LOWER(description)
        ORDER BY frequency DESC
        LIMIT ?
    ''', (user_id, limit)).fetchall()
    return [dict(r) for r in rows]

def get_active_share_token(user_id):
    """Return the most recent non-expired share token for this user, or None."""
    db = get_db()
    row = db.execute('''
        SELECT share_token FROM shopping_shares
        WHERE user_id=?
          AND (expires_at IS NULL OR expires_at > datetime('now'))
        ORDER BY created_at DESC LIMIT 1
    ''', (user_id,)).fetchone()
    return row['share_token'] if row else None

# ══════════════════════════════════════════════════════════════════════════════
# Routes – Auth
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        db = get_db()
        if not username or not password:
            flash('Username and password are required.', 'error')
        elif db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone():
            flash('Username already taken.', 'error')
        else:
            db.execute('INSERT INTO users (username, password_hash) VALUES (?,?)',
                       (username, generate_password_hash(password)))
            db.commit()
            user = db.execute('SELECT id FROM users WHERE username=?', (username,)).fetchone()
            setup_default_accounts(user['id'])
            flash('Account created! Please log in.', 'success')
            return redirect(url_for('login'))
    return render_template('auth.html', mode='register')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        db = get_db()
        user = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        if user and check_password_hash(user['password_hash'], password):
            session['user_id']  = user['id']
            session['username'] = user['username']
            setup_default_accounts(user['id'])
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid credentials.', 'error')
    return render_template('auth.html', mode='login')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

# ══════════════════════════════════════════════════════════════════════════════
# Routes – Dashboard
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/')
@login_required
def dashboard():
    uid    = current_user_id()
    period = request.args.get('period', 'month')
    c_start = request.args.get('custom_start', '')
    c_end   = request.args.get('custom_end', '')

    generate_charts(uid, period, c_start, c_end)

    account_balances, total_balance = get_all_account_balances(uid)
    net_worth = total_balance

    db = get_db()
    start, end = date_range_for_period(period, c_start, c_end)

    recent = db.execute(
        'SELECT e.*, a.name as account_name FROM expenses e '
        'LEFT JOIN accounts a ON e.account_id = a.id '
        'WHERE e.user_id=? AND e.expense_date BETWEEN ? AND ? '
        'ORDER BY e.expense_date DESC LIMIT 5',
        (uid, start, end)
    ).fetchall()

    total = db.execute(
        'SELECT COALESCE(SUM(amount), 0) as t FROM expenses '
        'WHERE user_id=? AND expense_date BETWEEN ? AND ?',
        (uid, start, end)
    ).fetchone()['t']

    shopping_preview = db.execute(
        'SELECT * FROM shopping_list WHERE user_id=? AND bought=0 '
        'ORDER BY priority ASC, sort_order, id LIMIT 5',
        (uid,)
    ).fetchall()

    shopping_total, shopping_count = get_shopping_total(uid)
    budget_status  = get_budget_status(uid)
    budget_alerts  = check_budget_alerts(uid)

    ts      = int(datetime.now().timestamp())
    pie_url = url_for('static', filename=f'charts/pie_{uid}.png') + f'?v={ts}'
    bar_url = url_for('static', filename=f'charts/bar_{uid}.png') + f'?v={ts}'

    return render_template('dashboard.html',
        recent=recent, total=total,
        budget_status=budget_status, budget_alerts=budget_alerts,
        pie_url=pie_url, bar_url=bar_url,
        period=period, period_options=PERIOD_OPTIONS,
        custom_start=c_start, custom_end=c_end,
        shopping_preview=shopping_preview,
        shopping_total=shopping_total, shopping_count=shopping_count,
        account_balances=account_balances, total_balance=total_balance,
        net_worth=net_worth,
        currency_symbol=CURRENCY_SYMBOL,
    )

# ══════════════════════════════════════════════════════════════════════════════
# Routes – Accounts
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/accounts')
@login_required
def accounts():
    uid = current_user_id()
    db  = get_db()

    accounts_list = get_user_accounts(uid)
    account_data  = []
    for account in accounts_list:
        balance = update_account_balance(account['id'], uid)
        account_data.append({
            'id':               account['id'],
            'name':             account['name'],
            'type':             account['type'],
            'color':            account['color'],
            'balance':          balance,
            'initial_balance':  account.get('initial_balance', 0),
            'formatted_balance': f"{CURRENCY_SYMBOL} {balance:,.2f}",
        })

    all_recent = []
    for account in account_data:
        for t in get_account_transactions(account['id'], uid, 5):
            t['account_name'] = account['name']
            all_recent.append(t)

    all_recent.sort(key=lambda x: x['date'], reverse=True)
    recent_transactions = all_recent[:15]

    today_str = date.today().isoformat()

    return render_template('accounts.html',
        accounts=account_data,
        recent_transactions=recent_transactions,
        net_worth=sum(a['balance'] for a in account_data),
        currency_symbol=CURRENCY_SYMBOL,
        today_date=today_str,
    )

@app.route('/accounts/update_balance/<int:account_id>', methods=['POST'])
@login_required
def update_account_balance_route(account_id):
    uid = current_user_id()
    try:
        new_balance = float(request.form['balance'])
    except (ValueError, KeyError):
        flash('Invalid balance value.', 'error')
        return redirect(url_for('accounts'))

    db = get_db()
    db.execute('UPDATE accounts SET initial_balance=? WHERE id=? AND user_id=?',
               (new_balance, account_id, uid))
    db.commit()
    update_account_balance(account_id, uid)
    flash(f'Balance updated to {CURRENCY_SYMBOL} {new_balance:,.2f}.', 'success')
    return redirect(url_for('accounts'))

@app.route('/accounts/transfer', methods=['POST'])
@login_required
def transfer_money():
    uid = current_user_id()
    try:
        from_account  = int(request.form['from_account'])
        to_account    = int(request.form['to_account'])
        amount        = float(request.form['amount'])
    except (ValueError, KeyError):
        flash('Invalid transfer data.', 'error')
        return redirect(url_for('accounts'))

    description   = request.form.get('description', '').strip()
    transfer_date = request.form.get('transfer_date', date.today().isoformat())

    if from_account == to_account:
        flash('Cannot transfer to the same account.', 'error')
        return redirect(url_for('accounts'))
    if amount <= 0:
        flash('Amount must be greater than zero.', 'error')
        return redirect(url_for('accounts'))

    record_transfer(uid, from_account, to_account, amount, description, transfer_date)
    return redirect(url_for('accounts'))

@app.route('/accounts/transaction/<int:account_id>')
@login_required
def account_transactions(account_id):
    uid = current_user_id()
    db  = get_db()
    account = db.execute(
        'SELECT * FROM accounts WHERE id=? AND user_id=?', (account_id, uid)
    ).fetchone()
    if not account:
        flash('Account not found.', 'error')
        return redirect(url_for('accounts'))

    balance      = update_account_balance(account_id, uid)
    transactions = get_account_transactions(account_id, uid, 100)

    return render_template('account_transactions.html',
        account=account, balance=balance,
        transactions=transactions, currency_symbol=CURRENCY_SYMBOL,
    )

@app.route('/accounts/add_money', methods=['POST'])
@login_required
def add_money_to_account():
    """Quick way to add money directly to an account"""
    uid = current_user_id()
    try:
        account_id = int(request.form['account_id'])
        amount = float(request.form['amount'])
        source = request.form.get('source', 'Manual Deposit').strip()
        description = request.form.get('description', '').strip()
        income_date = request.form.get('income_date', date.today().isoformat())
    except (ValueError, KeyError):
        flash('Invalid amount or account selection.', 'error')
        return redirect(url_for('accounts'))
    
    if amount <= 0:
        flash('Amount must be greater than zero.', 'error')
        return redirect(url_for('accounts'))
    
    db = get_db()
    account = db.execute('SELECT id FROM accounts WHERE id=? AND user_id=?', (account_id, uid)).fetchone()
    if not account:
        flash('Account not found.', 'error')
        return redirect(url_for('accounts'))
    
    db.execute(
        'INSERT INTO income (user_id, amount, source, description, income_date, account_id, category) '
        'VALUES (?,?,?,?,?,?,?)',
        (uid, amount, source, description, income_date, account_id, 'Deposit')
    )
    db.commit()
    update_account_balance(account_id, uid)
    
    flash(f'Added {CURRENCY_SYMBOL} {amount:,.2f} to account successfully.', 'success')
    return redirect(url_for('accounts'))

@app.route('/accounts/edit_initial_balance/<int:account_id>', methods=['POST'])
@login_required
def edit_initial_balance(account_id):
    """Edit the initial balance (starting balance) of an account"""
    uid = current_user_id()
    try:
        initial_balance = float(request.form['initial_balance'])
    except (ValueError, KeyError):
        flash('Invalid balance value.', 'error')
        return redirect(url_for('accounts'))
    
    db = get_db()
    db.execute(
        'UPDATE accounts SET initial_balance=? WHERE id=? AND user_id=?',
        (initial_balance, account_id, uid)
    )
    db.commit()
    update_account_balance(account_id, uid)
    
    flash(f'Initial balance updated to {CURRENCY_SYMBOL} {initial_balance:,.2f}.', 'success')
    return redirect(url_for('accounts'))

@app.route('/accounts/edit/<int:account_id>', methods=['GET', 'POST'])
@login_required
def edit_account(account_id):
    """Edit account name, type, color, and initial balance"""
    uid = current_user_id()
    db  = get_db()

    account = db.execute(
        'SELECT * FROM accounts WHERE id=? AND user_id=?', (account_id, uid)
    ).fetchone()
    if not account:
        flash('Account not found.', 'error')
        return redirect(url_for('accounts'))

    if request.method == 'POST':
        name            = request.form.get('name', '').strip()
        account_type    = request.form.get('type', account['type'])
        color           = request.form.get('color', account['color'])
        initial_balance_str = request.form.get('initial_balance', '0')

        if not name:
            flash('Account name is required.', 'error')
            return redirect(url_for('edit_account', account_id=account_id))

        try:
            initial_balance = float(initial_balance_str)
        except ValueError:
            flash('Invalid balance value.', 'error')
            return redirect(url_for('edit_account', account_id=account_id))

        db.execute(
            'UPDATE accounts SET name=?, type=?, color=?, initial_balance=? WHERE id=? AND user_id=?',
            (name, account_type, color, initial_balance, account_id, uid)
        )
        db.commit()
        update_account_balance(account_id, uid)
        flash(f'Account "{name}" updated successfully.', 'success')
        return redirect(url_for('accounts'))

    balance = update_account_balance(account_id, uid)
    transactions = get_account_transactions(account_id, uid, 20)
    account_types = [
        ('mobile_money', 'Mobile Money'),
        ('checking',     'Checking'),
        ('savings',      'Savings'),
        ('cash',         'Cash'),
        ('investment',   'Investment'),
    ]
    return render_template('edit_account.html',
        account=account,
        balance=balance,
        transactions=transactions,
        account_types=account_types,
        currency_symbol=CURRENCY_SYMBOL,
    )

# ══════════════════════════════════════════════════════════════════════════════
# Routes – Expenses
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/expenses', methods=['GET', 'POST'])
@login_required
def expenses():
    uid = current_user_id()
    db  = get_db()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            try:
                amount = float(request.form['amount'])
            except ValueError:
                flash('Invalid amount.', 'error')
                return redirect(url_for('expenses'))

            description = request.form.get('description', '').strip()
            category    = request.form['category']
            subcategory = request.form['subcategory']
            exp_date    = request.form.get('expense_date') or date.today().isoformat()
            account_id  = request.form.get('account_id') or None
            if account_id:
                account_id = int(account_id)

            db.execute(
                'INSERT INTO expenses (user_id, amount, description, category, subcategory, expense_date, account_id) '
                'VALUES (?,?,?,?,?,?,?)',
                (uid, amount, description, category, subcategory, exp_date, account_id)
            )
            if account_id:
                update_account_balance(account_id, uid)
            db.commit()
            flash(f'Expense added: {CURRENCY_SYMBOL} {amount:,.2f}.', 'success')

        elif action == 'delete':
            expense = db.execute(
                'SELECT account_id FROM expenses WHERE id=? AND user_id=?',
                (request.form['expense_id'], uid)
            ).fetchone()
            db.execute('DELETE FROM expenses WHERE id=? AND user_id=?',
                       (request.form['expense_id'], uid))
            if expense and expense['account_id']:
                update_account_balance(expense['account_id'], uid)
            db.commit()
            flash('Expense deleted.', 'success')

        elif action == 'edit':
            old = db.execute(
                'SELECT account_id FROM expenses WHERE id=? AND user_id=?',
                (request.form['expense_id'], uid)
            ).fetchone()
            new_account_id = request.form.get('account_id') or None
            if new_account_id:
                new_account_id = int(new_account_id)

            db.execute(
                'UPDATE expenses SET amount=?, description=?, category=?, subcategory=?, '
                'expense_date=?, account_id=? WHERE id=? AND user_id=?',
                (float(request.form['amount']),
                 request.form.get('description', '').strip(),
                 request.form['category'],
                 request.form['subcategory'],
                 request.form['expense_date'],
                 new_account_id,
                 request.form['expense_id'], uid)
            )
            if old and old['account_id']:
                update_account_balance(old['account_id'], uid)
            if new_account_id:
                update_account_balance(new_account_id, uid)
            db.commit()
            flash('Expense updated.', 'success')

        generate_charts(uid)
        return redirect(url_for('expenses'))

    accounts_list = get_user_accounts(uid)
    for acc in accounts_list:
        acc['balance'] = update_account_balance(acc['id'], uid)
        acc['formatted_balance'] = f"{CURRENCY_SYMBOL} {acc['balance']:,.2f}"
    
    period         = request.args.get('period', 'all')
    c_start        = request.args.get('custom_start', '')
    c_end          = request.args.get('custom_end', '')
    cat_filter     = request.args.get('category_filter', '')
    account_filter = request.args.get('account_filter', '')
    start, end     = date_range_for_period(period, c_start, c_end)

    query  = ('SELECT e.*, a.name as account_name FROM expenses e '
              'LEFT JOIN accounts a ON e.account_id = a.id '
              'WHERE e.user_id=? AND e.expense_date BETWEEN ? AND ?')
    params = [uid, start, end]
    if cat_filter:
        query  += ' AND e.category=?'
        params.append(cat_filter)
    if account_filter:
        query  += ' AND e.account_id=?'
        params.append(int(account_filter))
    query += ' ORDER BY e.expense_date DESC'

    all_expenses = db.execute(query, params).fetchall()
    edit_id      = request.args.get('edit_id', type=int)

    return render_template('expenses.html',
        expenses=all_expenses, categories=CATEGORIES,
        period=period, period_options=PERIOD_OPTIONS,
        custom_start=c_start, custom_end=c_end,
        cat_filter=cat_filter, account_filter=account_filter,
        edit_id=edit_id, accounts_list=accounts_list,
        today=date.today().isoformat(),
        currency_symbol=CURRENCY_SYMBOL,
    )

@app.route('/expenses/export')
@login_required
def export_csv():
    uid = current_user_id()
    db  = get_db()
    rows = db.execute('''
        SELECT e.expense_date, e.category, e.subcategory, e.amount, e.description,
               a.name as account_name
        FROM expenses e
        LEFT JOIN accounts a ON e.account_id = a.id
        WHERE e.user_id=?
        ORDER BY e.expense_date DESC
    ''', (uid,)).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Category', 'Sub-category', f'Amount ({CURRENCY_SYMBOL})', 'Description', 'Account'])
    for r in rows:
        writer.writerow([r['expense_date'], r['category'], r['subcategory'],
                         f'{r["amount"]:.2f}', r['description'] or '', r['account_name'] or ''])
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=expenses.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

# ══════════════════════════════════════════════════════════════════════════════
# Routes – Income
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/income', methods=['GET', 'POST'])
@login_required
def income():
    uid = current_user_id()
    db  = get_db()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            try:
                amount = float(request.form['amount'])
            except ValueError:
                flash('Invalid amount.', 'error')
                return redirect(url_for('income'))
            source      = request.form['source'].strip()
            description = request.form.get('description', '').strip()
            income_date = request.form.get('income_date') or date.today().isoformat()
            account_id  = request.form.get('account_id') or None
            category    = request.form.get('category', 'Income')
            if account_id:
                account_id = int(account_id)

            db.execute(
                'INSERT INTO income (user_id, amount, source, description, income_date, account_id, category) '
                'VALUES (?,?,?,?,?,?,?)',
                (uid, amount, source, description, income_date, account_id, category)
            )
            if account_id:
                update_account_balance(account_id, uid)
            db.commit()
            flash(f'Income added: {CURRENCY_SYMBOL} {amount:,.2f}.', 'success')

        elif action == 'delete':
            record = db.execute(
                'SELECT account_id FROM income WHERE id=? AND user_id=?',
                (request.form['income_id'], uid)
            ).fetchone()
            db.execute('DELETE FROM income WHERE id=? AND user_id=?',
                       (request.form['income_id'], uid))
            if record and record['account_id']:
                update_account_balance(record['account_id'], uid)
            db.commit()
            flash('Income deleted.', 'success')

        return redirect(url_for('income'))

    accounts_list = get_user_accounts(uid)
    for acc in accounts_list:
        acc['balance'] = update_account_balance(acc['id'], uid)
        acc['formatted_balance'] = f"{CURRENCY_SYMBOL} {acc['balance']:,.2f}"
    
    all_income    = db.execute('''
        SELECT i.*, a.name as account_name
        FROM income i
        LEFT JOIN accounts a ON i.account_id = a.id
        WHERE i.user_id=?
        ORDER BY i.income_date DESC
    ''', (uid,)).fetchall()
    total_income = db.execute(
        'SELECT COALESCE(SUM(amount), 0) as total FROM income WHERE user_id=?', (uid,)
    ).fetchone()['total']

    return render_template('income.html',
        income_records=all_income, accounts_list=accounts_list,
        total_income=total_income, currency_symbol=CURRENCY_SYMBOL,
        today=date.today().isoformat(),
    )

# ══════════════════════════════════════════════════════════════════════════════
# Routes – Budgets (FIXED - no ON CONFLICT)
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/budgets', methods=['GET', 'POST'])
@login_required
def budgets():
    uid = current_user_id()
    db  = get_db()

    if request.method == 'POST':
        for cat in CATEGORIES:
            limit_val = request.form.get(f'budget_{cat}', '').strip()
            rollover  = 1 if request.form.get(f'rollover_{cat}') == 'on' else 0
            alert_threshold = int(request.form.get(f'alert_threshold_{cat}', 80))
            period_type     = request.form.get(f'period_type_{cat}', 'monthly')
            
            if limit_val and float(limit_val) > 0:
                # Check if budget already exists
                existing = db.execute(
                    'SELECT id FROM budgets WHERE user_id=? AND category=? AND period_type=?',
                    (uid, cat, period_type)
                ).fetchone()
                
                if existing:
                    # Update existing budget
                    db.execute(
                        'UPDATE budgets SET monthly_limit=?, rollover_enabled=?, alert_threshold=? '
                        'WHERE user_id=? AND category=? AND period_type=?',
                        (float(limit_val), rollover, alert_threshold, uid, cat, period_type)
                    )
                else:
                    # Insert new budget
                    db.execute(
                        'INSERT INTO budgets (user_id, category, monthly_limit, period_type, rollover_enabled, alert_threshold) '
                        'VALUES (?, ?, ?, ?, ?, ?)',
                        (uid, cat, float(limit_val), period_type, rollover, alert_threshold)
                    )
            else:
                # If limit is empty or zero, delete the budget
                db.execute(
                    'DELETE FROM budgets WHERE user_id=? AND category=?',
                    (uid, cat)
                )
        
        db.commit()
        flash('Budgets saved successfully.', 'success')
        return redirect(url_for('budgets'))

    # Build current dict with safe defaults
    budgets_rows = db.execute(
        'SELECT category, monthly_limit, period_type, rollover_enabled, alert_threshold '
        'FROM budgets WHERE user_id=?',
        (uid,)
    ).fetchall()

    current = {}
    for row in budgets_rows:
        current[row['category']] = {
            'limit':            row['monthly_limit'],
            'period_type':      row['period_type'] or 'monthly',
            'rollover_enabled': row['rollover_enabled'],
            'alert_threshold':  row['alert_threshold'],
        }
    # Ensure every category has a safe default
    for cat in CATEGORIES:
        current.setdefault(cat, {
            'limit': '', 'period_type': 'monthly',
            'rollover_enabled': 0, 'alert_threshold': 80,
        })

    status = get_budget_status(uid)

    return render_template('budgets.html',
        categories=CATEGORIES, current=current,
        status=status, period_options=PERIOD_OPTIONS_BUDGET,
        currency_symbol=CURRENCY_SYMBOL,
    )

@app.route('/budgets/history')
@login_required
def budgets_history():
    uid = current_user_id()
    db  = get_db()
    today      = date.today()
    results    = []
    
    all_cats = set()
    cat_rows = db.execute('SELECT DISTINCT category FROM expenses WHERE user_id=?', (uid,)).fetchall()
    for row in cat_rows:
        all_cats.add(row['category'])
    
    for cat in CATEGORIES.keys():
        all_cats.add(cat)
    
    for i in range(5, -1, -1):
        month_date = date(today.year, today.month, 1)
        for _ in range(5 - i):
            month_date = month_date.replace(day=1) - timedelta(days=1)
        month_date = month_date.replace(day=1)
        
        if month_date.month == 12:
            month_end = date(month_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(month_date.year, month_date.month + 1, 1) - timedelta(days=1)
        
        month_label = month_date.strftime('%b %Y')

        rows = db.execute('''
            SELECT category, SUM(amount) as spent
            FROM expenses
            WHERE user_id=? AND expense_date BETWEEN ? AND ?
            GROUP BY category
        ''', (uid, month_date.isoformat(), month_end.isoformat())).fetchall()
        
        spent_dict = {r['category']: round(r['spent'], 2) for r in rows}
        
        cat_data = []
        for cat in sorted(all_cats):
            cat_data.append({'category': cat, 'spent': spent_dict.get(cat, 0)})
        
        results.append({'month': month_label, 'categories': cat_data})
    return jsonify(results)

# ══════════════════════════════════════════════════════════════════════════════
# Routes – Shopping
# ══════════════════════════════════════════════════════════════════════════════
@app.route('/shopping', methods=['GET', 'POST'])
@login_required
def shopping():
    uid = current_user_id()
    db  = get_db()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add':
            name = request.form['item_name'].strip()
            category       = request.form.get('category', 'Uncategorized')
            priority       = int(request.form.get('priority', 2))
            estimated_price = request.form.get('estimated_price', '')
            estimated_price = float(estimated_price) if estimated_price else None
            if name:
                max_order = db.execute(
                    'SELECT COALESCE(MAX(sort_order),0) FROM shopping_list WHERE user_id=?', (uid,)
                ).fetchone()[0]
                db.execute(
                    'INSERT INTO shopping_list '
                    '(user_id, item_name, category, priority, estimated_price, sort_order, last_modified_by) '
                    'VALUES (?,?,?,?,?,?,?)',
                    (uid, name, category, priority, estimated_price, max_order + 1, session.get('username'))
                )
                db.commit()
                flash('Item added.', 'success')

        elif action == 'delete':
            db.execute('DELETE FROM shopping_list WHERE id=? AND user_id=?',
                       (request.form['item_id'], uid))
            db.commit()
            flash('Item removed.', 'success')

        elif action == 'bulk_update':
            checked_ids = set(request.form.getlist('checked_items'))
            all_items   = db.execute('SELECT id FROM shopping_list WHERE user_id=?', (uid,)).fetchall()
            for item in all_items:
                db.execute('UPDATE shopping_list SET bought=? WHERE id=?',
                           (1 if str(item['id']) in checked_ids else 0, item['id']))
            db.commit()
            flash('List updated.', 'success')

        elif action == 'edit':
            new_name = request.form['item_name'].strip()
            category = request.form.get('category', 'Uncategorized')
            priority = int(request.form.get('priority', 2))
            estimated_price = request.form.get('estimated_price', '')
            estimated_price = float(estimated_price) if estimated_price else None
            if new_name:
                db.execute(
                    'UPDATE shopping_list SET item_name=?, category=?, priority=?, estimated_price=? '
                    'WHERE id=? AND user_id=?',
                    (new_name, category, priority, estimated_price, request.form['item_id'], uid)
                )
                db.commit()
                flash('Item updated.', 'success')

        elif action == 'clear_bought':
            db.execute('DELETE FROM shopping_list WHERE user_id=? AND bought=1', (uid,))
            db.commit()
            flash('Cleared bought items.', 'success')

        elif action == 'convert_to_expense':
            item_id = request.form['item_id']
            item = db.execute(
                'SELECT * FROM shopping_list WHERE id=? AND user_id=?', (item_id, uid)
            ).fetchone()
            if item and item['estimated_price']:
                db.execute(
                    'INSERT INTO expenses (user_id, amount, description, category, subcategory, expense_date) '
                    'VALUES (?,?,?,?,?,?)',
                    (uid, item['estimated_price'], item['item_name'],
                     'Recreation', 'Shopping', date.today().isoformat())
                )
                db.execute('UPDATE shopping_list SET bought=1 WHERE id=?', (item_id,))
                db.commit()
                flash(f'Converted "{item["item_name"]}" to expense.', 'success')

        elif action == 'create_template':
            template_name = request.form.get('template_name', '').strip()
            if template_name:
                cursor = db.execute(
                    'INSERT INTO shopping_templates (user_id, template_name) VALUES (?,?)',
                    (uid, template_name)
                )
                template_id = cursor.lastrowid
                current_items = db.execute(
                    'SELECT * FROM shopping_list WHERE user_id=? AND bought=0', (uid,)
                ).fetchall()
                for it in current_items:
                    db.execute(
                        'INSERT INTO shopping_template_items '
                        '(template_id, item_name, category, priority, estimated_price, sort_order) '
                        'VALUES (?,?,?,?,?,?)',
                        (template_id, it['item_name'], it['category'],
                         it['priority'], it['estimated_price'], it['sort_order'])
                    )
                db.commit()
                flash(f'Template "{template_name}" saved.', 'success')

        elif action == 'apply_template':
            template_id = request.form.get('template_id')
            if template_id:
                tmpl = db.execute(
                    'SELECT id FROM shopping_templates WHERE id=? AND user_id=?',
                    (template_id, uid)
                ).fetchone()
                if tmpl:
                    items = db.execute(
                        'SELECT * FROM shopping_template_items WHERE template_id=?', (template_id,)
                    ).fetchall()
                    max_order = db.execute(
                        'SELECT COALESCE(MAX(sort_order),0) FROM shopping_list WHERE user_id=?', (uid,)
                    ).fetchone()[0]
                    for it in items:
                        max_order += 1
                        db.execute(
                            'INSERT INTO shopping_list '
                            '(user_id, item_name, category, priority, estimated_price, sort_order) '
                            'VALUES (?,?,?,?,?,?)',
                            (uid, it['item_name'], it['category'],
                             it['priority'], it['estimated_price'], max_order)
                        )
                    db.commit()
                    flash('Template applied.', 'success')

        return redirect(url_for('shopping'))

    edit_id         = request.args.get('edit_id', type=int)
    category_filter = request.args.get('category_filter', '')
    priority_filter = request.args.get('priority_filter', '')

    query  = 'SELECT * FROM shopping_list WHERE user_id=?'
    params = [uid]
    if category_filter:
        query  += ' AND category=?'
        params.append(category_filter)
    if priority_filter:
        query  += ' AND priority=?'
        params.append(int(priority_filter))
    query += ' ORDER BY bought ASC, priority ASC, sort_order, id'

    items     = db.execute(query, params).fetchall()
    templates = db.execute(
        'SELECT * FROM shopping_templates WHERE user_id=? ORDER BY created_at DESC', (uid,)
    ).fetchall()

    shopping_total, shopping_count = get_shopping_total(uid)
    frequent_items  = get_frequent_items(uid)
    share_token     = get_active_share_token(uid)

    return render_template('shopping.html',
        items=items, edit_id=edit_id,
        categories=SHOPPING_CATEGORIES, priority_options=PRIORITY_OPTIONS,
        category_filter=category_filter, priority_filter=priority_filter,
        templates=templates,
        shopping_total=shopping_total, shopping_count=shopping_count,
        frequent_items=frequent_items, share_token=share_token,
        currency_symbol=CURRENCY_SYMBOL,
    )

@app.route('/shopping/share', methods=['POST'])
@login_required
def create_share_link():
    uid         = current_user_id()
    db          = get_db()
    access_type = request.form.get('access_type', 'view')
    expires_days = int(request.form.get('expires_days', 7))
    expires_at  = (datetime.now() + timedelta(days=expires_days)).strftime('%Y-%m-%d %H:%M:%S')
    token       = secrets.token_urlsafe(24)

    db.execute('DELETE FROM shopping_shares WHERE user_id=?', (uid,))
    db.execute(
        'INSERT INTO shopping_shares (user_id, share_token, access_type, expires_at) VALUES (?,?,?,?)',
        (uid, token, access_type, expires_at)
    )
    db.commit()

    share_url = url_for('shared_shopping_list', token=token, _external=True)
    return jsonify({'share_url': share_url, 'token': token})

@app.route('/shopping/shared/<token>', methods=['GET', 'POST'])
def shared_shopping_list(token):
    db    = get_db()
    share = db.execute(
        "SELECT * FROM shopping_shares WHERE share_token=? "
        "AND (expires_at IS NULL OR expires_at > datetime('now'))",
        (token,)
    ).fetchone()

    if not share:
        flash('This share link is invalid or has expired.', 'error')
        return redirect(url_for('login'))

    uid      = share['user_id']
    can_edit = share['access_type'] == 'edit'

    if request.method == 'POST' and can_edit:
        action = request.form.get('action')
        if action == 'add':
            name = request.form['item_name'].strip()
            if name:
                max_order = db.execute(
                    'SELECT COALESCE(MAX(sort_order),0) FROM shopping_list WHERE user_id=?', (uid,)
                ).fetchone()[0]
                db.execute(
                    'INSERT INTO shopping_list (user_id, item_name, sort_order) VALUES (?,?,?)',
                    (uid, name, max_order + 1)
                )
                db.commit()
        elif action == 'delete':
            db.execute('DELETE FROM shopping_list WHERE id=? AND user_id=?',
                       (request.form['item_id'], uid))
            db.commit()
        elif action == 'bulk_update':
            checked_ids = set(request.form.getlist('checked_items'))
            all_items   = db.execute('SELECT id FROM shopping_list WHERE user_id=?', (uid,)).fetchall()
            for item in all_items:
                db.execute('UPDATE shopping_list SET bought=? WHERE id=?',
                           (1 if str(item['id']) in checked_ids else 0, item['id']))
            db.commit()
        return redirect(url_for('shared_shopping_list', token=token))

    items = db.execute(
        'SELECT * FROM shopping_list WHERE user_id=? ORDER BY bought ASC, priority ASC, sort_order',
        (uid,)
    ).fetchall()

    return render_template('shared_shopping.html',
        items=items, can_edit=can_edit, share_token=token,
        priority_options=PRIORITY_OPTIONS,
        currency_symbol=CURRENCY_SYMBOL,
    )

@app.route('/shopping/export')
@login_required
def export_shopping():
    uid = current_user_id()
    db  = get_db()
    items = db.execute(
        'SELECT item_name, category, '
        'CASE priority WHEN 1 THEN "High" WHEN 2 THEN "Medium" ELSE "Low" END as priority, '
        'estimated_price, '
        'CASE WHEN bought=1 THEN "Yes" ELSE "No" END as bought '
        'FROM shopping_list WHERE user_id=? ORDER BY bought, priority',
        (uid,)
    ).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Item', 'Category', 'Priority', f'Estimated Price ({CURRENCY_SYMBOL})', 'Bought'])
    total_estimate = 0
    for item in items:
        price = item['estimated_price'] or 0
        if item['bought'] == 'No':
            total_estimate += price
        writer.writerow([item['item_name'], item['category'], item['priority'],
                         f'{price:.2f}' if price else '-', item['bought']])
    writer.writerow([])
    writer.writerow([f'Total estimated cost for unchecked items ({CURRENCY_SYMBOL}):', f'{total_estimate:.2f}'])
    output.seek(0)
    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=shopping_list.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

@app.route('/shopping/print')
@login_required
def print_shopping():
    uid = current_user_id()
    db  = get_db()
    items = db.execute(
        'SELECT * FROM shopping_list WHERE user_id=? AND bought=0 '
        'ORDER BY priority ASC, category, sort_order',
        (uid,)
    ).fetchall()
    total, _ = get_shopping_total(uid)
    grouped  = defaultdict(list)
    for item in items:
        grouped[item['category']].append(item)

    return render_template('shopping_print.html',
        grouped_items=grouped, total=total,
        date=date.today().strftime('%B %d, %Y'),
        currency_symbol=CURRENCY_SYMBOL,
    )

# ── Run ────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(debug=True)