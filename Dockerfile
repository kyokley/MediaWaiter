ARG BASE_IMAGE=python:3.8-slim

FROM ${BASE_IMAGE} AS static-builder
WORKDIR /code

RUN apt-get update && apt-get install -y \
        npm \
        make

RUN npm install -g yarn
RUN mkdir /code/static
COPY package.json /code/package.json
COPY Makefile /code/Makefile
RUN make static

FROM ${BASE_IMAGE} AS prod

MAINTAINER Kevin Yokley

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /code

# Install required packages and remove the apt packages cache when done.
RUN apt-get update && apt-get install -y \
        curl \
        gnupg \
        g++ \
        git \
        ncurses-dev \
        libffi-dev \
        make

ENV VIRTUAL_ENV=/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PYTHONPATH=/code

RUN echo 'alias venv="source /venv/bin/activate"' >> /root/.bashrc
RUN echo 'export PATH=$PATH:/root/.poetry/bin' >> /root/.bashrc

# Add virtualenv to bash prompt
RUN echo 'if [ -z "${VIRTUAL_ENV_DISABLE_PROMPT:-}" ] ; then \n\
              _OLD_VIRTUAL_PS1="${PS1:-}" \n\
              if [ "x(venv) " != x ] ; then \n\
          	PS1="(venv) ${PS1:-}" \n\
              else \n\
              if [ "`basename \"$VIRTUAL_ENV\"`" = "__" ] ; then \n\
                  # special case for Aspen magic directories \n\
                  # see http://www.zetadev.com/software/aspen/ \n\
                  PS1="[`basename \`dirname \"$VIRTUAL_ENV\"\``] $PS1" \n\
              else \n\
                  PS1="(`basename \"$VIRTUAL_ENV\"`)$PS1" \n\
              fi \n\
              fi \n\
              export PS1 \n\
          fi' >> ~/.bashrc

RUN curl -sSL https://raw.githubusercontent.com/sdispater/poetry/master/get-poetry.py | python

COPY poetry.lock /code/poetry.lock
COPY pyproject.toml /code/pyproject.toml
COPY configs/docker_settings.py /code/local_settings.py

RUN /bin/bash -c "pip install --upgrade pip && \
                  /root/.poetry/bin/poetry install --no-dev && \
                  mkdir /root/logs /root/media"

COPY . /code
COPY --from=static-builder /code/static/bower_components /code/static/bower_components

CMD uwsgi --ini /code/server/uwsgi.ini

FROM prod AS dev
RUN /root/.poetry/bin/poetry install
