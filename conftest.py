import sys
import os

# Добавляем корень проекта в sys.path, чтобы pytest находил модули 'core' и 'ui'
# Это делается на уровне модуля, чтобы выполнялось до импорта тестов
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def pytest_configure(config):
    """
    Выполняется до сбора тестов. Гарантирует, что sys.path настроен.
    
    Это критически важно для NixOS, где Python не добавляет текущую 
    директорию в sys.path автоматически.
    """
    project_root = os.path.dirname(os.path.abspath(__file__))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    # Также добавляем в PYTHONPATH для подпроцессов
    os.environ['PYTHONPATH'] = project_root + ':' + os.environ.get('PYTHONPATH', '')
