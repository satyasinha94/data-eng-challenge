FROM python:3.8-slim

COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . app
WORKDIR app

ENTRYPOINT ["python", "-m", "nhldata.app", "--start-date", "2020-08-04", "--end-date", "2020-08-05"]
