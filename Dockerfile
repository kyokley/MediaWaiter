FROM python:3.6-slim

MAINTAINER Kevin Yokley

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

ARG REQS=--no-dev

WORKDIR /code

# Install required packages and remove the apt packages cache when done.
RUN apt-get update && apt-get install -y \
        curl \
        gnupg \
        g++ \
        git \
        apt-transport-https \
        ncurses-dev \
        make

RUN curl -sS https://dl.yarnpkg.com/debian/pubkey.gpg | apt-key add - && \
    echo "deb https://dl.yarnpkg.com/debian/ stable main" | tee /etc/apt/sources.list.d/yarn.list

RUN curl -sL https://deb.nodesource.com/setup_8.x | bash -

RUN apt-get update && apt-get install -y yarn nodejs

ENV VIRTUAL_ENV=/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

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

COPY package.json /node/package.json
COPY poetry.lock /code/poetry.lock
COPY pyproject.toml /code/pyproject.toml

RUN /bin/bash -c "source /venv/bin/activate && \
                  pip install --upgrade pip && \
                  /root/.poetry/bin/poetry install -vvv ${REQS}"

RUN cd /node && yarn install && rsync -ruv /node/node_modules/* /code/static/

COPY . /code

CMD uwsgi --ini /home/docker/code/uwsgi/uwsi.conf
