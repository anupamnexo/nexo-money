"""
Nexo.money - Corporate Card & Expense Management Platform
Database models and utilities for Indian SMEs
With Role-Based Access Control (RBAC)
"""

import sqlite3
import hashlib
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

# Database path
DB_PATH = Path(__file__).parent / "nexo.db"

# ============================================================
# RBAC Constants
# ============================================================

# Role hierarchy (lower number = higher privilege)
ROLE_HIERARCHY = {
    "super_admin": 0,
    "company_admin": 1,
    "admin": 2,
    "manager": 3,
    "employee": 4,
}

# What each role can do
ROLE_PERMISSIONS = {
    "super_admin": [
        "platform_manage", "company_create", "company_manage", "all_data",
    ],
    "company_admin": [
        "company_settings", "user_manage", "card_issue", "card_manage",
        "expense_approve", "expense_view_all", "expense_submit",
        "team_manage", "analytics", "gst", "budget_manage",
    ],
    "admin": [
        "card_issue", "card_manage", "expense_approve", "expense_view_all",
        "expense_submit", "team_view", "analytics", "gst", "budget_manage",
    ],
    "manager": [
        "expense_approve_team", "expense_view_team", "team_view_own",
        "expense_submit", "card_view_own",
    ],
    "employee": [
        "expense_submit", "expense_view_own", "card_view_own",
    ],
}

VALID_ROLES = list(ROLE_HIERARCHY.keys())


def role_level(role):
    """Get numeric level of a role (lower = more privileged)."""
    return ROLE_HIERARCHY.get(role, 99)


def has_permission(role, permission):
    """Check if a role has a specific permission."""
    return permission in ROLE_PERMISSIONS.get(role, [])


def is_role_at_least(user_role, min_role):
    """Check if user_role is at least as privileged as min_role."""
    return role_level(user_role) <= role_level(min_role)


# ============================================================
# Database Setup
# ============================================================

def init_db():
    """Initialize database with all required tables."""
    conn = get_db()
    cursor = conn.cursor()

    # Companies table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            gstin TEXT UNIQUE,
            pan TEXT UNIQUE,
            industry TEXT,
            city TEXT,
            plan TEXT DEFAULT 'free',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Users table (company_id nullable for super_admin)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'employee',
            company_id INTEGER,
            department TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)

    # User teams (manager-employee relationships)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            manager_id INTEGER,
            team_name TEXT,
            company_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (manager_id) REFERENCES users(id),
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)

    # Company settings (approval thresholds, etc.)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS company_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL UNIQUE,
            auto_approve_threshold REAL DEFAULT 5000,
            manager_approval_limit REAL DEFAULT 50000,
            admin_approval_limit REAL DEFAULT 200000,
            requires_manager_approval INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)

    # Cards table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            card_number TEXT NOT NULL,
            card_type TEXT DEFAULT 'virtual',
            status TEXT DEFAULT 'active',
            daily_limit REAL DEFAULT 50000,
            monthly_limit REAL DEFAULT 500000,
            spent_today REAL DEFAULT 0,
            spent_month REAL DEFAULT 0,
            merchant_category_restriction TEXT,
            issued_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (issued_by) REFERENCES users(id)
        )
    """)

    # Expenses table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            card_id INTEGER,
            amount REAL NOT NULL,
            currency TEXT DEFAULT 'INR',
            merchant_name TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT,
            receipt_url TEXT,
            gstin_vendor TEXT,
            gst_amount REAL DEFAULT 0,
            igst REAL DEFAULT 0,
            cgst REAL DEFAULT 0,
            sgst REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            approved_by INTEGER,
            approval_level INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (card_id) REFERENCES cards(id),
            FOREIGN KEY (approved_by) REFERENCES users(id)
        )
    """)

    # Approvals table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            expense_id INTEGER NOT NULL,
            approver_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            comment TEXT,
            approval_level INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (expense_id) REFERENCES expenses(id),
            FOREIGN KEY (approver_id) REFERENCES users(id)
        )
    """)

    # Budgets table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            team TEXT,
            category TEXT,
            monthly_limit REAL NOT NULL,
            spent_this_month REAL DEFAULT 0,
            period TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)

    # Vendors table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            gstin TEXT,
            total_spent REAL DEFAULT 0,
            transaction_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)

    # Waitlist table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            company_name TEXT,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ========== Schema Migration ==========
    # Add missing columns to existing tables (handles upgrades from pre-RBAC schema)
    def add_column_if_missing(cursor, table, column, col_type):
        cols = [row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            try:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except Exception:
                pass

    # Users table migrations
    add_column_if_missing(cursor, 'users', 'department', 'TEXT')
    add_column_if_missing(cursor, 'users', 'status', "TEXT DEFAULT 'active'")

    # Expenses table migrations
    add_column_if_missing(cursor, 'expenses', 'approval_level', 'INTEGER DEFAULT 0')

    # Approvals table migrations
    add_column_if_missing(cursor, 'approvals', 'approval_level', 'INTEGER DEFAULT 1')

    # Make users.company_id nullable (needed for super_admin who has no company)
    # SQLite doesn't support ALTER COLUMN, so we rebuild the table if needed
    try:
        # Check if company_id is NOT NULL in current schema
        table_info = cursor.execute("PRAGMA table_info(users)").fetchall()
        for col in table_info:
            if col[1] == 'company_id' and col[3] == 1:  # col[3] is notnull flag
                # Rebuild table with nullable company_id
                cursor.execute("""
                    CREATE TABLE users_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        email TEXT UNIQUE NOT NULL,
                        password_hash TEXT NOT NULL,
                        name TEXT NOT NULL,
                        role TEXT DEFAULT 'employee',
                        company_id INTEGER,
                        department TEXT,
                        status TEXT DEFAULT 'active',
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                cursor.execute("""
                    INSERT INTO users_new (id, email, password_hash, name, role, company_id, department, status, created_at)
                    SELECT id, email, password_hash, name, role, company_id, department, status, created_at FROM users
                """)
                cursor.execute("DROP TABLE users")
                cursor.execute("ALTER TABLE users_new RENAME TO users")
                break
    except Exception:
        pass

    # Migrate old role names to new ones
    cursor.execute("UPDATE users SET role='company_admin' WHERE role='admin'")
    cursor.execute("UPDATE users SET role='manager' WHERE role='approver'")

    conn.commit()
    conn.close()


