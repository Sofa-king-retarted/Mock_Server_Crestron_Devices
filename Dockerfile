FROM python:3.12-slim
WORKDIR /app
COPY . /app
EXPOSE 8080 4352 5678 52381/udp 9001 2202 8101 8102 9100
CMD ["python", "-m", "crestron_av_sim", "--config", "config/devices.json", "--scenarios", "config/scenarios.json"]
