from pydantic import BaseModel


class Person(BaseModel):
    person_id: int | None = None
    first_name: str
    middle_name: str = ""
    last_name: str
    email: str | None = None
    phone: str | None = None
    fax: str | None = None
    title: str | None = None


class Organization(BaseModel):
    org_id: int | None = None
    org_name: str
    org_vivo_uri: str = ""


class Job(BaseModel):
    job_id: int | None = None
    job_title: str
    job_type: str = ""
    start_date: int | None = None


class IngestedRecord(BaseModel):
    person: Person
    organization: Organization
    job: Job
