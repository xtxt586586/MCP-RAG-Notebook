FROM python:3.11-slim AS build
ARG TARGETARCH
RUN apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && case "$TARGETARCH" in \
         amd64) sha=d3847fef834e9db11bf64e3fb34db9c04db14e068eeb064f49af747010454f90 ;; \
         arm64) sha=52ce172f96e21da53b1ae9079808560d49b02ac86cecfa457217597f9bc28ab3 ;; \
         *) exit 1 ;; \
       esac \
    && curl -fL --retry 3 "https://go.dev/dl/go1.23.12.linux-${TARGETARCH}.tar.gz" -o /tmp/go.tar.gz \
    && echo "$sha  /tmp/go.tar.gz" | sha256sum -c - \
    && tar -C /usr/local -xzf /tmp/go.tar.gz && rm /tmp/go.tar.gz
ENV PATH="/usr/local/go/bin:${PATH}"
WORKDIR /src
RUN git clone --depth 1 --branch RELEASE.2024-12-18T13-15-44Z https://github.com/minio/minio.git . \
    && test "$(git rev-parse HEAD)" = "16f8cf1c52f0a77eeb8f7565aaf7f7df12454583"
ARG GOPROXY=https://proxy.golang.org,direct
RUN export MINIO_RELEASE=RELEASE \
    && LDFLAGS="$(go run buildscripts/gen-ldflags.go 2024-12-18T13:15:44Z)" \
    && CGO_ENABLED=0 go build -tags kqueue -trimpath -ldflags "$LDFLAGS" -o /out/minio .

FROM python:3.11-slim
RUN apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /out/minio /usr/local/bin/minio
ENTRYPOINT ["/usr/local/bin/minio"]
CMD ["--help"]
