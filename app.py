"""
Nexo.money - Corporate Card & Expense Management Platform
REST API server using Tornado
With Role-Based Access Control (RBAC)
"""

import os
import sys
import tornado.web
import tornado.ioloop
import json
import base64
import hmac
import hashlib
import time
import random
from datetime import datetime, timedelta
from urllib.parse import parse_qs

from models import (
    init_db, get_db, hash_password, verify_password, seed_demo_data,
    ROLE_HIERARCHY, ROLE_PERMISSIONS, VALID_ROLES,
    role_level, has_permission, is_role_at_least,
    get_team_member_ids, get_company_settings,
)

# Secret for token signing
TOKEN_SECRET = "nexo-secret-key-2024"
TOKEN_EXPIRY = 7 * 24 * 60 * 60  # 7 days


class BaseHandler(tornado.web.RequestHandler):
    """Base handler with CORS, auth, and RBAC utilities."""

    def set_default_headers(self):
        """Set CORS headers."""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.set_header("Content-Type", "application/json")

    def options(self, *args):
        """Handle CORS preflight."""
        self.set_status(204)
        self.finish()

    def write_json(self, data, status_code=200):
        """Write JSON response."""
        self.set_status(status_code)
        self.write(json.dumps(data))

    def write_error(self, status_code, **kwargs):
        """Write error response."""
        self.set_header("Content-Type", "application/json")
        self.write(json.dumps({"error": self._reason, "status": status_code}))

    def get_current_user(self):
        """Extract and validate user from token, including team info for managers."""
        auth_header = self.request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return None

        token = auth_header[7:]
        try:
            decoded = base64.b64decode(token).decode('utf-8')
            user_id, timestamp, signature = decoded.rsplit(':', 2)
            user_id = int(user_id)
            timestamp = int(timestamp)

            # Verify signature
            expected_sig = hmac.new(
                TOKEN_SECRET.encode(),
                f"{user_id}:{timestamp}".encode(),
                hashlib.sha256
            ).hexdigest()

            if signature != expected_sig:
                return None

            # Check expiry
            if time.time() - timestamp > TOKEN_EXPIRY:
                return None

            # Verify user exists
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, email, name, role, company_id, department, status
                FROM users WHERE id = ?
            """, (user_id,))
            user = cursor.fetchone()

            if not user:
                conn.close()
                return None

            user_dict = {
                "id": user["id"],
                "email": user["email"],
                "name": user["name"],
                "role": user["role"],
                "company_id": user["company_id"],
                "department": user["department"],
                "status": user["status"],
            }

            # For managers, also fetch their team member IDs
            if user["role"] == "manager" and user["company_id"]:
                user_dict["team_member_ids"] = get_team_member_ids(conn, user["id"], user["company_id"])
            else:
                user_dict["team_member_ids"] = []

            conn.close()
            return user_dict
        except Exception:
            return None

    def require_auth(self):
        """Require authentication."""
        user = self.get_current_user()
        if not user:
            self.set_status(401)
            self.write_json({"error": "Unauthorized"}, 401)
            return None
        if user.get("status") == "inactive":
            self.write_json({"error": "Account is deactivated"}, 403)
            return None
        return user

    def require_role(self, *roles):
        """Require user to have one of the specified roles. Returns user or None."""
        user = self.require_auth()
        if not user:
            return None
        if user["role"] not in roles:
            self.write_json({"error": "Forbidden: insufficient role"}, 403)
            return None
        return user

    def require_min_role(self, min_role):
        """Require user's role to be at least as privileged as min_role."""
        user = self.require_auth()
        if not user:
            return None
        if not is_role_at_least(user["role"], min_role):
            self.write_json({"error": "Forbidden: insufficient role"}, 403)
            return None
        return user

    def get_visible_user_ids(self, user, conn):
        """Get list of user IDs the current user can see data for."""
        role = user["role"]
        if role == "super_admin":
            # Super admin can see all users; optionally filter by company_id param
            company_filter = self.get_argument("company_id", None)
            cursor = conn.cursor()
            if company_filter:
                cursor.execute("SELECT id FROM users WHERE company_id = ?", (int(company_filter),))
            else:
                cursor.execute("SELECT id FROM users")
            return [row["id"] for row in cursor.fetchall()]
        elif role in ("company_admin", "admin"):
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE company_id = ?", (user["company_id"],))
            return [row["id"] for row in cursor.fetchall()]
        elif role == "manager":
            return [user["id"]] + user.get("team_member_ids", [])
        else:  # employee
            return [user["id"]]

    def get_company_filter(self, user):
        """Get company_id for SQL WHERE clauses. Super admin can query any company."""
        if user["role"] == "super_admin":
            company_id = self.get_argument("company_id", None)
            return int(company_id) if company_id else None
        return user["company_id"]


def generate_token(user_id):
    """Generate HMAC-signed token."""
    timestamp = int(time.time())
    signature = hmac.new(
        TOKEN_SECRET.encode(),
        f"{user_id}:{timestamp}".encode(),
        hashlib.sha256
    ).hexdigest()
    token_str = f"{user_id}:{timestamp}:{signature}"
    return base64.b64encode(token_str.encode()).decode()


# ============================================================================
# AUTH ENDPOINTS
# ============================================================================

class RegisterHandler(BaseHandler):
    def post(self):
        """POST /api/auth/register - Register new company + company_admin user."""
        try:
            data = json.loads(self.request.body)
            company_name = data.get("company_name")
            email = data.get("email")
            password = data.get("password")
            name = data.get("name")
            gstin = data.get("gstin")

            if not all([company_name, email, password, name]):
                return self.write_json({"error": "Missing required fields"}, 400)

            conn = get_db()
            cursor = conn.cursor()

            # Check if company exists
            cursor.execute("SELECT id FROM companies WHERE name = ?", (company_name,))
            if cursor.fetchone():
                conn.close()
                return self.write_json({"error": "Company already exists"}, 400)

            # Create company
            cursor.execute("""
                INSERT INTO companies (name, gstin)
                VALUES (?, ?)
            """, (company_name, gstin))
            company_id = cursor.lastrowid

            # Create company_admin user (registrant becomes company admin)
            pwd_hash = hash_password(password)
            cursor.execute("""
                INSERT INTO users (email, password_hash, name, role, company_id, department, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (email, pwd_hash, name, "company_admin", company_id, "Management", "active"))
            user_id = cursor.lastrowid

            # Create default company settings
            cursor.execute("""
                INSERT INTO company_settings (company_id) VALUES (?)
            """, (company_id,))

            conn.commit()
            conn.close()

            token = generate_token(user_id)
            self.write_json({
                "token": token,
                "user": {
                    "id": user_id,
                    "email": email,
                    "name": name,
                    "role": "company_admin",
                    "company_id": company_id
                }
            })
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


class LoginHandler(BaseHandler):
    def post(self):
        """POST /api/auth/login - Login user."""
        try:
            data = json.loads(self.request.body)
            email = data.get("email")
            password = data.get("password")

            if not email or not password:
                return self.write_json({"error": "Missing email or password"}, 400)

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, password_hash, name, role, company_id, department, status
                FROM users WHERE email = ?
            """, (email,))
            user = cursor.fetchone()

            if not user or not verify_password(user["password_hash"], password):
                conn.close()
                return self.write_json({"error": "Invalid credentials"}, 401)

            if user["status"] == "inactive":
                conn.close()
                return self.write_json({"error": "Account is deactivated"}, 403)

            # For super_admin, fetch list of companies they can manage
            companies = None
            if user["role"] == "super_admin":
                cursor.execute("SELECT id, name, industry, city, plan FROM companies ORDER BY name")
                companies = [dict(row) for row in cursor.fetchall()]

            conn.close()

            token = generate_token(user["id"])
            response = {
                "token": token,
                "user": {
                    "id": user["id"],
                    "email": email,
                    "name": user["name"],
                    "role": user["role"],
                    "company_id": user["company_id"],
                    "department": user["department"],
                }
            }
            if companies is not None:
                response["companies"] = companies

            self.write_json(response)
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


