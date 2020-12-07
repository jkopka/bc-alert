FROM python:3.8-slim
ADD . /src
WORKDIR /src
ENV TELEGRAM_TOKEN=""
RUN pip3 install --upgrade pip
RUN pip3 install -r requirements.txt
CMD ["python3", "main.py"]
