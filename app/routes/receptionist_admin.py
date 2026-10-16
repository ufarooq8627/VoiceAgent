from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.receptionist import UnansweredEnquiry, Business
from app.services.enquiry_service import EnquiryService
from app.services.receptionist_export import ReceptionistExportService
from app.routes.auth import login_required

router = APIRouter(
    prefix="/admin/receptionist",
    dependencies=[Depends(login_required)],
    tags=["receptionist_admin"],
)
templates = Jinja2Templates(directory="app/templates")


@router.get("/enquiries", response_class=HTMLResponse)
def list_enquiries(request: Request, db: Session = Depends(get_db)):
    enquiries = (
        db.query(UnansweredEnquiry)
        .order_by(UnansweredEnquiry.created_at.desc())
        .all()
    )
    pending_count = sum(1 for e in enquiries if e.status == "pending")
    resolved_count = sum(1 for e in enquiries if e.status == "resolved")

    return templates.TemplateResponse(
        request=request,
        name="admin/enquiries.html",
        context={
            "enquiries": enquiries,
            "pending_count": pending_count,
            "resolved_count": resolved_count,
            "active_nav": "receptionist_enquiries",
        },
    )


@router.post("/enquiries/{enquiry_id}/resolve")
def resolve_enquiry(
    enquiry_id: str,
    owner_answer: str = Form(...),
    publish_to_kb: str = Form(None),
    db: Session = Depends(get_db),
):
    enq = db.query(UnansweredEnquiry).filter(UnansweredEnquiry.id == enquiry_id).first()
    if not enq:
        raise HTTPException(status_code=404, detail="Enquiry not found.")

    should_publish = publish_to_kb in ["true", "True", "on", "1"]
    EnquiryService.resolve_enquiry(
        db=db,
        business_id=enq.business_id,
        enquiry_id=enquiry_id,
        owner_answer=owner_answer,
        publish_to_kb=should_publish,
    )
    return RedirectResponse(url="/admin/receptionist/enquiries", status_code=303)


@router.get("/export")
@router.get("/export/{format_type}")
def export_enquiries(format_type: str = None, format: str = "xlsx", db: Session = Depends(get_db)):
    selected = (format_type or format or "xlsx").lower().strip()
    if selected == "csv":
        csv_stream = ReceptionistExportService.export_enquiries_csv(db)
        return Response(
            content=csv_stream.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=receptionist_enquiries.csv"},
        )
    elif selected == "json":
        json_data = ReceptionistExportService.export_enquiries_json(db)
        return Response(
            content=json_data,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=receptionist_enquiries.json"},
        )
    else:
        excel_stream = ReceptionistExportService.export_enquiries_xlsx(db)
        return Response(
            content=excel_stream.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=receptionist_enquiries.xlsx"},
        )
