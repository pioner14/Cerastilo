from datetime import date, timedelta
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from core.i18n import _


class ParticipantEditDialog(QDialog):
    def __init__(self, facade, parent=None, participant_id=None):
        super().__init__(parent)
        self.facade = facade
        self.participant_id = participant_id
        self.excluded_weeks_dates = []
        self.setWindowTitle(
            _("Добавить возвещателя") if not participant_id else _("Редактировать возвещателя")
        )
        self.setMinimumWidth(600)
        self.setMinimumHeight(550)

        self.layout = QVBoxLayout(self)

        # Создаем QTabWidget
        self.tabs = QTabWidget()
        self.layout.addWidget(self.tabs)

        # === Вкладка 1: Основная информация ===
        tab_main = QWidget()
        tab_main_layout = QVBoxLayout(tab_main)

        self.form_group = QGroupBox(_("Основная информация"))
        self.form_layout = QFormLayout()

        self.name_edit = QLineEdit()
        self.form_layout.addRow(_("ФИО:"), self.name_edit)

        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("example@gmail.com")
        self.email_edit.setToolTip(_("Email для отправки персональных уведомлений о заданиях"))
        self.form_layout.addRow("Email:", self.email_edit)

        self.phone_edit = QLineEdit()
        self.phone_edit.setPlaceholderText("+7 (999) 000-00-00")
        self.phone_edit.setToolTip(_("Номер телефона (для справки)"))
        self.form_layout.addRow(_("Телефон:"), self.phone_edit)

        self.gender_combo = QComboBox()
        self.gender_combo.addItem(_("Брат"), "male")
        self.gender_combo.addItem(_("Сестра"), "female")
        self.form_layout.addRow(_("Пол:"), self.gender_combo)

        self.role_combo = QComboBox()
        self.role_combo.addItem(_("Возвещатель"), "PUB")
        self.role_combo.addItem(_("Помощник"), "MS")
        self.role_combo.addItem(_("Старейшина"), "E")
        self.form_layout.addRow(_("Духовный статус:"), self.role_combo)

        # Выбор семьи (главы семьи)
        self.family_combo = QComboBox()
        self.family_combo.addItem(_("— Нет семьи / Глава —"), None)
        potential_heads = [
            p for p in self.facade.get_all_participants(active_only=False) if p["gender"] == "male"
        ]
        for h in potential_heads:
            if h["id"] != self.participant_id:
                self.family_combo.addItem(h["name"], h["id"])
        self.form_layout.addRow(_("Семья (Глава):"), self.family_combo)

        # Личный интервал назначений (personal_gap)
        self.personal_gap_combo = QComboBox()
        self.personal_gap_combo.setToolTip(
            _(
                "Персональный интервал назначений.\n"
                "Авто = использовать правило по типу служения.\n"
                "0 нед. = всегда доступен (как старейшина).\n"
                "N нед. = не чаще раза в N недель."
            )
        )
        # Значения: (отображаемый текст, значение personal_gap)
        self._gap_options = [
            (_("Авто (по типу служения)"), None),
            (_("Всегда доступен (0 нед.)"), 0),
            (_("1 неделя"), 1),
            (_("2 недели"), 2),
            (_("3 недели"), 3),
            (_("4 недели"), 4),
            (_("5 недель"), 5),
            (_("6 недель"), 6),
            (_("8 недель"), 8),
            (_("10 недель"), 10),
            (_("12 недель"), 12),
        ]
        for label, val in self._gap_options:
            self.personal_gap_combo.addItem(label, val)
        self.form_layout.addRow(_("Личный интервал:"), self.personal_gap_combo)

        # Несовершеннолетний
        self.is_minor_check = QCheckBox()
        self.is_minor_check.setToolTip(
            _(
                "Отметить, если участник несовершеннолетний.\n"
                "Несовершеннолетний может получать учебные задания только:\n"
                "  • с другим несовершеннолетним (как главный или помощник)\n"
                "  • с взрослым членом своей семьи (только как помощник)"
            )
        )
        self.form_layout.addRow(_("Несовершеннолетний:"), self.is_minor_check)

        self.form_group.setLayout(self.form_layout)
        tab_main_layout.addWidget(self.form_group)

        self.quals_warning = QLabel(
            _(
                "⚠️ Не отмечено ни одной квалификации — участник не попадёт в распределение. "
                '<a href="quals">Отметить квалификации</a>'
            )
        )
        self.quals_warning.setWordWrap(True)
        self.quals_warning.setTextFormat(Qt.TextFormat.RichText)
        self.quals_warning.linkActivated.connect(
            lambda _link: self.tabs.setCurrentIndex(self._quals_tab_index)
        )
        tab_main_layout.addWidget(self.quals_warning)

        # Временное исключение из графика
        self.vacation_group = QGroupBox(_("Временное исключение из графика"))
        self.vacation_group.setCheckable(True)
        self.vacation_group.setChecked(False)
        self.vacation_group.setToolTip(
            _(
                "Исключить участника из всех автоматических и вспомогательных графиков\n"
                "на указанный период дат (например, на время отпуска)."
            )
        )
        vacation_layout = QFormLayout()

        self.vacation_from_edit = QDateEdit()
        self.vacation_from_edit.setCalendarPopup(True)
        self.vacation_from_edit.setDate(QDate.currentDate())
        vacation_layout.addRow(_("С:"), self.vacation_from_edit)

        self.vacation_to_edit = QDateEdit()
        self.vacation_to_edit.setCalendarPopup(True)
        self.vacation_to_edit.setDate(QDate.currentDate())
        vacation_layout.addRow(_("По:"), self.vacation_to_edit)

        self.vacation_group.setLayout(vacation_layout)
        tab_main_layout.addWidget(self.vacation_group)
        tab_main_layout.addStretch()

        self.tabs.addTab(tab_main, _("Основное"))

        # === Вкладка 2: Сменный график и пропуски ===
        tab_exclusions = QWidget()
        tab_exclusions_layout = QHBoxLayout(tab_exclusions)

        # Левая колонка вкладки: список
        list_layout = QVBoxLayout()
        list_layout.addWidget(QLabel(_("Исключенные недели (понедельники):")))
        self.excluded_weeks_list = QListWidget()
        self.excluded_weeks_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        list_layout.addWidget(self.excluded_weeks_list)

        self.btn_remove_excluded = QPushButton(_("🗑️ Удалить выбранные"))
        self.btn_remove_excluded.clicked.connect(self.remove_selected_excluded_weeks)
        list_layout.addWidget(self.btn_remove_excluded)
        tab_exclusions_layout.addLayout(list_layout, stretch=2)

        # Правая колонка вкладки: добавление
        add_layout = QVBoxLayout()

        # Отпуск, болезнь: все недели с … по … (одна неделя — обе даты в ней)
        manual_box = QGroupBox(_("Недоступен (отпуск, болезнь)"))
        manual_layout = QHBoxLayout()
        self.manual_date_edit = QDateEdit()
        self.manual_date_edit.setCalendarPopup(True)
        self.manual_date_edit.setDate(QDate.currentDate())
        self.manual_end_edit = QDateEdit()
        self.manual_end_edit.setCalendarPopup(True)
        self.manual_end_edit.setDate(QDate.currentDate())
        # «по» идёт за «с»: выбрали начало — по умолчанию одна неделя
        self.manual_date_edit.dateChanged.connect(self.manual_end_edit.setDate)
        self.btn_add_manual = QPushButton(_("➕ Добавить"))
        self.btn_add_manual.clicked.connect(self.add_manual_excluded_week)
        manual_layout.addWidget(QLabel(_("с")))
        manual_layout.addWidget(self.manual_date_edit)
        manual_layout.addWidget(QLabel(_("по")))
        manual_layout.addWidget(self.manual_end_edit)
        manual_layout.addWidget(self.btn_add_manual)
        manual_box.setLayout(manual_layout)
        add_layout.addWidget(manual_box)

        pattern_box = QGroupBox(_("Добавить по шаблону (сменный график)"))
        pattern_layout = QFormLayout()

        self.pattern_start_edit = QDateEdit()
        self.pattern_start_edit.setCalendarPopup(True)
        self.pattern_start_edit.setDate(QDate.currentDate())
        pattern_layout.addRow(_("Начало:"), self.pattern_start_edit)

        self.pattern_interval_combo = QComboBox()
        self.pattern_interval_combo.addItems(
            [
                _("Каждую неделю"),
                _("Через неделю (раз в 2 нед.)"),
                _("Раз в 3 недели"),
                _("Раз в 4 недели"),
                _("Раз в 5 недель"),
                _("Раз в 6 недель"),
            ]
        )
        self.pattern_interval_combo.setCurrentIndex(1)  # по умолчанию "через неделю"
        pattern_layout.addRow(_("Периодичность:"), self.pattern_interval_combo)

        self.pattern_count_spin = QSpinBox()
        self.pattern_count_spin.setRange(1, 52)
        self.pattern_count_spin.setValue(10)
        pattern_layout.addRow(_("Количество недель:"), self.pattern_count_spin)

        self.btn_add_pattern = QPushButton(_("⚙️ Сгенерировать шаблон"))
        self.btn_add_pattern.clicked.connect(self.add_pattern_excluded_weeks)
        pattern_layout.addRow(self.btn_add_pattern)

        pattern_box.setLayout(pattern_layout)
        add_layout.addWidget(pattern_box)
        add_layout.addStretch()

        tab_exclusions_layout.addLayout(add_layout, stretch=3)
        self.tabs.addTab(tab_exclusions, _("Сменный график"))

        # === Вкладка 3: Квалификации ===
        tab_quals = QWidget()
        tab_quals_layout = QVBoxLayout(tab_quals)

        self.qual_group = QGroupBox(_("Квалификации (доступные задания)"))
        self.qual_layout = QGridLayout()

        self.quals_list = [
            # Общие роли
            (_("Председатель"), "chairman"),
            (_("Молитва"), "prayer"),
            # СОКРОВИЩА ИЗ СЛОВА БОГА
            (_("Сокровища (10 мин.)"), "treasures_talk"),
            (_("Духовные жемчужины (10 мин.)"), "gems"),
            (_("Чтение Библии (4 мин.)"), "bible_reading"),
            # ОТТАЧИВАЕМ НАВЫКИ СЛУЖЕНИЯ
            (_("Учебные задания"), "ministry_item"),
            (_("Речь"), "ministry_speech"),
            (_("Напарник"), "assistant"),
            # ХРИСТИАНСКАЯ ЖИЗНЬ
            (_("Часть ХЖС"), "living_part"),
            (_("Изуч. Библии — Ведущий"), "cbs_conductor"),
            (_("Изуч. Библии — Чтец"), "cbs_reader"),
        ]

        self.checkboxes = {}
        # Квалификации из БД без галочки в форме (например, от удалённых графиков
        # служения) сохраняются как были, чтобы сохранение их не стирало.
        self._hidden_quals = []
        for i, (label, key) in enumerate(self.quals_list):
            cb = QCheckBox(label)
            self.checkboxes[key] = cb
            self.qual_layout.addWidget(cb, i // 2, i % 2)

        self.qual_group.setLayout(self.qual_layout)
        tab_quals_layout.addWidget(self.qual_group)
        tab_quals_layout.addStretch()

        self.tabs.addTab(tab_quals, _("Квалификации"))
        self._quals_tab_index = self.tabs.count() - 1
        for cb in self.checkboxes.values():
            cb.toggled.connect(self._update_quals_warning)

        # Кнопки
        buttons_layout = QHBoxLayout()
        self.btn_save = QPushButton(_("Сохранить"))
        self.btn_save.clicked.connect(self.save)
        self.btn_cancel = QPushButton(_("Отмена"))
        self.btn_cancel.clicked.connect(self.reject)

        buttons_layout.addStretch()
        buttons_layout.addWidget(self.btn_save)
        buttons_layout.addWidget(self.btn_cancel)
        self.layout.addLayout(buttons_layout)

        if self.participant_id:
            self.load_data()
        self._update_quals_warning()
        # Что было в форме при открытии — чтобы спросить «Сохранить?» при закрытии
        self._initial_state = self._form_state()

    def _form_state(self) -> tuple:
        """Всё, что вводят в карточке, — для сравнения «было/стало»."""
        vacation = (
            (
                self.vacation_from_edit.date().toString(Qt.DateFormat.ISODate),
                self.vacation_to_edit.date().toString(Qt.DateFormat.ISODate),
            )
            if self.vacation_group.isChecked()
            else None
        )
        return (
            self.name_edit.text().strip(),
            self.email_edit.text().strip(),
            self.phone_edit.text().strip(),
            self.gender_combo.currentData(),
            self.role_combo.currentData(),
            self.family_combo.currentData(),
            self.personal_gap_combo.currentData(),
            self.is_minor_check.isChecked(),
            vacation,
            frozenset(k for k, cb in self.checkboxes.items() if cb.isChecked()),
            tuple(sorted(self.excluded_weeks_dates)),
        )

    def _update_quals_warning(self, *_args) -> None:
        """Без квалификаций человек не попадает ни в «Авто», ни в кандидаты, а
        вкладку «Квалификации» новичок не замечает — подсказка на первой вкладке."""
        empty = (
            not any(cb.isChecked() for cb in self.checkboxes.values()) and not self._hidden_quals
        )
        self.quals_warning.setVisible(empty)
        self.tabs.setTabText(
            self._quals_tab_index, _("⚠️ Квалификации") if empty else _("Квалификации")
        )

    def has_changes(self) -> bool:
        return self._form_state() != getattr(self, "_initial_state", None)

    def reject(self):
        """«Отмена», Esc и крестик: введённое не пропадает молча."""
        if self.has_changes():
            reply = QMessageBox.question(
                self,
                _("Несохранённые изменения"),
                _("В карточке есть несохранённые изменения. Сохранить их?"),
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Save:
                self.save()
                return
        super().reject()

    def update_excluded_weeks_ui_list(self):
        self.excluded_weeks_list.clear()
        self.excluded_weeks_dates.sort()
        for d in self.excluded_weeks_dates:
            date_str = d.strftime("%d.%m.%Y")
            item = QListWidgetItem(date_str)
            item.setData(Qt.ItemDataRole.UserRole, d)
            self.excluded_weeks_list.addItem(item)

    def add_manual_excluded_week(self):
        """Добавить все недели (понедельники) с даты «с» по дату «по»."""
        q_start, q_end = self.manual_date_edit.date(), self.manual_end_edit.date()
        start = date(q_start.year(), q_start.month(), q_start.day())
        end = date(q_end.year(), q_end.month(), q_end.day())
        if end < start:
            start, end = end, start

        monday = start - timedelta(days=start.weekday())
        added = 0
        while monday <= end:
            if monday not in self.excluded_weeks_dates:
                self.excluded_weeks_dates.append(monday)
                added += 1
            monday += timedelta(weeks=1)

        if added:
            self.update_excluded_weeks_ui_list()
        else:
            QMessageBox.information(self, _("Информация"), _("Эти недели уже есть в списке."))

    def remove_selected_excluded_weeks(self):
        selected_items = self.excluded_weeks_list.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            d = item.data(Qt.ItemDataRole.UserRole)
            if d in self.excluded_weeks_dates:
                self.excluded_weeks_dates.remove(d)
        self.update_excluded_weeks_ui_list()

    def add_pattern_excluded_weeks(self):
        q_start = self.pattern_start_edit.date()
        start_date = date(q_start.year(), q_start.month(), q_start.day())

        # Align start date to Monday
        start_monday = start_date - timedelta(days=start_date.weekday())

        # Determine periodicity interval in weeks
        idx = self.pattern_interval_combo.currentIndex()
        interval = idx + 1

        count = self.pattern_count_spin.value()

        added_any = False
        for i in range(count):
            d = start_monday + timedelta(weeks=i * interval)
            if d not in self.excluded_weeks_dates:
                self.excluded_weeks_dates.append(d)
                added_any = True

        if added_any:
            self.update_excluded_weeks_ui_list()
            QMessageBox.information(
                self,
                _("Успех"),
                _("Сгенерировано и добавлено в список {count} недель.", count=count),
            )
        else:
            QMessageBox.information(
                self, _("Информация"), _("Все сгенерированные недели уже присутствуют в списке.")
            )

    def load_data(self):
        p_data = self.facade.get_participant(self.participant_id)
        if p_data:
            self.name_edit.setText(p_data["name"])
            self.email_edit.setText(p_data.get("email") or "")
            self.phone_edit.setText(p_data.get("phone") or "")
            # выбор по коду в данных пункта, а не по надписи: надписи переводятся
            self.gender_combo.setCurrentIndex(
                self.gender_combo.findData("male" if p_data["gender"] == "male" else "female")
            )

            role_code = {
                "ministerial_servant": "MS",
                "MS": "MS",
                "elder": "E",
                "E": "E",
            }.get(p_data["service_type"], "PUB")
            self.role_combo.setCurrentIndex(self.role_combo.findData(role_code))

            # Семья
            f_id = p_data["family_group_id"]
            if f_id:
                idx = self.family_combo.findData(f_id)
                if idx >= 0:
                    self.family_combo.setCurrentIndex(idx)

            # Загрузка квалификаций
            quals = p_data.get("qualifications", [])
            for q_key in self.checkboxes:
                if q_key in quals:
                    self.checkboxes[q_key].setChecked(True)
            self._hidden_quals = [q for q in quals if q not in self.checkboxes]

            # Загрузка персонального интервала
            pg = p_data.get("personal_gap")  # None или int
            idx = 0  # По умолчанию «Авто»
            for i, (_, val) in enumerate(self._gap_options):
                if val == pg:
                    idx = i
                    break
            self.personal_gap_combo.setCurrentIndex(idx)

            # Загрузка флага несовершеннолетнего
            self.is_minor_check.setChecked(bool(p_data.get("is_minor", False)))

            # Загрузка дат отпуска
            u_from = p_data.get("unavailable_from")
            u_to = p_data.get("unavailable_to")
            if u_from or u_to:
                self.vacation_group.setChecked(True)
                if u_from:
                    self.vacation_from_edit.setDate(QDate(u_from.year, u_from.month, u_from.day))
                if u_to:
                    self.vacation_to_edit.setDate(QDate(u_to.year, u_to.month, u_to.day))
            else:
                self.vacation_group.setChecked(False)

            # Загрузка исключенных недель
            weeks_val = self.facade.participants.get_excluded_weeks(self.participant_id)
            if isinstance(weeks_val, list):
                self.excluded_weeks_dates = weeks_val
            else:
                self.excluded_weeks_dates = []
            self.update_excluded_weeks_ui_list()

    def save(self):
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, _("Предупреждение"), _("Поле 'ФИО' не может быть пустым."))
            return

        email = self.email_edit.text().strip() or None
        phone = self.phone_edit.text().strip() or None
        gender = self.gender_combo.currentData() or "female"
        role = self.role_combo.currentData() or "PUB"

        quals = [key for key, cb in self.checkboxes.items() if cb.isChecked()] + self._hidden_quals
        family_id = self.family_combo.currentData()

        personal_gap = self.personal_gap_combo.currentData()
        is_minor = self.is_minor_check.isChecked()

        if self.vacation_group.isChecked():
            q_from = self.vacation_from_edit.date()
            q_to = self.vacation_to_edit.date()
            unavailable_from = date(q_from.year(), q_from.month(), q_from.day())
            unavailable_to = date(q_to.year(), q_to.month(), q_to.day())
        else:
            unavailable_from = None
            unavailable_to = None

        if self.participant_id:
            success = self.facade.update_participant(
                self.participant_id,
                name,
                gender,
                role,
                quals,
                family_id,
                personal_gap=personal_gap,
                is_minor=is_minor,
                unavailable_from=unavailable_from,
                unavailable_to=unavailable_to,
                email=email,
                phone=phone,
            )
            if not success:
                QMessageBox.warning(self, _("Ошибка"), _("Не удалось обновить возвещателя."))
                return
            p_id = self.participant_id
        else:
            new_id = self.facade.add_participant(
                name,
                gender,
                role,
                quals,
                family_id,
                personal_gap=personal_gap,
                is_minor=is_minor,
                unavailable_from=unavailable_from,
                unavailable_to=unavailable_to,
                email=email,
                phone=phone,
            )
            if new_id is None:
                QMessageBox.warning(
                    self,
                    _("Ошибка"),
                    _("Не удалось добавить возвещателя. Возможно, такое имя уже существует."),
                )
                return
            p_id = new_id

        # Сохранение списка исключенных недель
        self.facade.participants.set_excluded_weeks(p_id, self.excluded_weeks_dates)
        self.accept()
