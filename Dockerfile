FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5006

ENV PYTHONUNBUFFERED=1

CMD ["python", "App.py"]
