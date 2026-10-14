FROM python:3.13-alpine3.22
WORKDIR /app
COPY fan_tracker /app/fan_tracker
CMD ["python", "-u", "-m", "fan_tracker", "--config", "/data/options.json"]
