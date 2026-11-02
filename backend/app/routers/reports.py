"""Reports endpoints (Phase 8): daily, range, CSV export."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_admin
from ..models import InstagramAccount, User
from ..services import reports as report_service

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"Invalid date (expected YYYY-MM-DD): {value}")


@router.get("/daily")
def daily(
    report_date: str = Query(..., description="YYYY-MM-DD"),
    account_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    d = _parse_date(report_date)
    row = report_service.generate_daily_report(db, d, account_id)
    acc = db.get(InstagramAccount, account_id) if account_id else None
    return {
        "report_date": row.report_date,
        "account": acc.username if acc else None,
        "account_id": account_id,
        "total_detected": row.total_detected,
        "total_scheduled": row.total_scheduled,
        "total_published": row.total_published,
        "total_failed": row.total_failed,
        "total_pending": row.total_pending,
    }


@router.post("/generate")
def generate(
    report_date: str = Query(..., description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    d = _parse_date(report_date)
    rows = [report_service.generate_daily_report(db, d, None)]
    for acc in db.query(InstagramAccount).all():
        rows.append(report_service.generate_daily_report(db, d, acc.id))
    return {"generated": len(rows), "report_date": d.isoformat()}


@router.get("")
def range_report(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    account_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    return report_service.build_range_report(db, _parse_date(start), _parse_date(end), account_id)


@router.get("/export.csv")
def export_csv(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    account_id: int | None = None,
    db: Session = Depends(get_db),
    _=Depends(get_current_user),
):
    report = report_service.build_range_report(db, _parse_date(start), _parse_date(end), account_id)
    csv_text = report_service.report_to_csv(report)
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="report-{start}-to-{end}.csv"'},
    )
