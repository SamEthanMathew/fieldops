FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/README.md ./backend/README.md
COPY backend/app ./backend/app
COPY data ./data
COPY docs ./docs
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
COPY shared ./shared
COPY README.md ./

RUN pip install --no-cache-dir -e ./backend

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
