FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

ENV APP_USER=admin
ENV APP_PASS=admin123

ENTRYPOINT ["streamlit", "run", "streamlit_app.py", "--server.port=10000", "--server.address=0.0.0.0", "--server.headless=true", "--server.enableCORS=false", "--server.enableXsrfProtection=false"]
