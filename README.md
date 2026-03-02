# Nexo.money - Corporate Card & Expense Management Platform

A fintech MVP backend for Indian SMEs featuring corporate card management, expense tracking, GST compliance, and team expense approvals.

## Architecture

- **Database**: SQLite3 with 8 tables (companies, users, cards, expenses, approvals, budgets, vendors, waitlist)
- **Server**: Tornado web server with REST API
- **Auth**: JWT-like token system (base64 encoded user_id:timestamp:signature)
- **Port**: 8080

## Files

### 1. `models.py`
Database layer with SQLite3 schema and utilities.

**Tables:**
- `companies` - Company details (GSTIN, PAN, industry)
- `users` - Team members (email, role: admin/employee/approver)
- `cards` - Corporate cards (virtual/physical, limits)
- `expenses` - Expense records with GST breakdown
- `approvals` - Approval workflow tracking
- `budgets` - Category and team budgets
- `vendors` - Vendor information and spend tracking
- `waitlist` - Early access signups

**Key Functions:**
- `init_db()` - Initialize database schema
- `get_db()` - Get database connection
- `hash_password(password)` - PBKDF2-SHA256 with salt
- `verify_password(hash, password)` - Verify stored hash
- `seed_demo_data()` - Populate realistic test data for TechNova Solutions

### 2. `app.py`
Tornado web server with REST API endpoints.

## Running the Application

### 1. Initialize Database
```bash
python models.py
```

### 2. Start Server (without demo data)
```bash
python app.py
```

### 3. Start Server with Demo Data
```bash
python app.py --seed
```

Server runs on `http://localhost:8080`

## API Endpoints

### Authentication

#### POST `/api/auth/register`
Register new company and admin user.

```json
{
  "company_name": "TechNova Solutions",
  "gstin": "29AABCT1234P1Z5",
  "email": "admin@technova.com",
  "password": "SecurePass123!",
  "name": "Priya Shah"
}
```

Response:
```json
{
  "token": "base64_encoded_token",
  "user": {
    "id": 1,
    "email": "admin@technova.com",
    "name": "Priya Shah",
    "role": "admin",
    "company_id": 1
  }
}
```

#### POST `/api/auth/login`
Login user with email and password.

```json
{
  "email": "admin@technova.com",
  "password": "SecurePass123!"
}
```

#### GET `/api/auth/me`
Get current authenticated user (requires Authorization header).

Header: `Authorization: Bearer <token>`

### Cards

#### GET `/api/cards`
List all cards for company.

Response:
```json
{
  "cards": [
    {
      "id": 1,
      "user_id": 3,
      "card_number": "**** **** **** 4521",
      "card_type": "virtual",
      "status": "active",
      "daily_limit": 25000,
      "monthly_limit": 150000,
      "spent_today": 5200,
      "spent_month": 42100,
      "created_at": "2026-03-01T10:30:00"
    }
  ]
}
```

#### POST `/api/cards`
Issue new card for employee.

```json
{
  "user_id": 3,
  "card_type": "virtual",
  "daily_limit": 25000,
  "monthly_limit": 150000
}
```

#### PUT `/api/cards/:id`
Update card limits or status.

```json
{
  "status": "frozen",
  "daily_limit": 10000
}
```

### Expenses

#### GET `/api/expenses`
List expenses with optional filters.

Query Parameters:
- `status` - pending, approved, rejected, auto_approved
- `category` - travel, meals, office, software, marketing, other
- `start_date` - ISO format date
- `end_date` - ISO format date

Response:
```json
{
  "expenses": [
    {
      "id": 1,
      "user_id": 3,
      "card_id": 1,
      "amount": 2500,
      "currency": "INR",
      "merchant_name": "Uber",
      "category": "travel",
      "description": "Business trip to Mumbai",
      "receipt_url": null,
      "gstin_vendor": "18AAFCU5055K1ZO",
      "gst_amount": 125,
      "igst": 100,
      "cgst": 12.5,
      "sgst": 12.5,
      "status": "auto_approved",
      "approved_by": 1,
      "created_at": "2026-02-28T14:20:00"
    }
  ]
}
```

#### POST `/api/expenses`
Create new expense record. Auto-approves if under ₹5000.

```json
{
  "card_id": 1,
  "amount": 3200,
  "merchant_name": "Zomato",
  "category": "meals",
  "description": "Team lunch - client meeting",
  "receipt_url": "https://...",
  "gstin_vendor": "09AAACR5055K2Z0"
}
```

#### PUT `/api/expenses/:id/approve`
Approve pending expense.

```json
{
  "comment": "Approved - valid business expense"
}
```

#### PUT `/api/expenses/:id/reject`
Reject pending expense.

```json
{
  "comment": "Needs proper documentation"
}
```

### Dashboard

#### GET `/api/dashboard`
Comprehensive dashboard statistics.

Response:
```json
{
  "dashboard": {
    "total_spend_month": 156420.50,
    "total_spend_today": 8920.00,
    "active_cards": 12,
    "pending_approvals": 5,
    "spend_by_category": {
      "travel": 45000,
      "meals": 12000,
      "software": 78000,
      "office": 21000
    },
    "spend_by_team": {
      "Neha Patel": 32000,
      "Amit Singh": 28500,
      "Anjali Verma": 19200
    },
    "top_vendors": [
      {
        "name": "AWS India",
        "count": 8,
        "spent": 125000
      }
    ],
    "recent_transactions": [...],
    "budget_utilization": [
      {
        "category": "travel",
        "limit": 300000,
        "spent": 145000,
        "utilization": 48.33
      }
    ]
  }
}
```

