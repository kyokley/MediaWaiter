ARG BASE_IMAGE=python:3.9-alpine

FROM ${BASE_IMAGE} AS static-builder
WORKDIR /code

RUN apk update && apk add npm git

RUN npm install -g yarn
COPY package.json /code/package.json
RUN yarn install

FROM ${BASE_IMAGE} AS base

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /code

# Install required packages and remove the apt packages cache when done.
RUN apk update && apk add \
        gnupg \
        g++ \
        git \
        ncurses-dev \
        libffi-dev \
        cargo \
        openssl-dev \
        make

ENV VIRTUAL_ENV=/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PYTHONPATH=/code


RUN pip install -U pip wheel && pip install -U poetry
COPY poetry.lock pyproject.toml configs/docker_settings.py /code/

RUN poetry install --no-dev && mkdir /root/logs /root/media


FROM base AS prod
COPY . /code
COPY --from=static-builder /code/node_modules /var/static/bower_components
COPY ./static/assets /var/static/
CMD uwsgi --ini /code/server/uwsgi.ini

FROM base AS dev
COPY --from=static-builder /code/node_modules /var/static/bower_components
RUN poetry install
