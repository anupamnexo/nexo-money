# Nexo.money API - Quick Start Guide

## Setup & Running

### 1. Initialize the database
```bash
cd nexo-mvp
python models.py
```

### 2. Start the server with demo data
```bash
python app.py --seed
```

Server runs on: `http://localhost:8080`

## Demo Credentials

When you run with `--seed`, you get a company "TechNova Solutions" with these users:

| Email | Password | Role |
|-------|----------|------|
| priya.shah@technova.com | SecurePass123! | admin |
| rajesh.kumar@technova.com | SecurePass123! | approver |
| neha.patel@technova.com | SecurePass123! | employee |
| amit.singh@technova.com | SecurePass123! | employee |
| deepak.gupta@technova.com | SecurePass123! | approver |
| anjali.verma@technova.com | SecurePass123! | employee |

## API Examples

### 1. Login and Get Token

```bash
curl -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "priya.shah@technova.com",
    "password": "SecurePass123!"
  }'
```

Response:
```json
{
  "token": "MToxNzcyNDc0ODMxOmExN2Q4MTEzNmFkNTI1YWE4OTNhMzgyNG...",
  "user": {
    "id": 1,
    "email": "priya.shah@technova.com",
    "name": "Priya Shah",
    "role": "admin",
    "company_id": 1
  }
}
```

Save the token: `TOKEN="MToxNzcyNDc0ODMxOmExN2Q4MTEzNmFkNTI1YWE4OTNhMzgyNG..."`

### 2. Get Current User Info

```bash
curl -X GET http://localhost:8080/api/auth/me \
  -H "Authorization: Bearer $TOKEN"
```

### 3. View All Cards

```bash
curl -X GET http://localhost:8080/api/cards \
  -H "Authorization: Bearer $TOKEN"
```

### 4. Issue New Card

```bash
curl -X POST http://localhost:8080/api/cards \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "user_id": 3,
    "card_type": "virtual",
    "daily_limit": 25000,
    "monthly_limit": 150000
  }'
```

### 5. Create Expense (Auto-Approved if < ₹5000)

```bash
curl -X POST http://localhost:8080/api/expenses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "card_id": 1,
    "amount": 3500,
    "merchant_name": "Zomato",
    "category": "meals",
    "description": "Team lunch meeting",
    "gstin_vendor": "09AAACR5055K2Z0"
  }'
```

Response:
```json
{
  "expense": {
    "id": 183,
    "amount": 3500,
    "merchant_name": "Zomato",
    "category": "meals",
    "status": "auto_approved",
    "created_at": "2026-03-02T15:30:00"
  }
}
```

### 6. Create Expense (Requires Approval if >= ₹5000)

```bash
curl -X POST http://localhost:8080/api/expenses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "card_id": 1,
    "amount": 15000,
    "merchant_name": "AWS India",
    "category": "software",
    "description": "AWS monthly bill",
    "gstin_vendor": "18AAHCU3044R1Z2"
  }'
```

Response:
```json
{
  "expense": {
    "id": 184,
    "amount": 15000,
    "merchant_name": "AWS India",
    "category": "software",
    "status": "pending",
    "created_at": "2026-03-02T15:30:00"
  }
}
```

### 7. View Expenses with Filters

```bash
# Get all pending expenses
curl -X GET "http://localhost:8080/api/expenses?status=pending" \
  -H "Authorization: Bearer $TOKEN"

# Get meals category expenses
curl -X GET "http://localhost:8080/api/expenses?category=meals" \
  -H "Authorization: Bearer $TOKEN"

# Get expenses in date range
curl -X GET "http://localhost:8080/api/expenses?start_date=2026-02-01&end_date=2026-03-02" \
  -H "Authorization: Bearer $TOKEN"
```

### 8. Approve Expense (As Approver)

First, login as approver:
```bash
curl -X POST http://localhost:8080/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "rajesh.kumar@technova.com",
    "password": "SecurePass123!"
  }'
```

Save token as: `APPROVER_TOKEN="..."`

Then approve:
```bash
curl -X PUT http://localhost:8080/api/expenses/184/approve \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $APPROVER_TOKEN" \
  -d '{
    "comment": "Approved - valid AWS bill"
  }'
```

### 9. Reject Expense

```bash
curl -X PUT http://localhost:8080/api/expenses/184/reject \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $APPROVER_TOKEN" \
  -d '{
    "comment": "Missing receipt documentation"
  }'
```

### 10. Get Dashboard Stats

```bash
curl -X GET http://localhost:8080/api/dashboard \
  -H "Authorization: Bearer $TOKEN"
```