def get_db():
    """Get database connection."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def hash_password(password):
    """Hash password with salt using SHA256."""
    salt = os.urandom(32)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt.hex() + ':' + pwd_hash.hex()


def verify_password(stored_hash, password):
    """Verify password against stored hash."""
    try:
        salt_hex, pwd_hash = stored_hash.split(':')
        salt = bytes.fromhex(salt_hex)
        pwd_hash_check = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
        return pwd_hash_check.hex() == pwd_hash
    except Exception:
        return False


def get_team_member_ids(conn, manager_id, company_id):
    """Get list of user IDs that report to a manager."""
    cursor = conn.cursor()
    cursor.execute("""
        SELECT user_id FROM user_teams
        WHERE manager_id = ? AND company_id = ?
    """, (manager_id, company_id))
    return [row["user_id"] for row in cursor.fetchall()]


def get_company_settings(conn, company_id):
    """Get company settings, with defaults."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM company_settings WHERE company_id = ?", (company_id,))
    row = cursor.fetchone()
    if row:
        return dict(row)
    return {
        "auto_approve_threshold": 5000,
        "manager_approval_limit": 50000,
        "admin_approval_limit": 200000,
        "requires_manager_approval": 1,
    }


# ============================================================
# Demo Data Seeder
# ============================================================

