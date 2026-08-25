from typing import Generic, TypeVar

from app.schemas.base import ContractModel

ItemT = TypeVar("ItemT")


class Page(ContractModel, Generic[ItemT]):
    items: list[ItemT]
    next_cursor: str | None
