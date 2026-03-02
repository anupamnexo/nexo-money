"""
Nexo.money - Corporate Card & Expense Management Platform
Database models and utilities for Indian SMEs
"""

import sqlite3
import hashlib
import os
import json
from datetime import datetime, timedelta
from pathlib import Path

# Database path
DB_PATH = Path(__file__).parent / "nexo.db"


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

    # Users table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT DEFAULT 'employee',
            company_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
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


def seed_demo_data():
    """Populate database with realistic demo data for TechNova Solutions."""
    conn = get_db()
    cursor = conn.cursor()

    try:
        # Clear existing demo data
        cursor.execute("DELETE FROM approvals")
        cursor.execute("DELETE FROM expenses")
        cursor.execute("DELETE FROM cards")
        cursor.execute("DELETE FROM users")
        cursor.execute("DELETE FROM budgets")
        cursor.execute("DELETE FROM vendors")
        cursor.execute("DELETE FROM companies")

        # Create company
        cursor.execute("""
            INSERT INTO companies (name, gstin, pan, industry, city, plan)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("TechNova Solutions", "29AABCT1234P1Z5", "AABCT1234P", "SaaS", "Bangalore", "premium"))
        company_id = cursor.lastrowid

        # Create team members
        team_data = [
            ("priya.shah@technova.com", "Priya Shah", "admin"),
            ("rajesh.kumar@technova.com", "Rajesh Kumar", "approver"),
            ("neha.patel@technova.com", "Neha Patel", "employee"),
            ("amit.singh@technova.com", "Amit Singh", "employee"),
            ("deepak.gupta@technova.com", "Deepak Gupta", "approver"),
            ("anjali.verma@technova.com", "Anjali Verma", "employee"),
        ]

        user_ids = {}
        for email, name, role in team_data:
            pwd_hash = hash_password("demo123")
            cursor.execute("""
                INSERT INTO users (email, password_hash, name, role, company_id)
                VALUES (?, ?, ?, ?, ?)
            """, (email, pwd_hash, name, role, company_id))
            user_ids[name] = cursor.lastrowid

        # Create cards for employees
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
                INSERT INTO cards (company_id, user_id, card_number, card_type, daily_limit, monthly_limit)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (company_id, user_id, masked, card_type, daily, monthly))
            card_ids.append(cursor.lastrowid)

        # Create budgets
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
            """, (company_id, team, category, limit, period))

        # Create vendors
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
            """, (company_id, name, gstin))
            vendor_ids[name] = cursor.lastrowid

        # Create expenses with realistic data
        categories = ["travel", "meals", "office", "software", "marketing", "other"]
        merchants = {
            "travel": ["Uber", "Ola", "IndiGo", "SpiceJet", "MakeMyTrip"],
            "meals": ["Zomato", "Swiggy", "CoffeeDay", "DomosFood", "RestaurantX"],
            "office": ["Amazon", "Flipkart", "LocalOfficeSupply", "StationeryPlus"],
            "software": ["AWS India", "Google Cloud", "Slack", "Jira", "GitHub"],
            "marketing": ["FacebookAds", "GoogleAds", "LinkedInAds", "ContentWriter"],
            "other": ["MiscExpense1", "MiscExpense2", "Repairs", "Utilities"],
        }

        approvers = [user_ids["Rajesh Kumar"], user_ids["Deepak Gupta"]]

        # Generate expenses for last 6 months
        now = datetime.now()
        expenses_created = 0

        for days_back in range(180, -1, -15):
            for _ in range(14):  # ~2 weeks of expenses
                exp_date = now - timedelta(days=days_back)

                category = categories[expenses_created % len(categories)]
                merchant = merchants[category][expenses_created % len(merchants[category])]

                # Vary amounts
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

                # Auto-approve if under 5000, else pending
                auto_approve = amount < 5000

                # Calculate GST
                gst_rate = 0.05 if amount < 5000 else 0.18  # Simplified
                gst_amount = amount * gst_rate
                igst = gst_amount * 0.8  # Simplified distribution
                cgst = gst_amount * 0.1
                sgst = gst_amount * 0.1

                card_id = card_ids[expenses_created % len(card_ids)]
                user_id = user_ids[["Neha Patel", "Amit Singh", "Anjali Verma"][expenses_created % 3]]

                cursor.execute("""
                    INSERT INTO expenses (
                        company_id, user_id, card_id, amount, merchant_name, category,
                        description, gstin_vendor, gst_amount, igst, cgst, sgst,
                        status, approved_by, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    company_id, user_id, card_id, amount, merchant, category,
                    f"Business expense for {category}", vendor_ids.get(merchant),
                    gst_amount, igst, cgst, sgst,
                    "auto_approved" if auto_approve else "pending",
                    approvers[expenses_created % 2] if auto_approve else None,
                    exp_date.isoformat()
                ))

                expense_id = cursor.lastrowid

                # Create approval record if not auto-approved
                if not auto_approve:
                    cursor.execute("""
                        INSERT INTO approvals (expense_id, approver_id, status, created_at)
                        VALUES (?, ?, ?, ?)
                    """, (expense_id, approvers[expenses_created % 2], "pending", exp_date.isoformat()))

                expenses_created += 1

        conn.commit()
        print(f"Demo data seeded: {expenses_created} expenses, 12 cards, 6 team members, 5 budgets")

    except Exception as e:
        conn.rollback()
        print(f"Error seeding demo data: {e}")
        raise
    finally:
        conn.close()


# Quick test
if __name__ == "__main__":
    # Remove old database
    if DB_PATH.exists():
        DB_PATH.unlink()

    # Initialize and seed
    init_db()
    seed_demo_data()
    print("Database initialized successfully!")
