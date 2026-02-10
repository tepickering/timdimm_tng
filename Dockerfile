FROM ubuntu:latest

LABEL maintainer="te.pickering@gmail.com"

WORKDIR /timdimm

COPY . .

ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt update && apt -y upgrade \
    && apt install -y software-properties-common python3-pip python3-ipython git dbus-x11

RUN apt-add-repository ppa:mutlaqja/ppa && apt update && apt install -y indi-full kstars-bleeding gsc

RUN python3 -m pip install -e .[dev]
