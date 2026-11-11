from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from app.models.contact import Contact
from app.schemas.contact import ContactUpdate
from app.services.contact import ContactService, InvalidContactError


async def test_contact_update_preserves_other_fields_and_coordinates():
    db = AsyncMock()
    service = ContactService(db)
    contact = Contact(
        id=1, phone="123", address="Address", latitude=Decimal("1"), longitude=Decimal("2")
    )
    service.contacts.get = AsyncMock(return_value=contact)

    result = await service.update(ContactUpdate(phone="456", latitude=Decimal("3")))

    assert result.phone == "456"
    assert result.address == "Address"
    assert result.latitude == Decimal("3")
    assert result.longitude == Decimal("2")
    db.commit.assert_awaited_once()


@pytest.mark.parametrize("body", [{"phone": None}, {"address": None}, {"longitude": None}])
async def test_contact_update_rejects_invalid_result(body):
    db = AsyncMock()
    service = ContactService(db)
    contact = Contact(
        id=1, phone="123", address="Address", latitude=Decimal("1"), longitude=Decimal("2")
    )
    service.contacts.get = AsyncMock(return_value=contact)

    with pytest.raises(InvalidContactError):
        await service.update(ContactUpdate(**body))

    db.commit.assert_not_awaited()
    assert contact.phone == "123"
    assert contact.longitude == Decimal("2")
