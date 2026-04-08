FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install --no-cache-dir .

EXPOSE 8200

ENTRYPOINT ["thesma-mcp"]
