"""Database models and operations for buttercup-ui."""

import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator
import uuid

from sqlalchemy import (
    BLOB,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    func,
    DateTime,
)
from sqlalchemy.orm import Session, relationship, sessionmaker, DeclarativeBase, Mapped, mapped_column

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class Task(Base):
    """Task model for storing task information."""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String)
    project_name: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    duration: Mapped[int] = mapped_column(Integer)
    deadline: Mapped[datetime] = mapped_column(DateTime)
    challenge_repo_url: Mapped[str] = mapped_column(String)
    challenge_repo_head_ref: Mapped[str] = mapped_column(String)
    challenge_repo_base_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    fuzz_tooling_url: Mapped[str] = mapped_column(String)
    fuzz_tooling_ref: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Error tracking fields
    crs_submission_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    crs_error_details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string for detailed error info
    crs_submission_status: Mapped[str | None] = mapped_column(String, nullable=True)  # 'pending', 'success', 'failed'
    crs_submission_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    povs: Mapped[list["POV"]] = relationship("POV", back_populates="task", cascade="all, delete-orphan")
    patches: Mapped[list["Patch"]] = relationship("Patch", back_populates="task", cascade="all, delete-orphan")
    bundles: Mapped[list["Bundle"]] = relationship("Bundle", back_populates="task", cascade="all, delete-orphan")


class POV(Base):
    """POV (Proof of Vulnerability) model."""

    __tablename__ = "povs"

    pov_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.task_id"), nullable=False)
    architecture: Mapped[str] = mapped_column(String)
    engine: Mapped[str] = mapped_column(String)
    fuzzer_name: Mapped[str] = mapped_column(String)
    sanitizer: Mapped[str] = mapped_column(String)
    testcase: Mapped[bytes] = mapped_column(BLOB)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Relationship
    task: Mapped[Task] = relationship("Task", back_populates="povs")


class Patch(Base):
    """Patch model for storing code patches."""

    __tablename__ = "patches"

    patch_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.task_id"), nullable=False)
    patch: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    task: Mapped[Task] = relationship("Task", back_populates="patches")


class Bundle(Base):
    """Bundle model for storing submission bundles."""

    __tablename__ = "bundles"

    bundle_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String, ForeignKey("tasks.task_id"), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    broadcast_sarif_id: Mapped[str | None] = mapped_column(String, nullable=True)
    freeform_id: Mapped[str | None] = mapped_column(String, nullable=True)
    patch_id: Mapped[str | None] = mapped_column(String, nullable=True)
    pov_id: Mapped[str | None] = mapped_column(String, nullable=True)
    submitted_sarif_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    task: Mapped[Task] = relationship("Task", back_populates="bundles")


