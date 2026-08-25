from app.schemas.base import ContractModel
from app.schemas.common import DomainRef, JobRef


class DomainJobAccepted(ContractModel):
    target: DomainRef
    job: JobRef
