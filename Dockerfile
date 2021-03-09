FROM python:3.9.2-slim

# Install security updates, make, gcc and clang
RUN apt-get update && \
    apt-get -y upgrade && \
    DEBIAN_FRONTEND=noninteractive apt-get -y install make gcc clang && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Create a user that has the same GID and UID as you
ARG GROUP_ID
ARG USER_ID
RUN groupadd -g $GROUP_ID retrowrite
RUN useradd -m -r -u $USER_ID -g $GROUP_ID retrowrite

# Work directory
WORKDIR /home/retrowrite/retrowrite

# Install python dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Create a symbolic link to have access to the retrowrite command
RUN ln -s /retrowrite/retrowrite/retrowrite /bin/retrowrite

# Use the retrowrite user
USER retrowrite