class MeHandler(BaseHandler):
    def get(self):
        """GET /api/auth/me - Get current user."""
        user = self.require_auth()
        if not user:
            return
        # Remove internal fields
        safe_user = {k: v for k, v in user.items() if k != "team_member_ids"}
        self.write_json({"user": safe_user})


# ============================================================================
# SUPER ADMIN: COMPANY MANAGEMENT
# ============================================================================

class CompaniesHandler(BaseHandler):
    def get(self):
        """GET /api/admin/companies - List all companies (super_admin only)."""
        user = self.require_role("super_admin")
        if not user:
            return

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.id, c.name, c.gstin, c.pan, c.industry, c.city, c.plan, c.created_at,
                   (SELECT COUNT(*) FROM users WHERE company_id = c.id) as user_count,
                   (SELECT COUNT(*) FROM cards WHERE company_id = c.id) as card_count,
                   (SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE company_id = c.id AND status != 'rejected') as total_spend
            FROM companies c ORDER BY c.created_at DESC
        """)
        companies = [dict(row) for row in cursor.fetchall()]
        conn.close()

        self.write_json({"companies": companies})

    def post(self):
        """POST /api/admin/companies - Create new company (super_admin only)."""
        user = self.require_role("super_admin")
        if not user:
            return

        try:
            data = json.loads(self.request.body)
            name = data.get("name")
            gstin = data.get("gstin")
            pan = data.get("pan")
            industry = data.get("industry")
            city = data.get("city")
            plan = data.get("plan", "free")

            if not name:
                return self.write_json({"error": "Company name is required"}, 400)

            conn = get_db()
            cursor = conn.cursor()

            cursor.execute("SELECT id FROM companies WHERE name = ?", (name,))
            if cursor.fetchone():
                conn.close()
                return self.write_json({"error": "Company already exists"}, 400)

            cursor.execute("""
                INSERT INTO companies (name, gstin, pan, industry, city, plan)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name, gstin, pan, industry, city, plan))
            company_id = cursor.lastrowid

            # Create default company settings
            cursor.execute("INSERT INTO company_settings (company_id) VALUES (?)", (company_id,))

            conn.commit()
            conn.close()

            self.write_json({"company": {"id": company_id, "name": name, "plan": plan}}, 201)
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


