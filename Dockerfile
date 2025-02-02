ARG BASE_IMAGE=python:3.12-alpine

FROM node:alpine3.20 AS static-builder
WORKDIR /code

COPY package.json package-lock.json /code/
RUN npm install

FROM ${BASE_IMAGE} AS base-builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=.
ENV UV_PROJECT_DIR=/mw
ENV VIRTUAL_ENV=${UV_PROJECT_DIR}/.venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

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
        make && \
        pip install --upgrade --no-cache-dir pip uv && \
        uv venv --seed ${VIRTUAL_ENV}


FROM base-builder AS base
ARG UID=1000

WORKDIR /code

RUN addgroup -g ${UID} user && \
        adduser -u ${UID} -DG user user
RUN chown -R user:user /code /www && \
        chmod 555 -R /www /code

COPY uv.lock pyproject.toml ${UV_PROJECT_DIR}/

RUN uv sync --no-dev --project ${VIRTUAL_ENV}


FROM base AS prod
USER user
COPY . /code
COPY --from=static-builder /code/node_modules /var/static
COPY ./static/assets /var/static/assets
CMD ["gunicorn", "waiter:gunicorn_app"]

FROM base AS dev-root
COPY --from=static-builder /code/node_modules /var/static
RUN uv sync --project "${VIRTUAL_ENV}"

FROM dev-root AS dev
USER user
