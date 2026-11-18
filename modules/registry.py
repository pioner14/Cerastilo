from typing import Dict, List, TYPE_CHECKING
from .base_module import BaseModule

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from core.facade import ApplicationFacade

class ModuleRegistry:
    def __init__(self):
        self._modules: Dict[str, BaseModule] = {}
    
    def register(self, module: BaseModule):
        """Регистрирует новый модуль."""
        self._modules[module.id] = module
    
    def get_enabled(self, facade: 'ApplicationFacade') -> List[BaseModule]:
        """
        Возвращает список включенных модулей.
        Проверяет настройку 'module_{id}' (по умолчанию 'true').
        """
        enabled = []
        for m in self._modules.values():
            # По умолчанию модуль включен, если нет явного 'false'
            if facade.get_setting(f'module_{m.id}', 'true') == 'true':
                enabled.append(m)
        return enabled
    
    def get_all(self) -> List[BaseModule]:
        """Возвращает все зарегистрированные модули."""
        return list(self._modules.values())
    
    def migrate_all(self, session: 'Session'):
        """Запускает миграции всех модулей."""
        for m in self._modules.values():
            try:
                m.migrate(session)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Migration failed for module {m.id}: {e}")
