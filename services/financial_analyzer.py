"""Database-backed financial facts used by the chat orchestrator."""
from collections import defaultdict
from datetime import date, timedelta
from sqlalchemy import func
from sqlalchemy.orm import Session

from models import Budget, Category, SavingGoal, Transaction
from services.question_parser import ParsedQuestion


def analyze_finances(db: Session, user_id: int, parsed: ParsedQuestion) -> dict:
    transactions = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.txn_date >= parsed.start_date,
        Transaction.txn_date <= parsed.end_date,
    ).all()
    income = sum(float(item.amount) for item in transactions if item.type == "income")
    expense = sum(float(item.amount) for item in transactions if item.type == "expense")
    by_category = defaultdict(float)
    for item in transactions:
        if item.type == "expense":
            by_category[item.category.name if item.category else "Khác"] += float(item.amount)

    budgets = db.query(Budget).filter(Budget.user_id == user_id).all()
    budget_status = []
    for budget in budgets:
        month_start = date(budget.year, budget.month, 1)
        month_end = (
            date(budget.year + 1, 1, 1) - timedelta(days=1)
            if budget.month == 12
            else date(budget.year, budget.month + 1, 1) - timedelta(days=1)
        )
        budget_period_start = max(parsed.start_date, month_start)
        budget_period_end = min(parsed.end_date, month_end)
        if budget_period_start > budget_period_end:
            continue

        spent = db.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(
            Transaction.user_id == user_id,
            Transaction.type == "expense",
            Transaction.category_id == budget.category_id,
            Transaction.txn_date >= budget_period_start,
            Transaction.txn_date <= budget_period_end,
        ).scalar() or 0
        spent = float(spent)
        limit = float(budget.limit_amount)
        category = db.query(Category).filter(
            Category.id == budget.category_id,
            Category.user_id == user_id,
        ).first()
        budget_status.append({
            "category": category.name if category else "Khác",
            "spent": spent,
            "limit": limit,
            "remaining": max(0, limit - spent),
            "percent": round(spent / limit * 100, 1) if limit else 0,
            "exceeded": spent > limit,
        })

    goals = db.query(SavingGoal).filter(SavingGoal.user_id == user_id).all()

    return {
        "period": parsed.period,
        "start_date": parsed.start_date.isoformat(),
        "end_date": parsed.end_date.isoformat(),
        "income": round(income, 2),
        "expense": round(expense, 2),
        "balance": round(income - expense, 2),
        "saving_rate": round((income - expense) / income * 100, 1) if income else 0,
        "transaction_count": len(transactions),
        "top_categories": [
            {"name": name, "amount": round(amount, 2)}
            for name, amount in sorted(by_category.items(), key=lambda row: -row[1])[:5]
        ],
        "budgets": sorted(budget_status, key=lambda row: -row["percent"]),
        "budget_alerts": sorted([row for row in budget_status if row["percent"] >= 80], key=lambda row: -row["percent"]),
        "saving_goals": [
            {
                "name": goal.name,
                "target_amount": float(goal.target_amount),
                "current_amount": float(goal.current_amount or 0),
                "progress_percent": round(float(goal.current_amount or 0) / float(goal.target_amount) * 100, 1) if goal.target_amount else 0,
                "over_amount": max(0, float(goal.current_amount or 0) - float(goal.target_amount)),
            }
            for goal in goals
        ],
    }


def analyze_system(db: Session, parsed: ParsedQuestion) -> dict:
    """Return aggregate metadata only; never load a user's private finance rows."""
    from models import AILog, User

    return {
        "period": parsed.period,
        "start_date": parsed.start_date.isoformat(),
        "end_date": parsed.end_date.isoformat(),
        "total_users": db.query(func.count(User.id)).filter(User.role != "admin").scalar() or 0,
        "active_users": db.query(func.count(User.id)).filter(User.role != "admin", User.status == "active").scalar() or 0,
        "total_transactions": db.query(func.count(Transaction.id)).scalar() or 0,
        "ai_requests": db.query(func.count(AILog.id)).scalar() or 0,
        "private_data_access": False,
    }
