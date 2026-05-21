FROM python:3.14-alpine

COPY src/neplocal/*.py /opt/neplocal/

ENV PYTHONPATH=/opt
ENV PYTHONUNBUFFERED=1

WORKDIR /wd/
EXPOSE 80
VOLUME /wd/captures

ENTRYPOINT ["python", "-m", "neplocal.proxy"]