#### GET `/api/gst`
GST compliance analytics.

Response:
```json
{
  "gst": {
    "total_gst_paid": 189436.49,
    "claimable_itc": 189436.49,
    "itc_recovery_rate": 85,
    "gst_by_month": {
      "2026-03": 45000,
      "2026-02": 38000,
      "2026-01": 52000
    },
    "missing_gstin_count": 12
  }
}
```

### Team

#### GET `/api/team`
List all team members.

Response:
```json
{
  "team": [
    {
      "id": 1,
      "email": "priya.shah@technova.com",
      "name": "Priya Shah",
      "role": "admin",
      "created_at": "2026-01-15T09:00:00"
    }
  ]
}
```

#### POST `/api/team`
Add new team member and optionally issue card.

```json
{
  "email": "neha.patel@technova.com",
  "name": "Neha Patel",
  "role": "employee",
  "password": "TempPass123!",
  "issue_card": true
}
```

### Analytics

#### GET `/api/analytics`
Comprehensive analytics data.

Response:
```json
{
  "analytics": {
    "spend_trend": {
      "2026-01": 156000,
      "2026-02": 189000,
      "2026-03": 210000
    },
    "category_breakdown": [
      {
        "category": "software",
        "spent": 347100,
        "count": 30
      }
    ],
    "top_merchants": [
      {
        "merchant": "AWS India",
        "spent": 125000,
        "count": 8
      }
    ],
    "avg_transaction_size": 6629.65,
    "cards_utilization": [
      {
        "card": "**** **** **** 4521",
        "spent": 42100,
        "limit": 150000,
        "utilization": 28.07
      }
    ]
  }
}
```

### Waitlist

#### POST `/api/waitlist`
Add email to early access waitlist.

```json
{
  "email": "startup@example.com",
  "company_name": "Example Corp",
  "phone": "+91-9876543210"
}
```

## Demo Data

Run `python app.py --seed` to populate database with:

- **Company**: TechNova Solutions (GSTIN: 29AABCT1234P1Z5)
- **Team**: 6 members (1 admin, 2 approvers, 3 employees)
- **Cards**: 12 cards (mix of virtual and physical)
- **Expenses**: 182 expenses over 6 months
- **Budgets**: 5 categories with limits
- **Vendors**: 5 vendors with transaction history
- **GST Data**: Complete tax breakdown across all expenses

**Expense Distribution:**
- Software: 30 txns = ₹347,100
- Travel: 31 txns = ₹310,310
- Other: 30 txns = ₹173,040
- Marketing: 30 txns = ₹170,670
- Office: 30 txns = ₹144,970
- Meals: 31 txns = ₹60,507

**Total**: ₹1.2M+ spend with ₹189k+ GST captured

## Authentication

All API endpoints (except `/api/auth/register`, `/api/auth/login`, `/api/waitlist`) require authentication.

Include token in header:
```
Authorization: Bearer <token>
```

Token format: Base64 encoded `{user_id}:{timestamp}:{hmac_sha256_signature}`

Token expiry: 7 days

## CORS

All endpoints support CORS. Headers included:
- `Access-Control-Allow-Origin: *`
- `Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS`
- `Access-Control-Allow-Headers: Content-Type, Authorization`

## Error Handling

All errors return JSON with status code:

```json
{
  "error": "Unauthorized",
  "status": 401
}
```

Common status codes:
- 200 - Success
- 201 - Created
- 400 - Bad Request
- 401 - Unauthorized
- 404 - Not Found
- 500 - Server Error

## Database Schema

### Companies
```
id (PK), name (UNIQUE), gstin (UNIQUE), pan (UNIQUE),
industry, city, plan (free/premium/enterprise), created_at
```

### Users
```
id (PK), email (UNIQUE), password_hash, name, role,
company_id (FK), created_at
```

### Cards
```
id (PK), company_id (FK), user_id (FK), card_number,
card_type (virtual/physical), status (active/frozen/cancelled),
daily_limit, monthly_limit, spent_today, spent_month,
merchant_category_restriction, created_at
```

### Expenses
```
id (PK), company_id (FK), user_id (FK), card_id (FK),
amount, currency, merchant_name, category, description,
receipt_url, gstin_vendor, gst_amount, igst, cgst, sgst,
status (pending/approved/rejected/auto_approved),
approved_by (FK), created_at
```

### Approvals
```
id (PK), expense_id (FK), approver_id (FK),
status (pending/approved/rejected), comment, created_at
```

### Budgets
```
id (PK), company_id (FK), team, category,
monthly_limit, spent_this_month, period (YYYY-MM), created_at
```

### Vendors
```
id (PK), company_id (FK), name, gstin,
total_spent, transaction_count, created_at
```

### Waitlist
```
id (PK), email (UNIQUE), company_name, phone, created_at
```

## Security Notes

- Passwords hashed with PBKDF2-HMAC-SHA256 + 32-byte salt
- Tokens signed with HMAC-SHA256
- 7-day token expiration
- User validation on token decode
- Company-level data isolation (users only see their company data)
- SQLite3 row factory for safe data access

## Future Enhancements

- Payment gateway integration (Razorpay, PayU)
- Real card issuance (BaaS partners)
- Advanced GST compliance reports
- Receipt OCR and auto-categorization
- Batch expense uploads
- Mobile app API
- Webhooks for expense events
- Advanced analytics (ML-based anomaly detection)
- Compliance certifications (SOC2, GDPR)

## License

Proprietary - Nexo.money