class DatabaseManager:
    """Database manager for buttercup-ui operations."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._create_tables()

    def _create_tables(self) -> None:
        """Create all database tables."""
        Base.metadata.create_all(bind=self.engine)
        logger.info("Database tables created/verified")

    def get_session(self) -> Session:
        """Get a database session."""
        return self.SessionLocal()

    # Context manager methods for session-scoped queries
    @contextmanager
    def get_all_tasks(self) -> Iterator[list[Task]]:
        """Context manager: yields all tasks with session open."""
        with self.get_session() as session:
            tasks = session.query(Task).all()
            yield tasks
            session.commit()

    @contextmanager
    def get_task(self, task_id: str) -> Iterator[Task | None]:
        """Context manager: yields a task by ID with session open."""
        with self.get_session() as session:
            task = session.query(Task).filter(Task.task_id == task_id).first()
            yield task
            session.commit()

    def get_tasks_by_crs_status(self, crs_status: str) -> list[Task]:
        """Get all tasks with a specific CRS submission status."""
        with self.get_session() as session:
            tasks = session.query(Task).filter(Task.crs_submission_status == crs_status).all()
            session.commit()
            return tasks

    def get_tasks_by_status(self, status: str) -> list[Task]:
        """Get all tasks with a specific overall status (active, expired, failed)."""
        with self.get_session() as session:
            if status == "failed":
                # For failed status, check CRS submission status
                tasks = session.query(Task).filter(Task.crs_submission_status == "failed").all()
            else:
                # For other statuses, we need to calculate based on deadline
                from datetime import datetime

                now = datetime.now()

                if status == "active":
                    tasks = session.query(Task).filter(Task.deadline > now).all()
                elif status == "expired":
                    tasks = session.query(Task).filter(Task.deadline <= now).all()
                else:
                    tasks = []

            session.commit()
            return tasks

    @contextmanager
    def get_povs_for_task(self, task_id: str) -> Iterator[list[POV]]:
        """Context manager: yields all POVs for a task with session open."""
        with self.get_session() as session:
            povs = session.query(POV).filter(POV.task_id == task_id).all()
            yield povs
            session.commit()

    @contextmanager
    def get_pov(self, pov_id: str, task_id: str | None = None) -> Iterator[POV | None]:
        """Context manager: yields a POV by ID with session open."""
        with self.get_session() as session:
            if task_id:
                pov = session.query(POV).filter(POV.task_id == task_id, POV.pov_id == pov_id).first()
            else:
                pov = session.query(POV).filter(POV.pov_id == pov_id).first()
            yield pov
            session.commit()

    @contextmanager
    def get_all_povs(self) -> Iterator[list[POV]]:
        """Context manager: yields all POVs with session open."""
        with self.get_session() as session:
            povs = session.query(POV).all()
            yield povs
            session.commit()

    @contextmanager
    def get_patches_for_task(self, task_id: str) -> Iterator[list[Patch]]:
        """Context manager: yields all patches for a task with session open."""
        with self.get_session() as session:
            patches = session.query(Patch).filter(Patch.task_id == task_id).all()
            yield patches
            session.commit()

    @contextmanager
    def get_patch(self, patch_id: str, task_id: str | None = None) -> Iterator[Patch | None]:
        """Context manager: yields a patch by ID with session open."""
        with self.get_session() as session:
            if task_id:
                patch = session.query(Patch).filter(Patch.task_id == task_id, Patch.patch_id == patch_id).first()
            else:
                patch = session.query(Patch).filter(Patch.patch_id == patch_id).first()
            yield patch
            session.commit()

    @contextmanager
    def get_all_patches(self) -> Iterator[list[Patch]]:
        """Context manager: yields all patches with session open."""
        with self.get_session() as session:
            patches = session.query(Patch).all()
            yield patches
            session.commit()

    @contextmanager
    def get_bundles_for_task(self, task_id: str) -> Iterator[list[Bundle]]:
        """Context manager: yields all bundles for a task with session open."""
        with self.get_session() as session:
            bundles = session.query(Bundle).filter(Bundle.task_id == task_id).all()
            yield bundles
            session.commit()

    @contextmanager
    def get_bundle(self, bundle_id: str, task_id: str | None = None) -> Iterator[Bundle | None]:
        """Context manager: yields a bundle by ID with session open."""
        with self.get_session() as session:
            if task_id:
                bundle = session.query(Bundle).filter(Bundle.task_id == task_id, Bundle.bundle_id == bundle_id).first()
            else:
                bundle = session.query(Bundle).filter(Bundle.bundle_id == bundle_id).first()
            yield bundle
            session.commit()

    @contextmanager
    def get_all_bundles(self) -> Iterator[list[Bundle]]:
        """Context manager: yields all bundles with session open."""
        with self.get_session() as session:
            bundles = session.query(Bundle).all()
            yield bundles
            session.commit()

    # Task operations
    def create_task(
        self,
        *,
        task_id: str,
        name: str,
        project_name: str,
        status: str,
        duration: int,
        deadline: datetime,
        challenge_repo_url: str,
        challenge_repo_head_ref: str,
        challenge_repo_base_ref: str | None,
        fuzz_tooling_url: str,
        fuzz_tooling_ref: str,
    ) -> Task:
        """Create a new task."""
        with self.get_session() as session:
            task = Task(
                task_id=task_id,
                name=name,
                project_name=project_name,
                status=status,
                duration=duration,
                deadline=deadline,
                challenge_repo_url=challenge_repo_url,
                challenge_repo_head_ref=challenge_repo_head_ref,
                challenge_repo_base_ref=challenge_repo_base_ref,
                fuzz_tooling_url=fuzz_tooling_url,
                fuzz_tooling_ref=fuzz_tooling_ref,
            )
            session.add(task)
            session.commit()
            logger.info(f"Created task: {task.task_id}")
            return task

    def update_task_crs_status(
        self,
        *,
        task_id: str,
        crs_submission_status: str,
        crs_submission_error: str | None = None,
        crs_error_details: dict | None = None,
    ) -> None:
        """Update the CRS submission status and error information for a task."""
        import json

        with self.get_session() as session:
            task = session.query(Task).filter(Task.task_id == task_id).first()
            if task:
                task.crs_submission_status = crs_submission_status
                task.crs_submission_error = crs_submission_error
                task.crs_submission_timestamp = datetime.now()

                if crs_error_details:
                    task.crs_error_details = json.dumps(crs_error_details, indent=2)

                session.commit()
                logger.info(f"Updated CRS status for task {task_id}: {crs_submission_status}")
            else:
                logger.warning(f"Task {task_id} not found for CRS status update")

    # POV operations
    def create_pov(
        self, *, task_id: str, architecture: str, engine: str, fuzzer_name: str, sanitizer: str, testcase: bytes
    ) -> POV:
        """Create a new POV."""
        with self.get_session() as session:
            pov = POV(
                task_id=task_id,
                architecture=architecture,
                engine=engine,
                fuzzer_name=fuzzer_name,
                sanitizer=sanitizer,
                testcase=testcase,
            )
            session.add(pov)
            session.commit()
            logger.info(f"Created POV: {pov.pov_id}")
            return pov

    # Patch operations
    def create_patch(self, *, task_id: str, patch: str) -> Patch:
        """Create a new patch."""
        with self.get_session() as session:
            patch_obj = Patch(task_id=task_id, patch=patch)
            session.add(patch_obj)
            session.commit()
            logger.info(f"Created patch: {patch_obj.patch_id}")
            return patch_obj

    # Bundle operations
    def create_bundle(
        self,
        *,
        task_id: str,
        broadcast_sarif_id: str | None = None,
        description: str | None = None,
        freeform_id: str | None = None,
        patch_id: str | None = None,
        pov_id: str | None = None,
        submitted_sarif_id: str | None = None,
    ) -> Bundle:
        """Create a new bundle."""
        with self.get_session() as session:
            bundle = Bundle(
                task_id=task_id,
                broadcast_sarif_id=broadcast_sarif_id,
                description=description,
                freeform_id=freeform_id,
                patch_id=patch_id,
                pov_id=pov_id,
                submitted_sarif_id=submitted_sarif_id,
            )
            session.add(bundle)
            session.commit()
            logger.info(f"Created bundle: {bundle.bundle_id}")
            return bundle

    def delete_bundle(self, bundle: Bundle) -> None:
        """Delete a bundle."""
        with self.get_session() as session:
            session.delete(bundle)
            session.commit()
            logger.info(f"Deleted bundle: {bundle.bundle_id}")
