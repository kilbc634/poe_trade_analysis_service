FROM selenium/standalone-chrome:140.0-chromedriver-140.0-20251020

USER root
RUN apt-get update && apt-get install -y python3 python3-pip
RUN python3 --version && pip3 --version

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

CMD ["bash"]