class CompanyDetailHandler(BaseHandler):
    def put(self, company_id):
        """PUT /api/admin/companies/:id - Update company (super_admin only)."""
        user = self.require_role("super_admin")
        if not user:
            return

        try:
            data = json.loads(self.request.body)
            conn = get_db()
            cursor = conn.cursor()

            updates = []
            params = []
            for field in ["name", "gstin", "pan", "industry", "city", "plan"]:
                if field in data:
                    updates.append(f"{field} = ?")
                    params.append(data[field])

            if updates:
                params.append(int(company_id))
                cursor.execute(f"UPDATE companies SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()

            cursor.execute("SELECT * FROM companies WHERE id = ?", (int(company_id),))
            company = cursor.fetchone()
            conn.close()

            if not company:
                return self.write_json({"error": "Company not found"}, 404)

            self.write_json({"company": dict(company)})
        except Exception as e:
            self.write_json({"error": str(e)}, 500)

    def get(self, company_id):
        """GET /api/admin/companies/:id - Get company details with users."""
        user = self.require_role("super_admin")
        if not user:
            return

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM companies WHERE id = ?", (int(company_id),))
        company = cursor.fetchone()
        if not company:
            conn.close()
            return self.write_json({"error": "Company not found"}, 404)

        cursor.execute("""
            SELECT id, email, name, role, department, status, created_at
            FROM users WHERE company_id = ? ORDER BY created_at
        """, (int(company_id),))
        users = [dict(row) for row in cursor.fetchall()]

        settings = get_company_settings(conn, int(company_id))
        conn.close()

        self.write_json({
            "company": dict(company),
            "users": users,
            "settings": settings
        })


# ============================================================================
# COMPANY SETTINGS
# ============================================================================

class CompanySettingsHandler(BaseHandler):
    def get(self):
        """GET /api/company/settings - Get company settings (company_admin only)."""
        user = self.require_role("company_admin")
        if not user:
            return

        conn = get_db()
        settings = get_company_settings(conn, user["company_id"])
        conn.close()
        self.write_json({"settings": settings})

    def put(self):
        """PUT /api/company/settings - Update company settings (company_admin only)."""
        user = self.require_role("company_admin")
        if not user:
            return

        try:
            data = json.loads(self.request.body)
            conn = get_db()
            cursor = conn.cursor()

            # Upsert settings
            cursor.execute("SELECT id FROM company_settings WHERE company_id = ?", (user["company_id"],))
            exists = cursor.fetchone()

            if exists:
                updates = []
                params = []
                for field in ["auto_approve_threshold", "manager_approval_limit",
                              "admin_approval_limit", "requires_manager_approval"]:
                    if field in data:
                        updates.append(f"{field} = ?")
                        params.append(data[field])
                if updates:
                    updates.append("updated_at = ?")
                    params.append(datetime.now().isoformat())
                    params.append(user["company_id"])
                    cursor.execute(
                        f"UPDATE company_settings SET {', '.join(updates)} WHERE company_id = ?",
                        params
                    )
            else:
                cursor.execute("""
                    INSERT INTO company_settings (company_id, auto_approve_threshold,
                        manager_approval_limit, admin_approval_limit, requires_manager_approval)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    user["company_id"],
                    data.get("auto_approve_threshold", 5000),
                    data.get("manager_approval_limit", 50000),
                    data.get("admin_approval_limit", 200000),
                    data.get("requires_manager_approval", 1),
                ))

            conn.commit()
            settings = get_company_settings(conn, user["company_id"])
            conn.close()

            self.write_json({"settings": settings})
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


# ============================================================================
# CARD ENDPOINTS
# ============================================================================

class CardsHandler(BaseHandler):
    def get(self):
        """GET /api/cards - List cards scoped by role."""
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        cursor = conn.cursor()
        role = user["role"]

        if role == "super_admin":
            company_id = self.get_company_filter(user)
            if company_id:
                cursor.execute("""
                    SELECT c.id, c.user_id, c.card_number, c.card_type, c.status,
                           c.daily_limit, c.monthly_limit, c.spent_today, c.spent_month,
                           c.created_at, u.name as user_name
                    FROM cards c JOIN users u ON c.user_id = u.id
                    WHERE c.company_id = ? ORDER BY c.created_at DESC
                """, (company_id,))
            else:
                cursor.execute("""
                    SELECT c.id, c.user_id, c.card_number, c.card_type, c.status,
                           c.daily_limit, c.monthly_limit, c.spent_today, c.spent_month,
                           c.created_at, u.name as user_name, co.name as company_name
                    FROM cards c JOIN users u ON c.user_id = u.id
                    JOIN companies co ON c.company_id = co.id
                    ORDER BY c.created_at DESC
                """)
        elif role in ("company_admin", "admin"):
            cursor.execute("""
                SELECT c.id, c.user_id, c.card_number, c.card_type, c.status,
                       c.daily_limit, c.monthly_limit, c.spent_today, c.spent_month,
                       c.created_at, u.name as user_name
                FROM cards c JOIN users u ON c.user_id = u.id
                WHERE c.company_id = ? ORDER BY c.created_at DESC
            """, (user["company_id"],))
        elif role == "manager":
            visible_ids = [user["id"]] + user.get("team_member_ids", [])
            placeholders = ",".join("?" * len(visible_ids))
            cursor.execute(f"""
                SELECT c.id, c.user_id, c.card_number, c.card_type, c.status,
                       c.daily_limit, c.monthly_limit, c.spent_today, c.spent_month,
                       c.created_at, u.name as user_name
                FROM cards c JOIN users u ON c.user_id = u.id
                WHERE c.user_id IN ({placeholders}) AND c.company_id = ?
                ORDER BY c.created_at DESC
            """, visible_ids + [user["company_id"]])
        else:  # employee
            cursor.execute("""
                SELECT c.id, c.user_id, c.card_number, c.card_type, c.status,
                       c.daily_limit, c.monthly_limit, c.spent_today, c.spent_month,
                       c.created_at, u.name as user_name
                FROM cards c JOIN users u ON c.user_id = u.id
                WHERE c.user_id = ? AND c.company_id = ?
                ORDER BY c.created_at DESC
            """, (user["id"], user["company_id"]))

        cards = [dict(row) for row in cursor.fetchall()]
        conn.close()
        self.write_json({"cards": cards})

    def post(self):
        """POST /api/cards - Issue new card (company_admin, admin only)."""
        user = self.require_role("super_admin", "company_admin", "admin")
        if not user:
            return

        try:
            data = json.loads(self.request.body)
            target_user_id = data.get("user_id", user["id"])
            card_type = data.get("card_type", "virtual")
            daily_limit = data.get("daily_limit", 25000)
            monthly_limit = data.get("monthly_limit", 150000)

            # For super_admin, determine company from target user
            if user["role"] == "super_admin":
                company_id = data.get("company_id")
                if not company_id:
                    return self.write_json({"error": "company_id required for super_admin"}, 400)
            else:
                company_id = user["company_id"]

            conn = get_db()
            cursor = conn.cursor()

            # Check target user belongs to company
            cursor.execute("SELECT id FROM users WHERE id = ? AND company_id = ?",
                           (target_user_id, company_id))
            if not cursor.fetchone():
                conn.close()
                return self.write_json({"error": "User not found in company"}, 404)

            last_four = str(random.randint(1000, 9999))
            masked = f"**** **** **** {last_four}"

            cursor.execute("""
                INSERT INTO cards (company_id, user_id, card_number, card_type,
                                  daily_limit, monthly_limit, issued_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (company_id, target_user_id, masked, card_type, daily_limit, monthly_limit, user["id"]))
            card_id = cursor.lastrowid
            conn.commit()

            cursor.execute("""
                SELECT id, user_id, card_number, card_type, status,
                       daily_limit, monthly_limit, spent_today, spent_month, created_at
                FROM cards WHERE id = ?
            """, (card_id,))
            card = dict(cursor.fetchone())
            conn.close()

            self.write_json({"card": card}, 201)
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


class CardHandler(BaseHandler):
    def put(self, card_id):
        """PUT /api/cards/:id - Update card (company_admin, admin only)."""
        user = self.require_role("super_admin", "company_admin", "admin")
        if not user:
            return

        try:
            data = json.loads(self.request.body)
            conn = get_db()
            cursor = conn.cursor()

            # Verify card belongs to company (or any company for super_admin)
            if user["role"] == "super_admin":
                cursor.execute("SELECT id FROM cards WHERE id = ?", (card_id,))
            else:
                cursor.execute("SELECT id FROM cards WHERE id = ? AND company_id = ?",
                               (card_id, user["company_id"]))
            if not cursor.fetchone():
                conn.close()
                return self.write_json({"error": "Card not found"}, 404)

            updates = []
            params = []
            for field in ["daily_limit", "monthly_limit", "status"]:
                if field in data:
                    updates.append(f"{field} = ?")
                    params.append(data[field])

            if updates:
                params.append(card_id)
                cursor.execute(f"UPDATE cards SET {', '.join(updates)} WHERE id = ?", params)
                conn.commit()

            cursor.execute("""
                SELECT id, user_id, card_number, card_type, status,
                       daily_limit, monthly_limit, spent_today, spent_month, created_at
                FROM cards WHERE id = ?
            """, (card_id,))
            card = dict(cursor.fetchone())
            conn.close()

            self.write_json({"card": card})
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


# ============================================================================
# EXPENSE ENDPOINTS
# ============================================================================

class ExpensesHandler(BaseHandler):
    def get(self):
        """GET /api/expenses - List expenses scoped by role."""
        user = self.require_auth()
        if not user:
            return

        status_filter = self.get_argument("status", None)
        category = self.get_argument("category", None)
        start_date = self.get_argument("start_date", None)
        end_date = self.get_argument("end_date", None)

        conn = get_db()
        cursor = conn.cursor()
        role = user["role"]

        # Build base query based on role
        if role == "super_admin":
            company_id = self.get_company_filter(user)
            if company_id:
                base_where = "e.company_id = ?"
                params = [company_id]
            else:
                base_where = "1=1"
                params = []
        elif role in ("company_admin", "admin"):
            base_where = "e.company_id = ?"
            params = [user["company_id"]]
        elif role == "manager":
            visible_ids = [user["id"]] + user.get("team_member_ids", [])
            placeholders = ",".join("?" * len(visible_ids))
            base_where = f"e.user_id IN ({placeholders}) AND e.company_id = ?"
            params = visible_ids + [user["company_id"]]
        else:  # employee
            base_where = "e.user_id = ? AND e.company_id = ?"
            params = [user["id"], user["company_id"]]

        query = f"""
            SELECT e.id, e.user_id, e.card_id, e.amount, e.currency, e.merchant_name,
                   e.category, e.description, e.receipt_url, e.gstin_vendor,
                   e.gst_amount, e.igst, e.cgst, e.sgst, e.status, e.approved_by,
                   e.approval_level, e.created_at, u.name as user_name
            FROM expenses e JOIN users u ON e.user_id = u.id
            WHERE {base_where}
        """

        if status_filter:
            query += " AND e.status = ?"
            params.append(status_filter)
        if category:
            query += " AND e.category = ?"
            params.append(category)
        if start_date:
            query += " AND e.created_at >= ?"
            params.append(start_date)
        if end_date:
            query += " AND e.created_at <= ?"
            params.append(end_date)

        query += " ORDER BY e.created_at DESC"

        cursor.execute(query, params)
        expenses = [dict(row) for row in cursor.fetchall()]
        conn.close()

        self.write_json({"expenses": expenses})

    def post(self):
        """POST /api/expenses - Create expense (all roles except super_admin)."""
        user = self.require_auth()
        if not user:
            return

        if user["role"] == "super_admin":
            return self.write_json({"error": "Super admin cannot submit expenses"}, 403)

        try:
            data = json.loads(self.request.body)
            card_id = data.get("card_id")
            amount = data.get("amount")
            merchant_name = data.get("merchant_name")
            category = data.get("category", "other")
            description = data.get("description", "")
            receipt_url = data.get("receipt_url")
            gstin_vendor = data.get("gstin_vendor")

            if not all([amount, merchant_name]):
                return self.write_json({"error": "Missing required fields"}, 400)

            conn = get_db()
            cursor = conn.cursor()

            # Get company settings for approval thresholds
            settings = get_company_settings(conn, user["company_id"])

            # Calculate GST
            gst_rate = 0.05 if amount < 5000 else 0.18
            gst_amount = amount * gst_rate
            igst = gst_amount * 0.8
            cgst = gst_amount * 0.1
            sgst = gst_amount * 0.1

            # Determine approval status based on amount and settings
            auto_threshold = settings.get("auto_approve_threshold", 5000)
            if amount < auto_threshold:
                status = "auto_approved"
                approved_by = user["id"]
                approval_level = 0
            else:
                status = "pending"
                approved_by = None
                approval_level = 1

            cursor.execute("""
                INSERT INTO expenses (
                    company_id, user_id, card_id, amount, merchant_name,
                    category, description, receipt_url, gstin_vendor,
                    gst_amount, igst, cgst, sgst, status, approved_by, approval_level
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user["company_id"], user["id"], card_id, amount, merchant_name,
                category, description, receipt_url, gstin_vendor,
                gst_amount, igst, cgst, sgst, status, approved_by, approval_level
            ))
            expense_id = cursor.lastrowid

            # Create approval record if not auto-approved
            if status == "pending":
                # Determine who should approve based on submitter's role
                if user["role"] == "employee" and settings.get("requires_manager_approval", 1):
                    # Find employee's manager from user_teams
                    cursor.execute("""
                        SELECT manager_id FROM user_teams
                        WHERE user_id = ? AND company_id = ?
                    """, (user["id"], user["company_id"]))
                    team_row = cursor.fetchone()
                    if team_row and team_row["manager_id"]:
                        approver_id = team_row["manager_id"]
                    else:
                        # No manager assigned, escalate to admin
                        cursor.execute("""
                            SELECT id FROM users
                            WHERE company_id = ? AND role IN ('admin', 'company_admin')
                            ORDER BY CASE role WHEN 'admin' THEN 1 WHEN 'company_admin' THEN 2 END
                            LIMIT 1
                        """, (user["company_id"],))
                        admin_row = cursor.fetchone()
                        approver_id = admin_row["id"] if admin_row else user["id"]
                elif user["role"] == "manager":
                    # Manager's expenses go to admin
                    cursor.execute("""
                        SELECT id FROM users
                        WHERE company_id = ? AND role IN ('admin', 'company_admin')
                        ORDER BY CASE role WHEN 'admin' THEN 1 WHEN 'company_admin' THEN 2 END
                        LIMIT 1
                    """, (user["company_id"],))
                    admin_row = cursor.fetchone()
                    approver_id = admin_row["id"] if admin_row else user["id"]
                elif user["role"] == "admin":
                    # Admin's expenses go to company_admin
                    cursor.execute("""
                        SELECT id FROM users
                        WHERE company_id = ? AND role = 'company_admin'
                        LIMIT 1
                    """, (user["company_id"],))
                    ca_row = cursor.fetchone()
                    approver_id = ca_row["id"] if ca_row else user["id"]
                else:
                    # company_admin expenses â self-approve or first admin
                    cursor.execute("""
                        SELECT id FROM users
                        WHERE company_id = ? AND role = 'admin' AND id != ?
                        LIMIT 1
                    """, (user["company_id"], user["id"]))
                    other = cursor.fetchone()
                    approver_id = other["id"] if other else user["id"]

                cursor.execute("""
                    INSERT INTO approvals (expense_id, approver_id, status, approval_level)
                    VALUES (?, ?, ?, ?)
                """, (expense_id, approver_id, "pending", 1))

            conn.commit()
            conn.close()

            self.write_json({
                "expense": {
                    "id": expense_id,
                    "amount": amount,
                    "merchant_name": merchant_name,
                    "category": category,
                    "status": status,
                    "created_at": datetime.now().isoformat()
                }
            }, 201)
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


class ExpenseApproveHandler(BaseHandler):
    def put(self, expense_id):
        """PUT /api/expenses/:id/approve - Approve expense with chain logic."""
        user = self.require_auth()
        if not user:
            return

        # Only certain roles can approve
        if user["role"] not in ("company_admin", "admin", "manager"):
            return self.write_json({"error": "You cannot approve expenses"}, 403)

        try:
            data = json.loads(self.request.body)
            comment = data.get("comment", "")

            conn = get_db()
            cursor = conn.cursor()

            # Fetch the expense
            if user["role"] == "super_admin":
                cursor.execute("SELECT * FROM expenses WHERE id = ?", (int(expense_id),))
            else:
                cursor.execute("SELECT * FROM expenses WHERE id = ? AND company_id = ?",
                               (int(expense_id), user["company_id"]))
            expense = cursor.fetchone()
            if not expense:
                conn.close()
                return self.write_json({"error": "Expense not found"}, 404)

            expense = dict(expense)

            # Block self-approval
            if expense["user_id"] == user["id"]:
                conn.close()
                return self.write_json({"error": "Cannot approve your own expense"}, 403)

            # Manager can only approve their team's expenses
            if user["role"] == "manager":
                team_ids = user.get("team_member_ids", [])
                if expense["user_id"] not in team_ids:
                    conn.close()
                    return self.write_json({"error": "You can only approve your team's expenses"}, 403)

            # Check approval thresholds for escalation
            settings = get_company_settings(conn, expense["company_id"])
            amount = expense["amount"]
            needs_escalation = False

            if user["role"] == "manager" and amount > settings.get("manager_approval_limit", 50000):
                needs_escalation = True
            elif user["role"] == "admin" and amount > settings.get("admin_approval_limit", 200000):
                needs_escalation = True

            if needs_escalation:
                # Escalate: mark current approval as approved, create next-level approval
                new_level = expense["approval_level"] + 1
                cursor.execute("""
                    UPDATE expenses SET approval_level = ? WHERE id = ?
                """, (new_level, expense_id))

                cursor.execute("""
                    UPDATE approvals SET status = ?, comment = ?
                    WHERE expense_id = ? AND status = 'pending'
                """, ("approved", comment, expense_id))

                # Find next-level approver
                if user["role"] == "manager":
                    cursor.execute("""
                        SELECT id FROM users
                        WHERE company_id = ? AND role IN ('admin', 'company_admin')
                        ORDER BY CASE role WHEN 'admin' THEN 1 WHEN 'company_admin' THEN 2 END
                        LIMIT 1
                    """, (expense["company_id"],))
                else:  # admin
                    cursor.execute("""
                        SELECT id FROM users
                        WHERE company_id = ? AND role = 'company_admin'
                        LIMIT 1
                    """, (expense["company_id"],))

                next_approver = cursor.fetchone()
                if next_approver:
                    cursor.execute("""
                        INSERT INTO approvals (expense_id, approver_id, status, approval_level)
                        VALUES (?, ?, ?, ?)
                    """, (expense_id, next_approver["id"], "pending", new_level))

                conn.commit()
                conn.close()
                return self.write_json({"message": "Expense approved at your level, escalated for further approval"})

            # Final approval â no escalation needed
            cursor.execute("""
                UPDATE expenses SET status = ?, approved_by = ?
                WHERE id = ?
            """, ("approved", user["id"], expense_id))

            cursor.execute("""
                UPDATE approvals SET status = ?, comment = ?
                WHERE expense_id = ? AND status = 'pending'
            """, ("approved", comment, expense_id))

            conn.commit()
            conn.close()

            self.write_json({"message": "Expense approved"})
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


class ExpenseRejectHandler(BaseHandler):
    def put(self, expense_id):
        """PUT /api/expenses/:id/reject - Reject expense."""
        user = self.require_auth()
        if not user:
            return

        if user["role"] not in ("company_admin", "admin", "manager"):
            return self.write_json({"error": "You cannot reject expenses"}, 403)

        try:
            data = json.loads(self.request.body)
            comment = data.get("comment", "")

            conn = get_db()
            cursor = conn.cursor()

            # Verify expense belongs to company
            if user["role"] == "super_admin":
                cursor.execute("SELECT id, user_id FROM expenses WHERE id = ?", (int(expense_id),))
            else:
                cursor.execute("SELECT id, user_id FROM expenses WHERE id = ? AND company_id = ?",
                               (int(expense_id), user["company_id"]))
            expense = cursor.fetchone()
            if not expense:
                conn.close()
                return self.write_json({"error": "Expense not found"}, 404)

            # Manager can only reject their team's expenses
            if user["role"] == "manager":
                team_ids = user.get("team_member_ids", [])
                if expense["user_id"] not in team_ids:
                    conn.close()
                    return self.write_json({"error": "You can only reject your team's expenses"}, 403)

            cursor.execute("UPDATE expenses SET status = ? WHERE id = ?", ("rejected", expense_id))
            cursor.execute("""
                UPDATE approvals SET status = ?, comment = ?
                WHERE expense_id = ? AND status = 'pending'
            """, ("rejected", comment, expense_id))

            conn.commit()
            conn.close()

            self.write_json({"message": "Expense rejected"})
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


# ============================================================================
# DASHBOARD ENDPOINTS
# ============================================================================

class DashboardHandler(BaseHandler):
    def get(self):
        """GET /api/dashboard - Dashboard stats scoped by role."""
        user = self.require_auth()
        if not user:
            return

        try:
            conn = get_db()
            cursor = conn.cursor()
            now = datetime.now()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            role = user["role"]

            # Determine scope
            if role == "super_admin":
                company_id = self.get_company_filter(user)
                if company_id:
                    expense_where = "company_id = ?"
                    card_where = "company_id = ?"
                    expense_params = [company_id]
                    card_params = [company_id]
                else:
                    expense_where = "1=1"
                    card_where = "1=1"
                    expense_params = []
                    card_params = []
            elif role in ("company_admin", "admin"):
                expense_where = "company_id = ?"
                card_where = "company_id = ?"
                expense_params = [user["company_id"]]
                card_params = [user["company_id"]]
            elif role == "manager":
                visible_ids = [user["id"]] + user.get("team_member_ids", [])
                placeholders = ",".join("?" * len(visible_ids))
                expense_where = f"user_id IN ({placeholders}) AND company_id = ?"
                card_where = f"user_id IN ({placeholders}) AND company_id = ?"
                expense_params = visible_ids + [user["company_id"]]
                card_params = visible_ids + [user["company_id"]]
            else:  # employee
                expense_where = "user_id = ? AND company_id = ?"
                card_where = "user_id = ? AND company_id = ?"
                expense_params = [user["id"], user["company_id"]]
                card_params = [user["id"], user["company_id"]]

            # Total spend this month
            cursor.execute(f"""
                SELECT COALESCE(SUM(amount), 0) as total
                FROM expenses
                WHERE {expense_where} AND created_at >= ? AND status != 'rejected'
            """, expense_params + [month_start.isoformat()])
            total_spend_month = cursor.fetchone()["total"]

            # Total spend today
            cursor.execute(f"""
                SELECT COALESCE(SUM(amount), 0) as total
                FROM expenses
                WHERE {expense_where} AND created_at >= ? AND status != 'rejected'
            """, expense_params + [today_start.isoformat()])
            total_spend_today = cursor.fetchone()["total"]

            # Active cards
            cursor.execute(f"""
                SELECT COUNT(*) as count FROM cards
                WHERE {card_where} AND status = 'active'
            """, card_params)
            active_cards = cursor.fetchone()["count"]

            # Pending approvals (for this user specifically)
            cursor.execute("""
                SELECT COUNT(*) as count FROM approvals
                WHERE approver_id = ? AND status = 'pending'
            """, (user["id"],))
            pending_approvals = cursor.fetchone()["count"]

            # Spend by category (last 6 months)
            spend_by_category = {}
            for i in range(6):
                month_date = now - timedelta(days=30*i)
                ms = month_date.replace(day=1)
                nm = (ms + timedelta(days=32)).replace(day=1)
                cursor.execute(f"""
                    SELECT category, COALESCE(SUM(amount), 0) as total
                    FROM expenses
                    WHERE {expense_where} AND created_at >= ? AND created_at < ?
                    AND status != 'rejected'
                    GROUP BY category
                """, expense_params + [ms.isoformat(), nm.isoformat()])
                for row in cursor.fetchall():
                    if row["category"] not in spend_by_category:
                        spend_by_category[row["category"]] = 0
                    spend_by_category[row["category"]] += row["total"]

            # Spend by team member (last 3 months)
            spend_by_team = {}
            three_months_ago = now - timedelta(days=90)
            cursor.execute(f"""
                SELECT u.name, COALESCE(SUM(e.amount), 0) as total
                FROM expenses e
                JOIN users u ON e.user_id = u.id
                WHERE {expense_where.replace('company_id', 'e.company_id').replace('user_id', 'e.user_id')}
                AND e.created_at >= ? AND e.status != 'rejected'
                GROUP BY e.user_id
                ORDER BY total DESC
                LIMIT 10
            """, expense_params + [three_months_ago.isoformat()])
            for row in cursor.fetchall():
                spend_by_team[row["name"]] = row["total"]

            # Top vendors (last 3 months)
            cursor.execute(f"""
                SELECT merchant_name, COUNT(*) as count, COALESCE(SUM(amount), 0) as total
                FROM expenses
                WHERE {expense_where} AND created_at >= ? AND status != 'rejected'
                GROUP BY merchant_name
                ORDER BY total DESC
                LIMIT 5
            """, expense_params + [three_months_ago.isoformat()])
            top_vendors = [{"name": row["merchant_name"], "count": row["count"], "spent": row["total"]}
                          for row in cursor.fetchall()]

            # Recent transactions (last 10)
            cursor.execute(f"""
                SELECT id, merchant_name, amount, category, status, created_at
                FROM expenses
                WHERE {expense_where}
                ORDER BY created_at DESC
                LIMIT 10
            """, expense_params)
            recent_transactions = [dict(row) for row in cursor.fetchall()]

            # Budget utilization (only for company-level roles)
            budget_util = []
            if role in ("super_admin", "company_admin", "admin"):
                budget_company = self.get_company_filter(user) if role == "super_admin" else user["company_id"]
                if budget_company:
                    cursor.execute("""
                        SELECT category, monthly_limit, spent_this_month
                        FROM budgets
                        WHERE company_id = ? AND period = ?
                    """, (budget_company, now.strftime("%Y-%m")))
                    for row in cursor.fetchall():
                        utilization = (row["spent_this_month"] / row["monthly_limit"] * 100) if row["monthly_limit"] > 0 else 0
                        budget_util.append({
                            "category": row["category"],
                            "limit": row["monthly_limit"],
                            "spent": row["spent_this_month"],
                            "utilization": round(utilization, 2)
                        })

            conn.close()

            self.write_json({
                "dashboard": {
                    "total_spend_month": total_spend_month,
                    "total_spend_today": total_spend_today,
                    "active_cards": active_cards,
                    "pending_approvals": pending_approvals,
                    "spend_by_category": spend_by_category,
                    "spend_by_team": spend_by_team,
                    "top_vendors": top_vendors,
                    "recent_transactions": recent_transactions,
                    "budget_utilization": budget_util
                }
            })
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


class GSTHandler(BaseHandler):
    def get(self):
        """GET /api/gst - GST analytics (company_admin, admin only)."""
        user = self.require_min_role("admin")
        if not user:
            return

        try:
            conn = get_db()
            cursor = conn.cursor()
            now = datetime.now()

            company_id = self.get_company_filter(user)
            if not company_id:
                conn.close()
                return self.write_json({"error": "Company context required"}, 400)

            # Total GST paid
            cursor.execute("""
                SELECT COALESCE(SUM(gst_amount), 0) as total
                FROM expenses
                WHERE company_id = ? AND status != 'rejected'
            """, (company_id,))
            total_gst_paid = cursor.fetchone()["total"]

            claimable_itc = total_gst_paid
            itc_recovery_rate = 85

            # GST by month (last 12 months)
            gst_by_month = {}
            for i in range(12):
                month_date = now - timedelta(days=30*i)
                ms = month_date.replace(day=1)
                nm = (ms + timedelta(days=32)).replace(day=1)
                cursor.execute("""
                    SELECT COALESCE(SUM(gst_amount), 0) as total
                    FROM expenses
                    WHERE company_id = ? AND created_at >= ? AND created_at < ?
                    AND status != 'rejected'
                """, (company_id, ms.isoformat(), nm.isoformat()))
                month_key = ms.strftime("%Y-%m")
                gst_by_month[month_key] = cursor.fetchone()["total"]

            # Missing GSTIN count
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM expenses
                WHERE company_id = ? AND gstin_vendor IS NULL AND status != 'rejected'
            """, (company_id,))
            missing_gstin_count = cursor.fetchone()["count"]

            conn.close()

            self.write_json({
                "gst": {
                    "total_gst_paid": total_gst_paid,
                    "claimable_itc": claimable_itc,
                    "itc_recovery_rate": itc_recovery_rate,
                    "gst_by_month": gst_by_month,
                    "missing_gstin_count": missing_gstin_count
                }
            })
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


# ============================================================================
# TEAM ENDPOINTS
# ============================================================================

class TeamHandler(BaseHandler):
    def get(self):
        """GET /api/team - List team members scoped by role."""
        user = self.require_auth()
        if not user:
            return

        if user["role"] == "employee":
            return self.write_json({"error": "Forbidden"}, 403)

        conn = get_db()
        cursor = conn.cursor()
        role = user["role"]

        if role == "super_admin":
            company_id = self.get_company_filter(user)
            if company_id:
                cursor.execute("""
                    SELECT u.id, u.email, u.name, u.role, u.department, u.status, u.created_at,
                           ut.manager_id, m.name as manager_name
                    FROM users u
                    LEFT JOIN user_teams ut ON u.id = ut.user_id
                    LEFT JOIN users m ON ut.manager_id = m.id
                    WHERE u.company_id = ?
                    ORDER BY u.created_at
                """, (company_id,))
            else:
                cursor.execute("""
                    SELECT u.id, u.email, u.name, u.role, u.department, u.status, u.created_at,
                           u.company_id, c.name as company_name
                    FROM users u
                    LEFT JOIN companies c ON u.company_id = c.id
                    WHERE u.role != 'super_admin'
                    ORDER BY u.company_id, u.created_at
                """)
        elif role in ("company_admin", "admin"):
            cursor.execute("""
                SELECT u.id, u.email, u.name, u.role, u.department, u.status, u.created_at,
                       ut.manager_id, m.name as manager_name
                FROM users u
                LEFT JOIN user_teams ut ON u.id = ut.user_id
                LEFT JOIN users m ON ut.manager_id = m.id
                WHERE u.company_id = ?
                ORDER BY u.created_at
            """, (user["company_id"],))
        elif role == "manager":
            # Manager sees own team
            visible_ids = [user["id"]] + user.get("team_member_ids", [])
            placeholders = ",".join("?" * len(visible_ids))
            cursor.execute(f"""
                SELECT u.id, u.email, u.name, u.role, u.department, u.status, u.created_at,
                       ut.manager_id, m.name as manager_name
                FROM users u
                LEFT JOIN user_teams ut ON u.id = ut.user_id
                LEFT JOIN users m ON ut.manager_id = m.id
                WHERE u.id IN ({placeholders})
                ORDER BY u.created_at
            """, visible_ids)

        team = [dict(row) for row in cursor.fetchall()]
        conn.close()

        self.write_json({"team": team})

    def post(self):
        """POST /api/team - Add team member (company_admin, admin only)."""
        user = self.require_role("super_admin", "company_admin", "admin")
        if not user:
            return

        try:
            data = json.loads(self.request.body)
            email = data.get("email")
            name = data.get("name")
            new_role = data.get("role", "employee")
            password = data.get("password", "TempPass123!")
            issue_card = data.get("issue_card", False)
            department = data.get("department", "")
            manager_id = data.get("manager_id")

            if not email or not name:
                return self.write_json({"error": "Missing required fields"}, 400)

            if new_role not in VALID_ROLES:
                return self.write_json({"error": f"Invalid role. Valid: {', '.join(VALID_ROLES)}"}, 400)

            # Role creation restrictions
            if user["role"] == "admin" and new_role in ("super_admin", "company_admin", "admin"):
                return self.write_json({"error": "Admin can only create manager or employee roles"}, 403)
            if user["role"] == "company_admin" and new_role in ("super_admin", "company_admin"):
                return self.write_json({"error": "Company admin can create admin, manager, or employee roles"}, 403)

            # Determine company
            if user["role"] == "super_admin":
                company_id = data.get("company_id")
                if not company_id:
                    return self.write_json({"error": "company_id required for super_admin"}, 400)
            else:
                company_id = user["company_id"]

            conn = get_db()
            cursor = conn.cursor()

            # Check if user already exists
            cursor.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cursor.fetchone():
                conn.close()
                return self.write_json({"error": "User already exists"}, 400)

            # Create user
            pwd_hash = hash_password(password)
            cursor.execute("""
                INSERT INTO users (email, password_hash, name, role, company_id, department, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (email, pwd_hash, name, new_role, company_id, department, "active"))
            new_user_id = cursor.lastrowid

            # Set up manager relationship if provided
            if manager_id:
                cursor.execute("""
                    INSERT INTO user_teams (user_id, manager_id, team_name, company_id)
                    VALUES (?, ?, ?, ?)
                """, (new_user_id, manager_id, department, company_id))

            card_id = None
            if issue_card:
                last_four = str(random.randint(1000, 9999))
                masked = f"**** **** **** {last_four}"
                cursor.execute("""
                    INSERT INTO cards (company_id, user_id, card_number, card_type, issued_by)
                    VALUES (?, ?, ?, ?, ?)
                """, (company_id, new_user_id, masked, "virtual", user["id"]))
                card_id = cursor.lastrowid

            conn.commit()
            conn.close()

            self.write_json({
                "user": {
                    "id": new_user_id,
                    "email": email,
                    "name": name,
                    "role": new_role,
                    "department": department,
                    "card_id": card_id
                }
            }, 201)
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


# ============================================================================
# ANALYTICS ENDPOINTS
# ============================================================================

class AnalyticsHandler(BaseHandler):
    def get(self):
        """GET /api/analytics - Analytics data scoped by role."""
        user = self.require_min_role("manager")
        if not user:
            return

        # Employee can't access analytics
        if user["role"] == "employee":
            return self.write_json({"error": "Forbidden"}, 403)

        try:
            conn = get_db()
            cursor = conn.cursor()
            now = datetime.now()
            role = user["role"]

            # Build scope
            if role == "super_admin":
                company_id = self.get_company_filter(user)
                if company_id:
                    where = "e.company_id = ?"
                    params = [company_id]
                else:
                    where = "1=1"
                    params = []
            elif role in ("company_admin", "admin"):
                where = "e.company_id = ?"
                params = [user["company_id"]]
            else:  # manager
                visible_ids = [user["id"]] + user.get("team_member_ids", [])
                placeholders = ",".join("?" * len(visible_ids))
                where = f"e.user_id IN ({placeholders}) AND e.company_id = ?"
                params = visible_ids + [user["company_id"]]

            # Spend trend (12 months)
            spend_trend = {}
            for i in range(12, 0, -1):
                month_date = now - timedelta(days=30*i)
                ms = month_date.replace(day=1)
                nm = (ms + timedelta(days=32)).replace(day=1)
                cursor.execute(f"""
                    SELECT COALESCE(SUM(e.amount), 0) as total
                    FROM expenses e
                    WHERE {where} AND e.created_at >= ? AND e.created_at < ?
                    AND e.status != 'rejected'
                """, params + [ms.isoformat(), nm.isoformat()])
                month_key = ms.strftime("%Y-%m")
                spend_trend[month_key] = cursor.fetchone()["total"]

            # Category breakdown
            cursor.execute(f"""
                SELECT e.category, COALESCE(SUM(e.amount), 0) as total, COUNT(*) as count
                FROM expenses e
                WHERE {where} AND e.status != 'rejected'
                GROUP BY e.category
            """, params)
            category_breakdown = [{"category": row["category"], "spent": row["total"], "count": row["count"]}
                                 for row in cursor.fetchall()]

            # Top merchants
            cursor.execute(f"""
                SELECT e.merchant_name, COALESCE(SUM(e.amount), 0) as total, COUNT(*) as count
                FROM expenses e
                WHERE {where} AND e.status != 'rejected'
                GROUP BY e.merchant_name
                ORDER BY total DESC
                LIMIT 10
            """, params)
            top_merchants = [{"merchant": row["merchant_name"], "spent": row["total"], "count": row["count"]}
                            for row in cursor.fetchall()]

            # Average transaction
            cursor.execute(f"""
                SELECT COALESCE(AVG(e.amount), 0) as avg_size
                FROM expenses e
                WHERE {where} AND e.status != 'rejected'
            """, params)
            avg_transaction_size = cursor.fetchone()["avg_size"]

            # Total transactions
            cursor.execute(f"""
                SELECT COUNT(*) as total
                FROM expenses e
                WHERE {where} AND e.status != 'rejected'
            """, params)
            total_transactions = cursor.fetchone()["total"]

            # Cards utilization
            if role in ("super_admin", "company_admin", "admin"):
                card_company = self.get_company_filter(user) if role == "super_admin" else user["company_id"]
                if card_company:
                    cursor.execute("""
                        SELECT c.id, c.card_number, COALESCE(SUM(e.amount), 0) as spent,
                               c.monthly_limit, c.spent_month
                        FROM cards c
                        LEFT JOIN expenses e ON c.id = e.card_id AND e.status != 'rejected'
                        WHERE c.company_id = ?
                        GROUP BY c.id
                    """, (card_company,))
                else:
                    cursor.execute("""
                        SELECT c.id, c.card_number, COALESCE(SUM(e.amount), 0) as spent,
                               c.monthly_limit, c.spent_month
                        FROM cards c
                        LEFT JOIN expenses e ON c.id = e.card_id AND e.status != 'rejected'
                        GROUP BY c.id
                    """)
            else:  # manager
                visible_ids = [user["id"]] + user.get("team_member_ids", [])
                placeholders = ",".join("?" * len(visible_ids))
                cursor.execute(f"""
                    SELECT c.id, c.card_number, COALESCE(SUM(e.amount), 0) as spent,
                           c.monthly_limit, c.spent_month
                    FROM cards c
                    LEFT JOIN expenses e ON c.id = e.card_id AND e.status != 'rejected'
                    WHERE c.user_id IN ({placeholders})
                    GROUP BY c.id
                """, visible_ids)

            cards_utilization = []
            for row in cursor.fetchall():
                utilization = (row["spent"] / row["monthly_limit"] * 100) if row["monthly_limit"] > 0 else 0
                cards_utilization.append({
                    "card": row["card_number"],
                    "spent": row["spent"],
                    "limit": row["monthly_limit"],
                    "utilization": round(utilization, 2)
                })

            conn.close()

            self.write_json({
                "analytics": {
                    "spend_trend": spend_trend,
                    "category_breakdown": category_breakdown,
                    "top_merchants": top_merchants,
                    "avg_transaction_size": round(avg_transaction_size, 2),
                    "total_transactions": total_transactions,
                    "cards_utilization": cards_utilization
                }
            })
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


# ============================================================================
# APPROVALS LIST ENDPOINT
# ============================================================================

class ApprovalsHandler(BaseHandler):
    def get(self):
        """GET /api/approvals - List pending approvals for current user."""
        user = self.require_auth()
        if not user:
            return

        if user["role"] == "employee":
            return self.write_json({"approvals": []})

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT a.id, a.expense_id, a.status, a.comment, a.approval_level, a.created_at,
                   e.amount, e.merchant_name, e.category, e.description, e.user_id,
                   u.name as submitter_name, u.email as submitter_email
            FROM approvals a
            JOIN expenses e ON a.expense_id = e.id
            JOIN users u ON e.user_id = u.id
            WHERE a.approver_id = ?
            ORDER BY a.created_at DESC
        """, (user["id"],))
        approvals = [dict(row) for row in cursor.fetchall()]
        conn.close()

        self.write_json({"approvals": approvals})


# ============================================================================
# WAITLIST ENDPOINT
# ============================================================================

class WaitlistHandler(BaseHandler):
    def post(self):
        """POST /api/waitlist - Add to waitlist."""
        try:
            data = json.loads(self.request.body)
            email = data.get("email")
            company_name = data.get("company_name", "")
            phone = data.get("phone", "")

            if not email:
                return self.write_json({"error": "Email required"}, 400)

            conn = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO waitlist (email, company_name, phone)
                VALUES (?, ?, ?)
            """, (email, company_name, phone))
            conn.commit()
            conn.close()

            self.write_json({"message": "Added to waitlist"}, 201)
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


# ============================================================================
# STATIC FILE HANDLERS
# ============================================================================

class LandingHandler(BaseHandler):
    def get(self):
        """Serve landing page."""
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        try:
            with open("templates/landing.html", "r") as f:
                self.write(f.read())
        except FileNotFoundError:
            self.write("<h1>Nexo.money - Coming Soon</h1>")


class AppHandler(BaseHandler):
    def get(self):
        """Serve app page."""
        self.set_header("Content-Type", "text/html; charset=UTF-8")
        try:
            with open("templates/app.html", "r") as f:
                self.write(f.read())
        except FileNotFoundError:
            self.write("<h1>Nexo.money - Dashboard</h1>")


# ============================================================================
# MAIN APP
# ============================================================================

def make_app():
    """Create Tornado application."""
    return tornado.web.Application([
        # Auth
        (r"/api/auth/register", RegisterHandler),
        (r"/api/auth/login", LoginHandler),
        (r"/api/auth/me", MeHandler),

        # Super Admin: Company management
        (r"/api/admin/companies", CompaniesHandler),
        (r"/api/admin/companies/(\d+)", CompanyDetailHandler),

        # Company settings
        (r"/api/company/settings", CompanySettingsHandler),

        # Cards
        (r"/api/cards", CardsHandler),
        (r"/api/cards/(\d+)", CardHandler),

        # Expenses
        (r"/api/expenses", ExpensesHandler),
        (r"/api/expenses/(\d+)/approve", ExpenseApproveHandler),
        (r"/api/expenses/(\d+)/reject", ExpenseRejectHandler),

        # Approvals
        (r"/api/approvals", ApprovalsHandler),

        # Dashboard
        (r"/api/dashboard", DashboardHandler),
        (r"/api/gst", GSTHandler),

        # Team
        (r"/api/team", TeamHandler),

        # Analytics
        (r"/api/analytics", AnalyticsHandler),

        # Waitlist
        (r"/api/waitlist", WaitlistHandler),

        # Static
        (r"/", LandingHandler),
        (r"/app", AppHandler),
        (r"/static/(.*)", tornado.web.StaticFileHandler, {"path": "static"}),
    ], debug=True)


if __name__ == "__main__":
    import sys

    # Initialize database
    init_db()

    # Seed demo data if requested
    if len(sys.argv) > 1 and sys.argv[1] == "--seed":
        seed_demo_data()
        print("Demo data seeded!")

    # Start server
    port = int(os.environ.get("PORT", 8080))
    app = make_app()
    print(f"Nexo.money API running on http://0.0.0.0:{port}")
    app.listen(port, address="0.0.0.0")
    tornado.ioloop.IOLoop.current().start()
