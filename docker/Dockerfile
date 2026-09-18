FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VALIDATION_HOME=/opt/validation

WORKDIR /opt/validation

COPY Validation/ /opt/validation/Validation/

RUN python -m pip install --no-cache-dir \
      -r Validation/Data_Parser/requirements.txt \
      -r Validation/Data_Router/requirements.txt \
      -r Validation/Data_Forwarder/requirements.txt \
      -r Validation/Web_Console/requirements.txt \
      -r Validation/Database/requirements.txt

RUN mkdir -p \
      /opt/validation/DATA_INFLOW/SAIS_IOR \
      /opt/validation/DATA_INFLOW/SAIS_GLOBAL \
      /opt/validation/DATA_INFLOW/MSIS \
      /opt/validation/DATA_INFLOW/LRIT \
      /opt/validation/Validation/Data_Forwarder/spool/pending \
      /opt/validation/Validation/Data_Forwarder/spool/delivered \
      /opt/validation/Validation/Data_Forwarder/spool/failed \
      /opt/validation/Validation/Data_Forwarder/state \
      /opt/validation/Validation/Data_Router/state \
      /opt/validation/Validation/Data_Router/logs \
      /opt/validation/Validation/Data_Parser/logs \
      /opt/validation/Validation/Database/PANS/RAW_DATA

COPY docker/parser.yaml /opt/validation/docker/parser.yaml
COPY docker/sources.yaml /opt/validation/docker/sources.yaml
COPY docker/forwarder.yaml /opt/validation/docker/forwarder.yaml
COPY docker/console.yaml /opt/validation/docker/console.yaml

EXPOSE 8080 8081 8082 8088 10001 10002 10003 10004 10005

CMD ["python", "-m", "Validation.Data_Parser.app.main", "--config", "/opt/validation/docker/parser.yaml"]
