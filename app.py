"""
Nexo.money - Corporate Card & Expense Management Platform
REST API server using Tornado
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
from datetime import datetime, timedelta
from urllib.parse import parse_qs

from models import (
    init_db, get_db, hash_password, verify_password, seed_demo_data
)

# Secret for token signing
TOKEN_SECRET = "nexo-secret-key-2024"
TOKEN_EXPIRY = 7 * 24 * 60 * 60  # 7 days


class BaseHandler(tornado.web.RequestHandler):
    """Base handler with CORS and auth utilities."""

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
        """Extract and validate user from token."""
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
            cursor.execute("SELECT id, email, name, role, company_id FROM users WHERE id = ?", (user_id,))
            user = cursor.fetchone()
            conn.close()

            if not user:
                return None

            return {
                "id": user["id"],
                "email": user["email"],
                "name": user["name"],
                "role": user["role"],
                "company_id": user["company_id"]
            }
        except Exception:
            return None

    def require_auth(self):
        """Require authentication."""
        user = self.get_current_user()
        if not user:
            self.set_status(401)
            self.write_json({"error": "Unauthorized"}, 401)
            return None
        return user


def generate_token(user_id):
    """Generate JWT-like token."""
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
        """POST /api/auth/register - Register new company + admin user."""
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

            # Create admin user
            pwd_hash = hash_password(password)
            cursor.execute("""
                INSERT INTO users (email, password_hash, name, role, company_id)
                VALUES (?, ?, ?, ?, ?)
            """, (email, pwd_hash, name, "admin", company_id))
            user_id = cursor.lastrowid

            conn.commit()
            conn.close()

            token = generate_token(user_id)
            self.write_json({
                "token": token,
                "user": {
                    "id": user_id,
                    "email": email,
                    "name": name,
                    "role": "admin",
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
                SELECT id, password_hash, name, role, company_id
                FROM users WHERE email = ?
            """, (email,))
            user = cursor.fetchone()
            conn.close()

            if not user or not verify_password(user["password_hash"], password):
                return self.write_json({"error": "Invalid credentials"}, 401)

            token = generate_token(user["id"])
            self.write_json({
                "token": token,
                "user": {
                    "id": user["id"],
                    "email": email,
                    "name": user["name"],
                    "role": user["role"],
                    "company_id": user["company_id"]
                }
            })
        except Exception as e:
            self.write_json({"error": str(e)}, 500)


class MeHandler(BaseHandler):
    def get(self):
        """GET /api/auth/me - Get current user."""
        user = self.require_auth()
        if not user:
            return
        self.write_json({"user": user})


# ============================================================================
# CARD ENDPOINTS
# ============================================================================

