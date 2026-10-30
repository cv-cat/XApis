FROM golang:1.27-bookworm AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /gateway .
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 xapis && useradd --uid 10001 --gid xapis --no-create-home xapis \
    && mkdir /shared && chown 10001:10001 /shared
COPY --from=build /gateway /usr/local/bin/xapis-gateway
USER 10001:10001
EXPOSE 8090
ENV X_GATEWAY_TOKEN_FILE=/shared/gateway.token
HEALTHCHECK --interval=15s --timeout=4s --start-period=5s --retries=3 CMD ["/usr/local/bin/xapis-gateway", "healthcheck"]
ENTRYPOINT ["/usr/local/bin/xapis-gateway"]
