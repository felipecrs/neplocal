FROM python:3.14-alpine

COPY neplocal/*.py /opt/neplocal/

WORKDIR /wd/
EXPOSE 80
VOLUME /wd/captures

ENTRYPOINT ["python", "-m", "neplocal.proxy"]
