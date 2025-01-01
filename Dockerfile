ARG BASE_IMAGE=python:3.12-alpine

FROM ${BASE_IMAGE} AS static-builder
WORKDIR /code

RUN apk update && apk add npm git openssh

COPY package.json package-lock.json /code/
RUN npm install

FROM ${BASE_IMAGE} AS base-builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /www/media
WORKDIR /code/logs

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

RUN pip install -U pip wheel setuptools && pip install -U poetry

FROM base-builder AS base
WORKDIR /code
ARG UID=1000

RUN addgroup -g ${UID} user && \
        adduser -u ${UID} -DG user user
RUN chown -R user:user /code /www && \
        chmod 555 -R /www /code

COPY poetry.lock pyproject.toml /code/

RUN poetry install --without dev


FROM base AS prod
USER user
COPY . /code
COPY --from=static-builder /code/node_modules /var/static
COPY ./static/assets /var/static/assets
CMD gunicorn waiter:gunicorn_app

FROM base AS dev-root
COPY --from=static-builder /code/node_modules /var/static
RUN poetry install

FROM dev-root AS dev
USER user
