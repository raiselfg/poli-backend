from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from app.api.dependencies import CategoryServiceDep, CurrentSessionDep
from app.schemas.category import (
    CategoryAdmin,
    CategoryCreate,
    CategoryOrder,
    CategoryPublic,
    CategoryUpdate,
)
from app.services.category import (
    CategoryConflictError,
    CategoryNotFoundError,
    InvalidCategoryMediaError,
    InvalidCategoryOrderError,
)

router = APIRouter(tags=["categories"])


@router.get("/categories", response_model=list[CategoryPublic])
async def public_categories(service: CategoryServiceDep):
    return await service.list(published_only=True)


@router.get("/admin/categories", response_model=list[CategoryAdmin])
async def list_categories(service: CategoryServiceDep, current_session: CurrentSessionDep):
    return await service.list()


@router.put("/admin/categories/order", status_code=204)
async def reorder_categories(
    body: CategoryOrder, service: CategoryServiceDep, current_session: CurrentSessionDep
):
    try:
        await service.reorder(body.ids)
    except InvalidCategoryOrderError:
        raise HTTPException(status_code=422, detail="Invalid category order") from None
    return Response(status_code=204)


@router.post("/admin/categories", status_code=201, response_model=CategoryAdmin)
async def create_category(
    body: CategoryCreate, service: CategoryServiceDep, current_session: CurrentSessionDep
):
    try:
        return await service.create(body)
    except InvalidCategoryMediaError:
        raise HTTPException(status_code=422, detail="Invalid category media") from None
    except CategoryConflictError:
        raise HTTPException(status_code=409, detail="Category conflict") from None


@router.get("/admin/categories/{category_id}", response_model=CategoryAdmin)
async def get_category(
    category_id: UUID, service: CategoryServiceDep, current_session: CurrentSessionDep
):
    try:
        return await service.get(category_id)
    except CategoryNotFoundError:
        raise HTTPException(status_code=404, detail="Category not found") from None


@router.patch("/admin/categories/{category_id}", response_model=CategoryAdmin)
async def update_category(
    category_id: UUID,
    body: CategoryUpdate,
    service: CategoryServiceDep,
    current_session: CurrentSessionDep,
):
    try:
        return await service.update(category_id, body)
    except CategoryNotFoundError:
        raise HTTPException(status_code=404, detail="Category not found") from None
    except InvalidCategoryMediaError:
        raise HTTPException(status_code=422, detail="Invalid category media") from None
    except CategoryConflictError:
        raise HTTPException(status_code=409, detail="Category conflict") from None


@router.delete("/admin/categories/{category_id}", status_code=204)
async def delete_category(
    category_id: UUID, service: CategoryServiceDep, current_session: CurrentSessionDep
):
    try:
        await service.delete(category_id)
    except CategoryNotFoundError:
        raise HTTPException(status_code=404, detail="Category not found") from None
    return Response(status_code=204)
