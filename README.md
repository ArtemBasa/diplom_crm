# Flask CRM

Простая CRM на Python/Flask с SQLite

## Описание

Управление товарами, категориями, заказами и отзывами через web-интерфейс.

## Структура проекта

```````
diplom_crm/
├── app.py
├── requirements.txt
├── .gitignore
├── README.md
├── docs/
│ └── diagrams/
│ └── crm_erd.png
├── static/
└── templates/


## Установка и запуск

```bash
git clone https://github.com/ArtemBasa/diplom_crm.git
cd diplom_crm
python -m venv venv
venv/Scripts/activate    # Windows
# source venv/bin/activate # macOS/Linux
pip install -r requirements.txt
python -c "from app import init_db; init_db()"
python app.py
