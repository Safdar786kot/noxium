# Noxium node image (multi-stage, reproducible "depends" build)
#   docker build -t noxium .
#   docker run -d --name noxiumd -p 17750:17750 -v noxium-data:/home/noxium/.noxium noxium
FROM ubuntu:20.04 AS builder
RUN set -ex && apt-get update && DEBIAN_FRONTEND=noninteractive apt-get --no-install-recommends --yes install \
      automake autotools-dev bsdmainutils build-essential ca-certificates ccache cmake curl git libtool pkg-config gperf python3
WORKDIR /src
COPY . .
ARG NPROC
RUN set -ex && rm -rf build && make -j${NPROC:-$(nproc)} depends target=x86_64-linux-gnu

FROM ubuntu:20.04
RUN set -ex && apt-get update && apt-get --no-install-recommends --yes install ca-certificates curl && \
    apt-get clean && rm -rf /var/lib/apt
COPY --from=builder /src/build/x86_64-linux-gnu/release/bin /usr/local/bin/
RUN adduser --system --group --disabled-password noxium && \
    mkdir -p /wallet /home/noxium/.noxium && chown -R noxium:noxium /home/noxium/.noxium /wallet
VOLUME /home/noxium/.noxium
VOLUME /wallet
EXPOSE 17750 17751
USER noxium
HEALTHCHECK --interval=60s --timeout=10s CMD curl -fsS http://127.0.0.1:17751/get_info >/dev/null || exit 1
ENTRYPOINT ["noxiumd"]
CMD ["--p2p-bind-ip=0.0.0.0", "--p2p-bind-port=17750", "--rpc-bind-ip=0.0.0.0", "--rpc-bind-port=17751", "--restricted-rpc", "--non-interactive", "--confirm-external-bind"]
