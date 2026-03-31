import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from collector.config import settings

logger = logging.getLogger(__name__)

_engine = create_engine(settings.db_url, pool_pre_ping=True)
_SessionFactory = sessionmaker(bind=_engine)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """DB 세션을 컨텍스트 매니저로 제공한다. 예외 발생 시 자동 롤백."""
    session: Session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("DB 세션 오류로 롤백함")
        raise
    finally:
        session.close()
