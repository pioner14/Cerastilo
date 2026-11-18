import logging
from PySide6.QtCore import QThread, Signal
from typing import Callable

logger = logging.getLogger(__name__)


class ProgressCallback:
    """
    Callback-объект для эмиссии прогресса из фоновой задачи.

    Передаётся в задачу как аргумент, позволяет эмиссировать прогресс
    через сигнал TaskWorker.progress.
    """

    def __init__(self, emit_signal):
        self._emit = emit_signal

    def __call__(self, value: int):
        """Эмиссия значения прогресса (0-100 или абсолютное значение)."""
        self._emit(value)


class TaskWorker(QThread):
    """
    Generic worker to run expensive tasks in a background thread.
    Uses Signal to notify UI about results or progress.
    """

    finished = Signal(dict)  # Returns result dict {'success': bool, 'data': Any, 'error': str}
    progress = Signal(int)  # Optional progress percentage

    def __init__(
        self, task_func: Callable, *args, error_service=None, pass_progress=False, **kwargs
    ):
        """
        Инициализация worker.

        Args:
            task_func: Функция для выполнения в фоне
            *args: Позиционные аргументы для task_func
            error_service: Сервис обработки ошибок
            pass_progress: Если True, передаёт ProgressCallback как первый аргумент
            **kwargs: Именованные аргументы для task_func
        """
        super().__init__()
        self.task_func = task_func
        self.args = args
        self.kwargs = kwargs
        self.error_service = error_service
        self.pass_progress = pass_progress

    def run(self):
        try:
            logger.info(f"Background task starting: {self.task_func.__name__}")

            # Создаём progress callback если нужно
            if self.pass_progress:
                progress_cb = ProgressCallback(self.progress.emit)
                result = self.task_func(progress_cb, *self.args, **self.kwargs)
            else:
                result = self.task_func(*self.args, **self.kwargs)

            # ... generic result wrapping ...
            if result is None:
                final_res = {"success": True}
            elif isinstance(result, bool):
                final_res = {"success": result}
            elif isinstance(result, dict):
                final_res = result
            else:
                final_res = {"success": True, "data": result}

            self.finished.emit(final_res)
            logger.info(f"Background task finished: {self.task_func.__name__}")
        except Exception as e:
            if self.error_service:
                res = self.error_service.handle_exception(
                    e, f"BackgroundTask:{self.task_func.__name__}"
                )
                self.finished.emit(res)
            else:
                logger.error(f"Error in background task: {str(e)}", exc_info=True)
                self.finished.emit({"success": False, "error": str(e)})


class WorkerFactory:
    """Helper to create and start workers easily."""

    @staticmethod
    def run_task(facade, task_func: Callable, on_finished: Callable, *args, **kwargs) -> TaskWorker:
        worker = TaskWorker(task_func, *args, **kwargs)
        worker.finished.connect(on_finished)
        # We need to keep a reference to the worker or it will be GC'd
        # Storing it in the facade might be an option, but usually it's better in the UI component
        worker.start()
        return worker
