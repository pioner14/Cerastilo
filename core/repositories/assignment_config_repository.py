import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session

from core.models import AssignmentConfig
from core.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class AssignmentConfigRepository(BaseRepository[AssignmentConfig]):
    """
    Репозиторий для доступа к конфигурации заданий (AssignmentConfig).

    Reference: spec://repositories/assignment_config
    """

    def __init__(self, db_manager=None, session: Optional[Session] = None):
        super().__init__(db_manager=db_manager, model_class=AssignmentConfig, session=session)

    def get_config(self, section: Optional[str] = None, position: Optional[str] = None) -> Any:
        """
        Получает конфигурацию. Если section и position указаны,
        возвращает один элемент, иначе список всех конфигураций.
        """
        with self.get_session() as session:
            if section and position:
                return session.execute(
                    select(AssignmentConfig).where(
                        and_(
                            AssignmentConfig.section == section,
                            AssignmentConfig.position == position,
                        )
                    )
                ).scalar()

            configs = session.execute(select(AssignmentConfig)).scalars().all()
            return [
                {
                    "section": c.section,
                    "position": c.position,
                    "assignment_name": c.assignment_name,
                    "required_qualification": c.required_qualification,
                    "is_brothers_only": c.is_brothers_only,
                    "needs_assistant": c.needs_assistant,
                }
                for c in configs
            ]

    def save_configs(self, config_list: List[Dict[str, Any]]) -> bool:
        """
        Сохраняет (обновляет) список конфигураций.
        """
        with self.get_session() as session:
            try:
                for item in config_list:
                    stmt = (
                        update(AssignmentConfig)
                        .where(
                            and_(
                                AssignmentConfig.section == item["section"],
                                AssignmentConfig.position == item["position"],
                            )
                        )
                        .values(
                            assignment_name=item["assignment_name"],
                            required_qualification=item["required_qualification"],
                            is_brothers_only=bool(item["is_brothers_only"]),
                            needs_assistant=bool(item["needs_assistant"]),
                        )
                    )
                    session.execute(stmt)
                self._persist(session)
                return True
            except Exception:
                logger.exception("Failed to save assignment configuration")
                self._rollback(session)
                if self._external_session is not None:
                    raise
                return False
