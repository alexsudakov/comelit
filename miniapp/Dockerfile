FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV COMELIT_MINIAPP_CARD_PATH=/app/shared/comelit-card.js

COPY miniapp/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY miniapp/app ./app
COPY custom_components/comelit/frontend/comelit-card.js ./shared/comelit-card.js

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