Response shows:
- Monthly and daily spend
- Active cards count
- Pending approvals
- Spend by category & team
- Top vendors
- Recent transactions
- Budget utilization

### 11. Get GST Analytics

```bash
curl -X GET http://localhost:8080/api/gst \
  -H "Authorization: Bearer $TOKEN"
```

Response:
```json
{
  "gst": {
    "total_gst_paid": 189436.49,
    "claimable_itc": 189436.49,
    "itc_recovery_rate": 85,
    "gst_by_month": {
      "2026-03": 45000,
      "2026-02": 38000
    },
    "missing_gstin_count": 12
  }
}
```

### 12. View Team Members

```bash
curl -X GET http://localhost:8080/api/team \
  -H "Authorization: Bearer $TOKEN"
```

### 13. Add Team Member

```bash
curl -X POST http://localhost:8080/api/team \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "email": "varun.sharma@technova.com",
    "name": "Varun Sharma",
    "role": "employee",
    "password": "TempPassword123!",
    "issue_card": true
  }'
```

### 14. Get Analytics

```bash
curl -X GET http://localhost:8080/api/analytics \
  -H "Authorization: Bearer $TOKEN"
```

Response shows:
- 12-month spend trend
- Category breakdown
- Top 10 merchants
- Average transaction size
- Card utilization rates

### 15. Update Card Limits

```bash
curl -X PUT http://localhost:8080/api/cards/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "daily_limit": 15000,
    "monthly_limit": 100000,
    "status": "frozen"
  }'
```

### 16. Register New Company

```bash
curl -X POST http://localhost:8080/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "company_name": "StartupXYZ",
    "email": "founder@startupxyz.com",
    "password": "SecurePassword123!",
    "name": "Founder Name",
    "gstin": "29XXXXX1234P1Z5"
  }'
```

### 17. Add to Waitlist

```bash
curl -X POST http://localhost:8080/api/waitlist \
  -H "Content-Type: application/json" \
  -d '{
    "email": "interest@company.com",
    "company_name": "Another Company",
    "phone": "+91-9876543210"
  }'
```

## Key Data Points (Demo)

- **Company**: TechNova Solutions
- **GSTIN**: 29AABCT1234P1Z5
- **Total Spend**: ₹1,206,597 (6 months)
- **Total GST**: ₹189,436.49
- **Cards**: 12 (mix of virtual/physical)
- **Team**: 6 members
- **Expenses**: 182 records
- **Auto-Approved**: 80 (under ₹5000)
- **Pending**: 102 (need approval)

## Testing Workflow

### Scenario 1: Create and Auto-Approve Expense
1. Create expense under ₹5000 → Automatically approved
2. Check dashboard → Shows in total spend

### Scenario 2: Create and Manually Approve
1. Create expense over ₹5000 → Status: pending
2. Login as approver
3. Call approve endpoint → Status: approved
4. Dashboard updates with approved amount

### Scenario 3: Team Expense Management
1. Employee creates expense
2. Approver reviews in dashboard
3. Approver approves/rejects
4. System updates budget utilization
5. GST tracking updates automatically

## Database Inspection

To inspect the database directly:

```bash
sqlite3 nexo.db

# View all companies
SELECT * FROM companies;

# View all users
SELECT id, email, name, role FROM users;

# View all expenses
SELECT id, merchant_name, amount, category, status FROM expenses LIMIT 10;

# View GST data
SELECT SUM(gst_amount), SUM(igst), SUM(cgst), SUM(sgst) FROM expenses;

# View pending approvals
SELECT COUNT(*) FROM approvals WHERE status = 'pending';
```

## Tips

1. **Save tokens** in environment variables for easier testing
2. **Use Postman** for easier API testing with headers
3. **Check status codes** - 401 = auth needed, 404 = not found, 400 = bad request
4. **All dates** are in ISO format (YYYY-MM-DDTHH:MM:SS)
5. **INR amounts** are in rupees (no decimal limit)
6. **Card numbers** are masked in API responses
7. **Approvers** can only approve expenses they're assigned to
8. **Budget updates** happen when expenses are approved

## Troubleshooting

**Port already in use?**
```bash
# Kill existing process
pkill -f "python app.py"
# Or change port in app.py and restart
```

**Database locked?**
```bash
# Delete and reinitialize
rm nexo.db
python models.py
python app.py --seed
```

**Token expired?**
- Get a new token by logging in again

**Unauthorized error?**
- Check token is included in Authorization header
- Verify token hasn't expired (7 days)

## Next Steps

1. Build frontend using the API
2. Integrate with payment gateway
3. Add real card issuance
4. Implement webhook notifications
5. Add analytics exports (CSV, PDF)
6. Build mobile app
