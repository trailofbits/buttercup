"""Database models and operations for buttercup-ui."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    BLOB,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, relationship, sessionmaker

logger = logging.getLogger(__name__)

Base = declarative_base()


class Task(Base):
    """Task model for storing task information."""
    
    __tablename__ = "tasks"
    
    task_id = Column(String, primary_key=True)
    name = Column(String)
    project_name = Column(String)
    status = Column(String)
    duration = Column(Integer)
    deadline = Column(String)
    challenge_repo_url = Column(String)
    challenge_repo_head_ref = Column(String)
    challenge_repo_base_ref = Column(String)
    fuzz_tooling_url = Column(String)
    fuzz_tooling_ref = Column(String)
    created_at = Column(String)
    
    # Relationships
    povs = relationship("POV", back_populates="task", cascade="all, delete-orphan")
    patches = relationship("Patch", back_populates="task", cascade="all, delete-orphan")
    bundles = relationship("Bundle", back_populates="task", cascade="all, delete-orphan")


class POV(Base):
    """POV (Proof of Vulnerability) model."""
    
    __tablename__ = "povs"
    
    pov_id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.task_id"), nullable=False)
    timestamp = Column(String)
    architecture = Column(String)
    engine = Column(String)
    fuzzer_name = Column(String)
    sanitizer = Column(String)
    testcase = Column(BLOB)
    
    # Additional fields from POVSubmission
    additional_data = Column(Text)  # JSON string for additional fields
    
    # Relationship
    task = relationship("Task", back_populates="povs")


class Patch(Base):
    """Patch model for storing code patches."""
    
    __tablename__ = "patches"
    
    patch_id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.task_id"), nullable=False)
    timestamp = Column(String)
    patch = Column(Text)
    
    # Additional fields from PatchSubmission
    additional_data = Column(Text)  # JSON string for additional fields
    
    # Relationship
    task = relationship("Task", back_populates="patches")


class Bundle(Base):
    """Bundle model for storing submission bundles."""
    
    __tablename__ = "bundles"
    
    bundle_id = Column(String, primary_key=True)
    task_id = Column(String, ForeignKey("tasks.task_id"), nullable=False)
    timestamp = Column(String)
    description = Column(Text)
    broadcast_sarif_id = Column(String)
    freeform_id = Column(String)
    patch_id = Column(String)
    pov_id = Column(String)
    submitted_sarif_id = Column(String)
    
    # Additional fields from BundleSubmission
    additional_data = Column(Text)  # JSON string for additional fields
    
    # Relationship
    task = relationship("Task", back_populates="bundles")


class DatabaseManager:
    """Database manager for buttercup-ui operations."""
    
    def __init__(self, database_url: str):
        self.database_url = database_url
        self.engine = create_engine(database_url)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self._create_tables()
    
    def _create_tables(self):
        """Create all database tables."""
        Base.metadata.create_all(bind=self.engine)
        logger.info("Database tables created/verified")
    
    def get_session(self) -> Session:
        """Get a database session."""
        return self.SessionLocal()
    
    # Task operations
    def create_task(self, task_data: Dict[str, Any]) -> Task:
        """Create a new task."""
        with self.get_session() as session:
            task = Task(**task_data)
            session.add(task)
            session.commit()
            session.refresh(task)
            logger.info(f"Created task: {task.task_id}")
            return task
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        with self.get_session() as session:
            return session.query(Task).filter(Task.task_id == task_id).first()
    
    def get_all_tasks(self) -> List[Task]:
        """Get all tasks."""
        with self.get_session() as session:
            return session.query(Task).all()
    
    def update_task(self, task_id: str, task_data: Dict[str, Any]) -> Optional[Task]:
        """Update a task."""
        with self.get_session() as session:
            task = session.query(Task).filter(Task.task_id == task_id).first()
            if task:
                for key, value in task_data.items():
                    setattr(task, key, value)
                session.commit()
                session.refresh(task)
                logger.info(f"Updated task: {task_id}")
                return task
            return None
    
    def get_or_create_task(self, task_id: str) -> Task:
        """Get or create a task."""
        task = self.get_task(task_id)
        if not task:
            from datetime import datetime, timedelta
            now = datetime.now()
            deadline = now + timedelta(minutes=30)  # Default 30 minute duration
            
            task_data = {
                "task_id": task_id,
                "name": None,
                "project_name": "unknown",
                "status": "active",
                "duration": 1800,
                "deadline": deadline.isoformat(),
                "challenge_repo_url": None,
                "challenge_repo_head_ref": None,
                "challenge_repo_base_ref": None,
                "fuzz_tooling_url": None,
                "fuzz_tooling_ref": None,
                "created_at": now.isoformat(),
            }
            task = self.create_task(task_data)
        return task
    
    # POV operations
    def create_pov(self, pov_data: Dict[str, Any]) -> POV:
        """Create a new POV."""
        with self.get_session() as session:
            # Extract additional data
            additional_data = {}
            basic_fields = {"pov_id", "task_id", "timestamp", "architecture", "engine", "fuzzer_name", "sanitizer", "testcase"}
            for key, value in pov_data.items():
                if key not in basic_fields:
                    additional_data[key] = value
            
            pov_data_filtered = {k: v for k, v in pov_data.items() if k in basic_fields}
            pov_data_filtered["additional_data"] = json.dumps(additional_data) if additional_data else None
            
            pov = POV(**pov_data_filtered)
            session.add(pov)
            session.commit()
            session.refresh(pov)
            logger.info(f"Created POV: {pov.pov_id}")
            return pov
    
    def get_povs_for_task(self, task_id: str) -> List[POV]:
        """Get all POVs for a task."""
        with self.get_session() as session:
            return session.query(POV).filter(POV.task_id == task_id).all()
    
    def get_all_povs(self) -> List[POV]:
        """Get all POVs."""
        with self.get_session() as session:
            return session.query(POV).all()
    
    # Patch operations
    def create_patch(self, patch_data: Dict[str, Any]) -> Patch:
        """Create a new patch."""
        with self.get_session() as session:
            # Extract additional data
            additional_data = {}
            basic_fields = {"patch_id", "task_id", "timestamp", "patch"}
            for key, value in patch_data.items():
                if key not in basic_fields:
                    additional_data[key] = value
            
            patch_data_filtered = {k: v for k, v in patch_data.items() if k in basic_fields}
            patch_data_filtered["additional_data"] = json.dumps(additional_data) if additional_data else None
            
            patch = Patch(**patch_data_filtered)
            session.add(patch)
            session.commit()
            session.refresh(patch)
            logger.info(f"Created patch: {patch.patch_id}")
            return patch
    
    def get_patches_for_task(self, task_id: str) -> List[Patch]:
        """Get all patches for a task."""
        with self.get_session() as session:
            return session.query(Patch).filter(Patch.task_id == task_id).all()
    
    def get_all_patches(self) -> List[Patch]:
        """Get all patches."""
        with self.get_session() as session:
            return session.query(Patch).all()
    
    # Bundle operations  
    def create_bundle(self, bundle_data: Dict[str, Any]) -> Bundle:
        """Create a new bundle."""
        with self.get_session() as session:
            # Extract additional data
            additional_data = {}
            basic_fields = {"bundle_id", "task_id", "timestamp", "description", "broadcast_sarif_id", 
                          "freeform_id", "patch_id", "pov_id", "submitted_sarif_id"}
            for key, value in bundle_data.items():
                if key not in basic_fields:
                    additional_data[key] = value
            
            bundle_data_filtered = {k: v for k, v in bundle_data.items() if k in basic_fields}
            bundle_data_filtered["additional_data"] = json.dumps(additional_data) if additional_data else None
            
            bundle = Bundle(**bundle_data_filtered)
            session.add(bundle)
            session.commit()
            session.refresh(bundle)
            logger.info(f"Created bundle: {bundle.bundle_id}")
            return bundle
    
    def get_bundles_for_task(self, task_id: str) -> List[Bundle]:
        """Get all bundles for a task."""
        with self.get_session() as session:
            return session.query(Bundle).filter(Bundle.task_id == task_id).all()
    
    def get_all_bundles(self) -> List[Bundle]:
        """Get all bundles."""
        with self.get_session() as session:
            return session.query(Bundle).all()
    
    # Utility methods for converting models to dicts (for compatibility with existing code)
    def task_to_dict(self, task: Task) -> Dict[str, Any]:
        """Convert a Task model to dictionary format compatible with existing code."""
        povs = []
        for pov in task.povs:
            pov_dict = {
                "pov_id": pov.pov_id,
                "timestamp": pov.timestamp,
                "architecture": pov.architecture,
                "engine": pov.engine,
                "fuzzer_name": pov.fuzzer_name,
                "sanitizer": pov.sanitizer,
                "testcase": pov.testcase,
            }
            if pov.additional_data:
                additional = json.loads(pov.additional_data)
                pov_dict.update(additional)
            povs.append(pov_dict)
        
        patches = []
        for patch in task.patches:
            patch_dict = {
                "patch_id": patch.patch_id,
                "timestamp": patch.timestamp,
                "patch": patch.patch,
            }
            if patch.additional_data:
                additional = json.loads(patch.additional_data)
                patch_dict.update(additional)
            patches.append(patch_dict)
        
        bundles = []
        for bundle in task.bundles:
            bundle_dict = {
                "bundle_id": bundle.bundle_id,
                "timestamp": bundle.timestamp,
                "description": bundle.description,
                "broadcast_sarif_id": bundle.broadcast_sarif_id,
                "freeform_id": bundle.freeform_id,
                "patch_id": bundle.patch_id,
                "pov_id": bundle.pov_id,
                "submitted_sarif_id": bundle.submitted_sarif_id,
            }
            if bundle.additional_data:
                additional = json.loads(bundle.additional_data)
                bundle_dict.update(additional)
            bundles.append(bundle_dict)
        
        return {
            "task_id": task.task_id,
            "name": task.name,
            "project_name": task.project_name,
            "status": task.status,
            "duration": task.duration,
            "deadline": task.deadline,
            "challenge_repo_url": task.challenge_repo_url,
            "challenge_repo_head_ref": task.challenge_repo_head_ref,
            "challenge_repo_base_ref": task.challenge_repo_base_ref,
            "fuzz_tooling_url": task.fuzz_tooling_url,
            "fuzz_tooling_ref": task.fuzz_tooling_ref,
            "created_at": task.created_at,
            "povs": povs,
            "patches": patches,
            "bundles": bundles,
        }