class CardsHandler(BaseHandler):
    def get(self):
        """GET /api/cards - List cards for company."""
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, user_id, card_number, card_type, status,
                   daily_limit, monthly_limit, spent_today, spent_month, created_at
            FROM cards WHERE company_id = ?
            ORDER BY created_at DESC
        """, (user["company_id"],))
        cards = [dict(row) for row in cursor.fetchall()]
        conn.close()

        self.write_json({"cards": cards})

    def post(self):
        """POST /api/cards - Issue new card."""
        user = self.require_auth()
        if not user:
            return

        try:
            data = json.loads(self.request.body)
            user_id = data.get("user_id", user["id"])
            card_type = data.get("card_type", "virtual")
            daily_limit = data.get("daily_limit", 25000)
            monthly_limit = data.get("monthly_limit", 150000)

            conn = get_db()
            cursor = conn.cursor()

            # Check user belongs to company
            cursor.execute("""
                SELECT id FROM users WHERE id = ? AND company_id = ?
            """, (user_id, user["company_id"]))
            if not cursor.fetchone():
                conn.close()
                return self.write_json({"error": "User not found"}, 404)

            # Generate masked card number
            import random
            last_four = str(random.randint(1000, 9999))
            masked = f"**** **** **** {last_four}"

            cursor.execute("""
                INSERT INTO cards (company_id, user_id, card_number, card_type,
                                  daily_limit, monthly_limit)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user["company_id"], user_id, masked, card_type, daily_limit, monthly_limit))
            card_id = cursor.lastrowid

            conn.commit()
            conn.close()

            cursor.execute("""
                SELECT id, user_id, card_number, card_type, status,
                       daily_limit, monthly_limit, spent_today, spent_month, created_at
                FROM cards WHERE id = ?
            """, (card_id,))
            # Re-open connection to fetch
            conn = get_db()
            cursor = conn.cursor()
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
        """PUT /api/cards/:id - Update card."""
        user = self.require_auth()
        if not user:
            return

        try:
            data = json.loads(self.request.body)
            daily_limit = data.get("daily_limit")
            monthly_limit = data.get("monthly_limit")
            status = data.get("status")

            conn = get_db()
            cursor = conn.cursor()

            # Verify card belongs to company
            cursor.execute("""
                SELECT id FROM cards WHERE id = ? AND company_id = ?
            """, (card_id, user["company_id"]))
            if not cursor.fetchone():
                conn.close()
                return self.write_json({"error": "Card not found"}, 404)

            # Update card
            updates = []
            params = []
            if daily_limit is not None:
                updates.append("daily_limit = ?")
                params.append(daily_limit)
            if monthly_limit is not None:
                updates.append("monthly_limit = ?")
                params.append(monthly_limit)
            if status is not None:
                updates.append("status = ?")
                params.append(status)

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
        """GET /api/expenses - List expenses with filters."""
        user = self.require_auth()
        if not user:
            return

        status = self.get_argument("status", None)
        category = self.get_argument("category", None)
        start_date = self.get_argument("start_date", None)
        end_date = self.get_argument("end_date", None)

        conn = get_db()
        cursor = conn.cursor()

        query = """
            SELECT id, user_id, card_id, amount, currency, merchant_name,
                   category, description, receipt_url, gstin_vendor,
                   gst_amount, igst, cgst, sgst, status, approved_by, created_at
            FROM expenses WHERE company_id = ?
        """
        params = [user["company_id"]]

        if status:
            query += " AND status = ?"
            params.append(status)
        if category:
            query += " AND category = ?"
            params.append(category)
        if start_date:
            query += " AND created_at >= ?"
            params.append(start_date)
        if end_date:
            query += " AND created_at <= ?"
            params.append(end_date)

        query += " ORDER BY created_at DESC"

        cursor.execute(query, params)
        expenses = [dict(row) for row in cursor.fetchall()]
        conn.close()

        self.write_json({"expenses": expenses})

    def post(self):
        """POST /api/expenses - Create expense."""
        user = self.require_auth()
        if not user:
            return

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

            # Calculate GST
            gst_rate = 0.05 if amount < 5000 else 0.18
            gst_amount = amount * gst_rate
            igst = gst_amount * 0.8
            cgst = gst_amount * 0.1
            sgst = gst_amount * 0.1

            # Auto-approve if under 5000
            auto_approve = amount < 5000
            status = "auto_approved" if auto_approve else "pending"
            approved_by = user["id"] if auto_approve else None

            conn = get_db()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO expenses (
                    company_id, user_id, card_id, amount, merchant_name,
                    category, description, receipt_url, gstin_vendor,
                    gst_amount, igst, cgst, sgst, status, approved_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user["company_id"], user["id"], card_id, amount, merchant_name,
                category, description, receipt_url, gstin_vendor,
                gst_amount, igst, cgst, sgst, status, approved_by
            ))
            expense_id = cursor.lastrowid

            # If not auto-approved, create approval record
            if not auto_approve:
                # Get an approver (first approver role user)
                cursor.execute("""
                    SELECT id FROM users
                    WHERE company_id = ? AND role IN ('approver', 'admin')
                    LIMIT 1
                """, (user["company_id"],))
                approver = cursor.fetchone()
                if approver:
                    cursor.execute("""
                        INSERT INTO approvals (expense_id, approver_id, status)
                        VALUES (?, ?, ?)
                    """, (expense_id, approver["id"], "pending"))

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
        """PUT /api/expenses/:id/approve - Approve expense."""
        user = self.require_auth()
        if not user:
            return

        try:
            data = json.loads(self.request.body)
            comment = data.get("comment", "")

            conn = get_db()
            cursor = conn.cursor()

            # Verify expense belongs to company
            cursor.execute("""
                SELECT id, status FROM expenses WHERE id = ? AND company_id = ?
            """, (expense_id, user["company_id"]))
            expense = cursor.fetchone()
            if not expense:
                conn.close()
                return self.write_json({"error": "Expense not found"}, 404)

            # Update expense status
            cursor.execute("""
                UPDATE expenses SET status = ?, approved_by = ?
                WHERE id = ?
            """, ("approved", user["id"], expense_id))

            # Update approval record
            cursor.execute("""
                UPDATE approvals SET status = ?, comment = ?
                WHERE expense_id = ?
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

        try:
            data = json.loads(self.request.body)
            comment = data.get("comment", "")

            conn = get_db()
            cursor = conn.cursor()

            # Verify expense belongs to company
            cursor.execute("""
                SELECT id FROM expenses WHERE id = ? AND company_id = ?
            """, (expense_id, user["company_id"]))
            if not cursor.fetchone():
                conn.close()
                return self.write_json({"error": "Expense not found"}, 404)

            # Update expense status
            cursor.execute("""
                UPDATE expenses SET status = ?
                WHERE id = ?
            """, ("rejected", expense_id))

            # Update approval record
            cursor.execute("""
                UPDATE approvals SET status = ?, comment = ?
                WHERE expense_id = ?
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
        """GET /api/dashboard - Company dashboard stats."""
        user = self.require_auth()
        if not user:
            return

        try:
            conn = get_db()
            cursor = conn.cursor()
            now = datetime.now()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

            # Total spend this month
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) as total
                FROM expenses
                WHERE company_id = ? AND created_at >= ? AND status != 'rejected'
            """, (user["company_id"], month_start.isoformat()))
            total_spend_month = cursor.fetchone()["total"]

            # Total spend today
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) as total
                FROM expenses
                WHERE company_id = ? AND created_at >= ? AND status != 'rejected'
            """, (user["company_id"], today_start.isoformat()))
            total_spend_today = cursor.fetchone()["total"]

            # Active cards
            cursor.execute("""
                SELECT COUNT(*) as count FROM cards
                WHERE company_id = ? AND status = 'active'
            """, (user["company_id"],))
            active_cards = cursor.fetchone()["count"]

            # Pending approvals
            cursor.execute("""
                SELECT COUNT(*) as count FROM approvals
                WHERE approver_id = ? AND status = 'pending'
            """, (user["id"],))
            pending_approvals = cursor.fetchone()["count"]

            # Spend by category (last 6 months)
            spend_by_category = {}
            for i in range(6):
                month_date = now - timedelta(days=30*i)
                month_start = month_date.replace(day=1)
                next_month = (month_start + timedelta(days=32)).replace(day=1)
                cursor.execute("""
                    SELECT category, COALESCE(SUM(amount), 0) as total
                    FROM expenses
                    WHERE company_id = ? AND created_at >= ? AND created_at < ?
                    AND status != 'rejected'
                    GROUP BY category
                """, (user["company_id"], month_start.isoformat(), next_month.isoformat()))
                for row in cursor.fetchall():
                    if row["category"] not in spend_by_category:
                        spend_by_category[row["category"]] = 0
                    spend_by_category[row["category"]] += row["total"]

            # Spend by team (last 3 months)
            spend_by_team = {}
            three_months_ago = now - timedelta(days=90)
            cursor.execute("""
                SELECT u.name, COALESCE(SUM(e.amount), 0) as total
                FROM expenses e
                JOIN users u ON e.user_id = u.id
                WHERE e.company_id = ? AND e.created_at >= ? AND e.status != 'rejected'
                GROUP BY e.user_id
                ORDER BY total DESC
                LIMIT 10
            """, (user["company_id"], three_months_ago.isoformat()))
            for row in cursor.fetchall():
                spend_by_team[row["name"]] = row["total"]

            # Top vendors (last 3 months)
            cursor.execute("""
                SELECT merchant_name, COUNT(*) as count, COALESCE(SUM(amount), 0) as total
                FROM expenses
                WHERE company_id = ? AND created_at >= ? AND status != 'rejected'
                GROUP BY merchant_name
                ORDER BY total DESC
                LIMIT 5
            """, (user["company_id"], three_months_ago.isoformat()))
            top_vendors = [{"name": row["merchant_name"], "count": row["count"], "spent": row["total"]}
                          for row in cursor.fetchall()]

            # Recent transactions (last 10)
            cursor.execute("""
                SELECT id, merchant_name, amount, category, status, created_at
                FROM expenses
                WHERE company_id = ?
                ORDER BY created_at DESC
                LIMIT 10
            """, (user["company_id"],))
            recent_transactions = [dict(row) for row in cursor.fetchall()]

            # Budget utilization
            budget_util = []
            cursor.execute("""
                SELECT category, monthly_limit, spent_this_month
                FROM budgets
                WHERE company_id = ? AND period = ?
            """, (user["company_id"], now.strftime("%Y-%m")))
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
        """GET /api/gst - GST analytics."""
        user = self.require_auth()
        if not user:
            return

        try:
            conn = get_db()
            cursor = conn.cursor()
            now = datetime.now()

            # Total GST paid
            cursor.execute("""
                SELECT COALESCE(SUM(gst_amount), 0) as total
                FROM expenses
                WHERE company_id = ? AND status != 'rejected'
            """, (user["company_id"],))
            total_gst_paid = cursor.fetchone()["total"]

            # Claimable ITC (all GST amounts)
            claimable_itc = total_gst_paid

            # ITC recovery rate (simplified: 85%)
            itc_recovery_rate = 85

            # GST by month (last 12 months)
            gst_by_month = {}
            for i in range(12):
                month_date = now - timedelta(days=30*i)
                month_start = month_date.replace(day=1)
                next_month = (month_start + timedelta(days=32)).replace(day=1)
                cursor.execute("""
                    SELECT COALESCE(SUM(gst_amount), 0) as total
                    FROM expenses
                    WHERE company_id = ? AND created_at >= ? AND created_at < ?
                    AND status != 'rejected'
                """, (user["company_id"], month_start.isoformat(), next_month.isoformat()))
                month_key = month_start.strftime("%Y-%m")
                gst_by_month[month_key] = cursor.fetchone()["total"]

            # Missing GSTIN count
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM expenses
                WHERE company_id = ? AND gstin_vendor IS NULL AND status != 'rejected'
            """, (user["company_id"],))
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
        """GET /api/team - List team members."""
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, email, name, role, created_at
            FROM users WHERE company_id = ?
            ORDER BY created_at
        """, (user["company_id"],))
        team = [dict(row) for row in cursor.fetchall()]
        conn.close()

        self.write_json({"team": team})

    def post(self):
        """POST /api/team - Add team member."""
        user = self.require_auth()
        if not user:
            return

        try:
            data = json.loads(self.request.body)
            email = data.get("email")
            name = data.get("name")
            role = data.get("role", "employee")
            password = data.get("password", "TempPass123!")
            issue_card = data.get("issue_card", False)

            if not email or not name:
                return self.write_json({"error": "Missing required fields"}, 400)

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
                INSERT INTO users (email, password_hash, name, role, company_id)
                VALUES (?, ?, ?, ?, ?)
            """, (email, pwd_hash, name, role, user["company_id"]))
            user_id = cursor.lastrowid

            card_id = None
            if issue_card:
                import random
                last_four = str(random.randint(1000, 9999))
                masked = f"**** **** **** {last_four}"
                cursor.execute("""
                    INSERT INTO cards (company_id, user_id, card_number, card_type)
                    VALUES (?, ?, ?, ?)
                """, (user["company_id"], user_id, masked, "virtual"))
                card_id = cursor.lastrowid

            conn.commit()
            conn.close()

            self.write_json({
                "user": {
                    "id": user_id,
                    "email": email,
                    "name": name,
                    "role": role,
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
        """GET /api/analytics - Analytics data."""
        user = self.require_auth()
        if not user:
            return

        try:
            conn = get_db()
            cursor = conn.cursor()
            now = datetime.now()

            # Spend trend (12 months)
            spend_trend = {}
            for i in range(12, 0, -1):
                month_date = now - timedelta(days=30*i)
                month_start = month_date.replace(day=1)
                next_month = (month_start + timedelta(days=32)).replace(day=1)
                cursor.execute("""
                    SELECT COALESCE(SUM(amount), 0) as total
                    FROM expenses
                    WHERE company_id = ? AND created_at >= ? AND created_at < ?
                    AND status != 'rejected'
                """, (user["company_id"], month_start.isoformat(), next_month.isoformat()))
                month_key = month_start.strftime("%Y-%m")
                spend_trend[month_key] = cursor.fetchone()["total"]

            # Category breakdown
            cursor.execute("""
                SELECT category, COALESCE(SUM(amount), 0) as total, COUNT(*) as count
                FROM expenses
                WHERE company_id = ? AND status != 'rejected'
                GROUP BY category
            """, (user["company_id"],))
            category_breakdown = [{"category": row["category"], "spent": row["total"], "count": row["count"]}
                                 for row in cursor.fetchall()]

            # Top merchants
            cursor.execute("""
                SELECT merchant_name, COALESCE(SUM(amount), 0) as total, COUNT(*) as count
                FROM expenses
                WHERE company_id = ? AND status != 'rejected'
                GROUP BY merchant_name
                ORDER BY total DESC
                LIMIT 10
            """, (user["company_id"],))
            top_merchants = [{"merchant": row["merchant_name"], "spent": row["total"], "count": row["count"]}
                            for row in cursor.fetchall()]

            # Average transaction size
            cursor.execute("""
                SELECT COALESCE(AVG(amount), 0) as avg_size
                FROM expenses
                WHERE company_id = ? AND status != 'rejected'
            """, (user["company_id"],))
            avg_transaction_size = cursor.fetchone()["avg_size"]

            # Total transactions
            cursor.execute("""
                SELECT COUNT(*) as total
                FROM expenses
                WHERE company_id = ? AND status != 'rejected'
            """, (user["company_id"],))
            total_transactions = cursor.fetchone()["total"]

            # Cards utilization
            cursor.execute("""
                SELECT c.id, c.card_number, COALESCE(SUM(e.amount), 0) as spent,
                       c.monthly_limit, c.spent_month
                FROM cards c
                LEFT JOIN expenses e ON c.id = e.card_id AND e.status != 'rejected'
                WHERE c.company_id = ?
                GROUP BY c.id
            """, (user["company_id"],))
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
        try:
            with open("templates/landing.html", "r") as f:
                self.write(f.read())
        except FileNotFoundError:
            self.write("<h1>Nexo.money - Coming Soon</h1>")


class AppHandler(BaseHandler):
    def get(self):
        """Serve app page."""
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

        # Cards
        (r"/api/cards", CardsHandler),
        (r"/api/cards/(\d+)", CardHandler),

        # Expenses
        (r"/api/expenses", ExpensesHandler),
        (r"/api/expenses/(\d+)/approve", ExpenseApproveHandler),
        (r"/api/expenses/(\d+)/reject", ExpenseRejectHandler),

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
