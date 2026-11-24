"""SSL-контекст для HTTPS, SMTP и IMAP.

На Android у Python из python-for-android нет своих корневых сертификатов:
``ssl.create_default_context()`` ничему не доверяет, и любое HTTPS-соединение
(проверка обновлений на GitHub, Gmail) падает на проверке сертификата.
Берём системные сертификаты Android (PEM-файлы ``<hash>.0``). Как ``capath``
их подключить нельзя: имена — старый хеш OpenSSL (subject_hash_old), а OpenSSL 3
ищет по новому. Поэтому каждый файл загружается отдельно.
"""

import os
import ssl

from core.utils.android_storage import is_android

# Android 14+ обновляет корневые сертификаты модулем conscrypt, раньше — /system
ANDROID_CA_DIRS = ("/apex/com.android.conscrypt/cacerts", "/system/etc/security/cacerts")


def create_default_context() -> ssl.SSLContext:
    """Как ``ssl.create_default_context()``, но на Android — с системными сертификатами."""
    context = ssl.create_default_context()
    if is_android():
        for path in ANDROID_CA_DIRS:
            if not os.path.isdir(path):
                continue
            for name in sorted(os.listdir(path)):
                try:
                    context.load_verify_locations(cafile=os.path.join(path, name))
                except (OSError, ssl.SSLError):
                    continue  # нечитаемый или чужой формат — пропускаем
            break  # первая найденная папка — актуальная (conscrypt новее /system)
    return context
