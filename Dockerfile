FROM python:3
MAINTAINER James Tanner <tanner.jc@gmail.com>

ENV PYTHONUNBUFFERED 1
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
RUN python setup.py install
EXPOSE 80 443 5000
CMD ["github-test-proxy", "smart"]