def seed_demo_data():
    """Populate database with realistic demo data."""
    conn = get_db()
    cursor = conn.cursor()

    try:
        # Clear existing data
        for table in ["approvals", "expenses", "cards", "user_teams",
                      "company_settings", "users", "budgets", "vendors", "companies"]:
            cursor.execute(f"DELETE FROM {table}")

        # ---- Super Admin (platform-level, no company) ----
        sa_hash = hash_password("admin123")
        cursor.execute("""
            INSERT INTO users (email, password_hash, name, role, company_id, department, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ("platform@nexo.money", sa_hash, "Platform Admin", "super_admin", None, "Platform", "active"))
        super_admin_id = cursor.lastrowid

        # ---- Company 1: TechNova Solutions ----
        cursor.execute("""
            INSERT INTO companies (name, gstin, pan, industry, city, plan)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("TechNova Solutions", "29AABCT1234P1Z5", "AABCT1234P", "SaaS", "Bangalore", "premium"))
        company1_id = cursor.lastrowid

        # Company 1 settings
        cursor.execute("""
            INSERT INTO company_settings (company_id, auto_approve_threshold, manager_approval_limit, admin_approval_limit, requires_manager_approval)
            VALUES (?, ?, ?, ?, ?)
        """, (company1_id, 5000, 50000, 200000, 1))

        # Company 1 team
        team1_data = [
            ("priya.shah@technova.com", "Priya Shah", "company_admin", "Management"),
            ("rajesh.kumar@technova.com", "Rajesh Kumar", "admin", "Finance"),
            ("deepak.gupta@technova.com", "Deepak Gupta", "manager", "Engineering"),
            ("neha.patel@technova.com", "Neha Patel", "employee", "Engineering"),
            ("amit.singh@technova.com", "Amit Singh", "employee", "Engineering"),
            ("anjali.verma@technova.com", "Anjali Verma", "employee", "Sales"),
        ]

        user_ids = {}
        for email, name, role, dept in team1_data:
            pwd_hash = hash_password("demo123")
            cursor.execute("""
                INSERT INTO users (email, password_hash, name, role, company_id, department, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (email, pwd_hash, name, role, company1_id, dept, "active"))
            user_ids[name] = cursor.lastrowid

        # Set up team relationships: Deepak (manager) manages Neha, Amit, Anjali
        for emp_name in ["Neha Patel", "Amit Singh", "Anjali Verma"]:
            cursor.execute("""
                INSERT INTO user_teams (user_id, manager_id, team_name, company_id)
                VALUES (?, ?, ?, ?)
            """, (user_ids[emp_name], user_ids["Deepak Gupta"], "Engineering", company1_id))

        # ---- Company 2: GreenLeaf Organics ----
        cursor.execute("""
            INSERT INTO companies (name, gstin, pan, industry, city, plan)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("GreenLeaf Organics", "07AABCG5678Q1Z3", "AABCG5678Q", "Agriculture", "Delhi", "starter"))
        company2_id = cursor.lastrowid

        # Company 2 settings
        cursor.execute("""
            INSERT INTO company_settings (company_id, auto_approve_threshold, manager_approval_limit, admin_approval_limit, requires_manager_approval)
            VALUES (?, ?, ?, ?, ?)
        """, (company2_id, 3000, 30000, 100000, 1))

        # Company 2 team
        team2_data = [
            ("vikram.mehta@greenleaf.com", "Vikram Mehta", "company_admin", "Management"),
            ("sonia.kapoor@greenleaf.com", "Sonia Kapoor", "employee", "Operations"),
            ("ravi.sharma@greenleaf.com", "Ravi Sharma", "employee", "Sales"),
        ]

        for email, name, role, dept in team2_data:
            pwd_hash = hash_password("demo123")
            cursor.execute("""
                INSERT INTO users (email, password_hash, name, role, company_id, department, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (email, pwd_hash, name, role, company2_id, dept, "active"))
            user_ids[name] = cursor.lastrowid

        # ---- Cards for Company 1 ----
        card_data = [
            (user_ids["Neha Patel"], "virtual", 25000, 150000),
            (user_ids["Neha Patel"], "physical", 25000, 150000),
            (user_ids["Amit Singh"], "virtual", 30000, 200000),
            (user_ids["Amit Singh"], "physical", 30000, 200000),
            (user_ids["Anjali Verma"], "virtual", 25000, 150000),
            (user_ids["Priya Shah"], "virtual", 50000, 500000),
            (user_ids["Rajesh Kumar"], "virtual", 40000, 300000),
            (user_ids["Deepak Gupta"], "virtual", 35000, 250000),
            (user_ids["Neha Patel"], "virtual", 20000, 100000),
            (user_ids["Amit Singh"], "virtual", 25000, 150000),
            (user_ids["Anjali Verma"], "virtual", 30000, 200000),
            (user_ids["Priya Shah"], "physical", 50000, 500000),
        ]

        card_ids = []
        for i, (user_id, card_type, daily, monthly) in enumerate(card_data, 1):
            last_four = str(4500 + i).zfill(4)
            masked = f"**** **** **** {last_four}"
            cursor.execute("""
                INSERT INTO cards (company_id, user_id, card_number, card_type, daily_limit, monthly_limit, issued_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (company1_id, user_id, masked, card_type, daily, monthly, user_ids["Priya Shah"]))
            card_ids.append(cursor.lastrowid)

        # Cards for Company 2
        for i, (user_id, card_type, daily, monthly) in enumerate([
            (user_ids["Sonia Kapoor"], "virtual", 20000, 100000),
            (user_ids["Ravi Sharma"], "virtual", 20000, 100000),
        ], 13):
            last_four = str(4500 + i).zfill(4)
            masked = f"**** **** **** {last_four}"
            cursor.execute("""
                INSERT INTO cards (company_id, user_id, card_number, card_type, daily_limit, monthly_limit, issued_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (company2_id, user_id, masked, card_type, daily, monthly, user_ids["Vikram Mehta"]))

        # ---- Budgets for Company 1 ----
        budgets = [
            ("Engineering", "software", 500000, "2026-03"),
            ("Sales", "travel", 300000, "2026-03"),
            ("Operations", "office", 200000, "2026-03"),
            ("HR", "meals", 100000, "2026-03"),
            (None, "marketing", 250000, "2026-03"),
        ]
        for team, category, limit, period in budgets:
            cursor.execute("""
                INSERT INTO budgets (company_id, team, category, monthly_limit, period)
                VALUES (?, ?, ?, ?, ?)
            """, (company1_id, team, category, limit, period))

        # ---- Vendors for Company 1 ----
        vendors_list = [
            ("Uber", "18AAFCU5055K1ZO"),
            ("Zomato", "09AAACR5055K2Z0"),
            ("OYO Rooms", "29AAFCM1234P1Z0"),
            ("AWS India", "18AAHCU3044R1Z2"),
            ("Google Cloud", "27AAACR6789P1Z0"),
        ]
        vendor_ids = {}
        for name, gstin in vendors_list:
            cursor.execute("""
                INSERT INTO vendors (company_id, name, gstin)
                VALUES (?, ?, ?)
            """, (company1_id, name, gstin))
            vendor_ids[name] = cursor.lastrowid

        # ---- Expenses for Company 1 ----
        categories = ["travel", "meals", "office", "software", "marketing", "other"]
        merchants = {
            "travel": ["Uber", "Ola", "IndiGo", "SpiceJet", "MakeMyTrip"],
            "meals": ["Zomato", "Swiggy", "CoffeeDay", "DomosFood", "RestaurantX"],
            "office": ["Amazon", "Flipkart", "LocalOfficeSupply", "StationeryPlus"],
            "software": ["AWS India", "Google Cloud", "Slack", "Jira", "GitHub"],
            "marketing": ["FacebookAds", "GoogleAds", "LinkedInAds", "ContentWriter"],
            "other": ["MiscExpense1", "MiscExpense2", "Repairs", "Utilities"],
        }

        now = datetime.now()
        expenses_created = 0

        for days_back in range(180, -1, -15):
            for _ in range(14):
                exp_date = now - timedelta(days=days_back)
                category = categories[expenses_created % len(categories)]
                merchant = merchants[category][expenses_created % len(merchants[category])]

                if category == "software":
                    amount = 5000 + (expenses_created * 73) % 25000
                elif category == "travel":
                    amount = 2000 + (expenses_created * 89) % 35000
                elif category == "meals":
                    amount = 500 + (expenses_created * 67) % 3000
                elif category == "office":
                    amount = 1000 + (expenses_created * 91) % 8000
                else:
                    amount = 1500 + (expenses_created * 79) % 10000

                auto_approve = amount < 5000
                gst_rate = 0.05 if amount < 5000 else 0.18
                gst_amount = amount * gst_rate
                igst = gst_amount * 0.8
                cgst = gst_amount * 0.1
                sgst = gst_amount * 0.1

                card_id = card_ids[expenses_created % len(card_ids)]
                emp_names = ["Neha Patel", "Amit Singh", "Anjali Verma"]
                user_id = user_ids[emp_names[expenses_created % 3]]

                status = "auto_approved" if auto_approve else "pending"
                approved_by = user_ids["Deepak Gupta"] if auto_approve else None

                cursor.execute("""
                    INSERT INTO expenses (
                        company_id, user_id, card_id, amount, merchant_name, category,
                        description, gstin_vendor, gst_amount, igst, cgst, sgst,
                        status, approved_by, approval_level, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    company1_id, user_id, card_id, amount, merchant, category,
                    f"Business expense for {category}", vendor_ids.get(merchant),
                    gst_amount, igst, cgst, sgst,
                    status, approved_by, 0 if auto_approve else 1,
                    exp_date.isoformat()
                ))

                expense_id = cursor.lastrowid

                if not auto_approve:
                    # Assign to manager (Deepak) for approval
                    cursor.execute("""
                        INSERT INTO approvals (expense_id, approver_id, status, approval_level, created_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (expense_id, user_ids["Deepak Gupta"], "pending", 1, exp_date.isoformat()))

                expenses_created += 1

        conn.commit()
        print(f"Demo data seeded: {expenses_created} expenses, 2 companies, 9 users, 5 roles")
        print("Demo logins:")
        print("  Super Admin:   platform@nexo.money / admin123")
        print("  Company Admin: priya.shah@technova.com / demo123")
        print("  Admin:         rajesh.kumar@technova.com / demo123")
        print("  Manager:       deepak.gupta@technova.com / demo123")
        print("  Employee:      neha.patel@technova.com / demo123")

    except Exception as e:
        conn.rollback()
        print(f"Error seeding demo data: {e}")
        raise
    finally:
        conn.close()


# Quick test
if __name__ == "__main__":
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
    seed_demo_data()
    print("Database initialized successfully!")
