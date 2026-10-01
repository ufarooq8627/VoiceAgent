import random
from faker import Faker
from sqlalchemy.orm import Session

from app.models import Candidate, Job
from app.schemas.candidate import CandidateCreate

fake = Faker("en_IN")

SKILL_POOLS = {
    "backend": [
        "Python", "FastAPI", "Django", "PostgreSQL", "Redis",
        "Node.js", "Docker", "Celery", "SQLAlchemy", "RabbitMQ",
    ],
    "frontend": [
        "React", "TypeScript", "JavaScript", "Next.js", "Tailwind CSS",
        "Redux", "HTML5", "CSS3", "Vue.js", "Webpack",
    ],
    "fullstack": [
        "Python", "FastAPI", "React", "TypeScript", "PostgreSQL",
        "Docker", "Node.js", "Redis", "Next.js", "AWS",
    ],
    "devops": [
        "Docker", "Kubernetes", "AWS", "Terraform", "CI/CD",
        "Linux", "GitHub Actions", "Prometheus", "Ansible", "Nginx",
    ],
    "data": [
        "Python", "Pandas", "PyTorch", "SQL", "Scikit-learn",
        "Spark", "FastAPI", "Docker", "NumPy", "TensorFlow",
    ],
}

INDIAN_COMPANIES = [
    "TCS", "Infosys", "Wipro", "Swiggy", "Zomato", "Razorpay",
    "Flipkart", "CRED", "PhonePe", "Freshworks", "Zoho", "Paytm",
    "InMobi", "Ola", "Jio",
]


class CandidateService:
    @staticmethod
    def _get_skill_pool_for_title(title: str) -> list[str]:
        title_lower = title.lower()
        if "backend" in title_lower or "python" in title_lower:
            return SKILL_POOLS["backend"]
        if "frontend" in title_lower or "react" in title_lower or "ui" in title_lower:
            return SKILL_POOLS["frontend"]
        if "fullstack" in title_lower or "full stack" in title_lower:
            return SKILL_POOLS["fullstack"]
        if "devops" in title_lower or "cloud" in title_lower or "infra" in title_lower:
            return SKILL_POOLS["devops"]
        if "data" in title_lower or "ml" in title_lower or "ai" in title_lower:
            return SKILL_POOLS["data"]
        return SKILL_POOLS["backend"]

    @staticmethod
    def _calculate_salary(experience_years: int) -> str:
        if experience_years <= 3:
            lpa = random.randint(4, 9)
        elif experience_years <= 7:
            lpa = random.randint(10, 22)
        elif experience_years <= 11:
            lpa = random.randint(23, 32)
        else:
            lpa = random.randint(33, 42)
        return f"₹{lpa} LPA"

    @classmethod
    def generate_mock(cls, db: Session, job_id: str, count: int = 20) -> list[Candidate]:
        job = db.query(Job).filter(Job.id == job_id).first()
        title = job.title if job else ""
        pool = cls._get_skill_pool_for_title(title)

        candidates = []
        for _ in range(count):
            exp = random.randint(1, 15)
            k = min(len(pool), random.randint(4, 8))
            skills = random.sample(pool, k=k)
            name = fake.name()
            # Clean email from name
            clean_name = "".join(ch for ch in name.lower() if ch.isalnum())
            email = f"{clean_name}{random.randint(10, 999)}@example.com"
            phone = fake.phone_number()
            company = random.choice(INDIAN_COMPANIES)
            designation = (
                "Associate Engineer" if exp <= 3
                else "Software Engineer" if exp <= 6
                else "Senior Software Engineer" if exp <= 10
                else "Lead Engineer"
            )
            salary = cls._calculate_salary(exp)

            candidate = Candidate(
                job_id=job_id,
                name=name,
                email=email,
                phone=phone,
                skills=skills,
                experience_years=exp,
                current_company=company,
                designation=designation,
                expected_salary=salary,
                source="mock",
                status="NEW",
                timezone="Asia/Kolkata",
            )
            db.add(candidate)
            candidates.append(candidate)

        db.commit()
        for c in candidates:
            db.refresh(c)
        return candidates

    @classmethod
    def create_from_api(cls, db: Session, job_id: str, data: CandidateCreate) -> Candidate:
        candidate = Candidate(
            job_id=job_id,
            name=data.name,
            email=str(data.email),
            phone=data.phone,
            skills=data.skills,
            experience_years=data.experience_years,
            current_company=data.current_company,
            designation=data.designation,
            expected_salary=data.expected_salary,
            resume_path=data.resume_path,
            timezone=data.timezone,
            source="api",
            status="NEW",
        )
        db.add(candidate)
        db.commit()
        db.refresh(candidate)
        return candidate

    @staticmethod
    def get_by_job(
        db: Session,
        job_id: str,
        page: int = 1,
        per_page: int = 20,
        status_filter: str | None = None,
    ) -> list[Candidate]:
        query = db.query(Candidate).filter(Candidate.job_id == job_id)
        if status_filter:
            query = query.filter(Candidate.status == status_filter)
        offset = (page - 1) * per_page
        return query.order_by(Candidate.created_at.desc()).offset(offset).limit(per_page).all()

    @staticmethod
    def get_by_id(db: Session, candidate_id: str) -> Candidate | None:
        return db.query(Candidate).filter(Candidate.id == candidate_id).first()
