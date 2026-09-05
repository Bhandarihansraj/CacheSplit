import json
from typing import Any, Dict, List, Optional
import uuid
from datetime import datetime

from sqlalchemy import Column, String, Text, DateTime, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from adapters.interface import CommitStore

Base = declarative_base()

class CommitRecord(Base):
    __tablename__ = 'commits'
    
    commit_id = Column(String, primary_key=True)
    key = Column(String, index=True, nullable=False)
    value_json = Column(Text, nullable=False)
    metadata_json = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)


class SQLiteMockCommitStore(CommitStore):
    """
    SQLAlchemy-based implementation of CommitStore using SQLite.
    """
    def __init__(self, db_url: str = "sqlite:///:memory:"):
        self.engine = create_engine(db_url)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def write(self, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None) -> str:
        commit_id = str(uuid.uuid4())
        record = CommitRecord(
            commit_id=commit_id,
            key=key,
            value_json=json.dumps(value),
            metadata_json=json.dumps(metadata) if metadata else None
        )
        with self.Session() as session:
            session.add(record)
            session.commit()
        return commit_id

    def read(self, key: str) -> Optional[Any]:
        with self.Session() as session:
            record = session.query(CommitRecord).filter_by(key=key).order_by(CommitRecord.timestamp.desc()).first()
            if record:
                return json.loads(record.value_json)
        return None

    def list_history(self, key: str) -> List[Dict[str, Any]]:
        with self.Session() as session:
            records = session.query(CommitRecord).filter_by(key=key).order_by(CommitRecord.timestamp.asc()).all()
            history = []
            for r in records:
                history.append({
                    "commit_id": r.commit_id,
                    "key": r.key,
                    "value": json.loads(r.value_json),
                    "metadata": json.loads(r.metadata_json) if r.metadata_json else None,
                    "timestamp": r.timestamp.isoformat()
                })
            return history
