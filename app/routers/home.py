from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.auth import AuthenticatedUser, get_authenticated_user
from app.core.dependencies import get_session
from app.repositories.home import HomeRepository
from app.schemas.home import HomeSummary
from app.services.home import HomeService, SqlHomeService

router = APIRouter(tags=["home"])


def get_home_service(session: Annotated[Session, Depends(get_session)]) -> HomeService:
    return SqlHomeService(HomeRepository(session))


@router.get("/home", operation_id="home.get", response_model=HomeSummary)
def get_home(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[HomeService, Depends(get_home_service)],
) -> HomeSummary:
    return service.summary(user.id)


@router.post("/home/attendance", operation_id="home.attend", response_model=HomeSummary)
def attend(
    user: Annotated[AuthenticatedUser, Depends(get_authenticated_user)],
    service: Annotated[HomeService, Depends(get_home_service)],
) -> HomeSummary:
    """출석을 기록하고 갱신된 상태를 돌려준다.

    하루에 한 번만 기록되므로 같은 날 여러 번 눌러도 결과가 같다. 멱등키를
    받지 않는 이유다.
    """
    return service.attend(user.id)
