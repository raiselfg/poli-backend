from fastapi import APIRouter, HTTPException

from app.api.dependencies import ContactServiceDep, CurrentSessionDep
from app.schemas.contact import ContactRead, ContactUpdate
from app.services.contact import ContactNotFoundError, InvalidContactError

router = APIRouter(tags=["contacts"])


@router.get("/contacts", response_model=ContactRead)
async def get_contacts(service: ContactServiceDep):
    try:
        return await service.get()
    except ContactNotFoundError:
        raise HTTPException(status_code=404, detail="Contacts not found") from None


@router.patch("/admin/contacts", response_model=ContactRead)
async def update_contacts(
    body: ContactUpdate, service: ContactServiceDep, current_session: CurrentSessionDep
):
    try:
        return await service.update(body)
    except ContactNotFoundError:
        raise HTTPException(status_code=404, detail="Contacts not found") from None
    except InvalidContactError:
        raise HTTPException(status_code=422, detail="Invalid contact fields") from None
