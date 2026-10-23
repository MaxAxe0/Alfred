# R2: Smokescreen egress proxy, built from source.
# Stripe's published images could not be pulled (registry access denied), so we
# build the v0.1.0 release ourselves. The commit hash pins the exact source;
# go.sum inside it pins every dependency.

FROM golang:1.25-alpine AS build
# Commit for release tag v0.1.0.
ARG SMOKESCREEN_COMMIT=609eb8931420453daf5893509be0b25b21bd9edb
RUN apk add --no-cache git
WORKDIR /src
RUN git init -q \
 && git remote add origin https://github.com/stripe/smokescreen.git \
 && git fetch -q --depth 1 origin "$SMOKESCREEN_COMMIT" \
 && git checkout -q FETCH_HEAD
# Static binary (no C libraries) so it runs on the minimal base image below.
RUN CGO_ENABLED=0 go build -trimpath -o /out/smokescreen .

# Same minimal, non-root base image that Stripe's own Dockerfile pins:
# no shell, no package manager, just the binary.
FROM gcr.io/distroless/static:nonroot@sha256:e2e927ec666bae08560abb3c55d0659eceabb657f56b6782ab500a9fc7f555e3
COPY --from=build --chmod=0555 /out/smokescreen /smokescreen
USER 65532:65532
EXPOSE 4750
ENTRYPOINT ["/smokescreen"]
CMD ["--listen-ip", "0.0.0.0", "--listen-port", "4750"]
