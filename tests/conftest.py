"""
Конфигурация pytest для тестов.

Добавляет корень проекта в sys.path для импорта модулей core и ui.
"""

import sys
import os

# Добавляем корень проекта в sys.path
# Это необходимо для NixOS, где Python не добавляет текущую директорию в sys.path
project_root = os.path.dirname(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Тесты проверяют русские подписи — язык интерфейса на машине не должен влиять
os.environ["NHJS_LANG"] = "ru"
