# FinanceTracker

A dark, elegant personal finance web app built with Flask, SQLite, and Matplotlib.

## Features

- 🔐 **User Authentication** – Register/login, per-user data isolation
- 💸 **Expense Tracking** – Add, edit, delete expenses with categories and sub-categories
- 📊 **Dual Charts** – Pie chart (Essential vs Recreation) + Bar chart (by sub-category)
- 🗓 **Date Filters** – Last 7 days, This month, Last 3 months, This year, All time, Custom range
- 💰 **Budget Limits** – Set monthly caps, get visual alerts at 80% and 100%
- ⬇ **CSV Export** – Download all expenses as a spreadsheet
- 🛒 **Shopping List** – Add, edit, bulk check/uncheck, clear bought items
- 📱 **Responsive Design** – Works on mobile and desktop

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
python app.py
```

Then open **http://127.0.0.1:5000** in your browser.

## File Structure

```
finance_tracker/
├── app.py                  # Flask routes, DB logic, chart generation
├── requirements.txt
├── static/
│   ├── style.css           # All styles (dark theme, responsive)
│   └── charts/             # Generated chart PNGs (auto-created)
├── templates/
│   ├── base.html           # Navbar + layout shell
│   ├── auth.html           # Login / Register
│   ├── dashboard.html      # Charts, KPIs, recent expenses
│   ├── expenses.html       # Full expense management + export
│   ├── budgets.html        # Set & view monthly budget limits
│   └── shopping.html       # Shopping list with bulk update
└── data/
    └── finance.db          # SQLite database (auto-created)
```

## Categories

| Category     | Sub-categories                        |
|--------------|---------------------------------------|
| Essential    | Rent, Food, Transport                 |
| Recreation   | Entertainment, Hobbies, Eating out    |

## Production Notes

- Change `SECRET_KEY` via environment variable before deploying
- For multi-user production use, consider PostgreSQL instead of SQLite
- Serve static files via Nginx/Caddy in front of Gunicorn for best performance
