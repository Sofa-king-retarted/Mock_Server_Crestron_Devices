FROM python:3.12-slim
WORKDIR /app
COPY . /app
EXPOSE 8080 4352 4354 4356 5678 5680 5682 52381/udp 9001 2202 8101 8102 8103 8104 8105 8106 9100 9200 9300 9401 9402 9403
CMD ["python", "-m", "crestron_av_sim", "--lab", "config/labs/default_lab.json", "--catalog", "catalog/device_catalog.json", "--scenarios", "config/scenarios.json"]
