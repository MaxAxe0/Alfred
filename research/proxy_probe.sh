#!/bin/sh
# R2 probe: send requests through the proxy and report what happened.
# Runs in the curl image on the isolated network, with HTTP(S)_PROXY set.
#
# Smokescreen answers a refused request with HTTP 407. If the request never
# reached the proxy at all, say so: that is a test setup problem, not a pass.

try() {  # label url [extra curl options]
    label=$1; url=$2; shift 2
    out=$(curl -sS -o /dev/null --max-time 10 \
        -w '%{http_code} %{http_connect} %{proxy_used}' "$@" "$url" 2>/dev/null)
    status=$?
    set -- $out  # $1 = HTTP status, $2 = tunnel status, $3 = 1 if the proxy was used
    if [ "$3" != "1" ]; then
        result="NOT SENT THROUGH PROXY (curl exit $status)"
    elif [ "$1" = "407" ] || [ "$2" = "407" ]; then
        result="refused by proxy"
    else
        case "$1" in
            2??|3??) result="ALLOWED (page loaded, status $1)" ;;
            *) result="ALLOWED by proxy, far end failed (curl exit $status)" ;;
        esac
    fi
    printf '%-24s %-36s %s\n' "$label" "$url" "$result"
}

echo "== Should be allowed =="
try "public HTTPS"          "https://example.com/"
try "public HTTP"           "http://example.com/"

echo "== Should be refused =="
try "router web page"       "http://$ROUTER_IP/"
try "router HTTPS"          "https://$ROUTER_IP/"
# -p asks the proxy for a raw tunnel, the way a non-web connection would.
try "PC file sharing"       "http://$PC_IP:445/" -p
try "Ollama by name"        "http://host.docker.internal:11434/"
try "Ollama by address"     "http://192.168.65.254:11434/"
try "cloud metadata"        "http://169.254.169.254/"
try "the proxy itself"      "http://proxy:4750/"
try "IPv4-mapped IPv6"      "http://[::ffff:192.168.1.1]/"

# Public DNS names that point at private addresses. Sent to the test proxy
# that uses Cloudflare DNS, because a home router may hide these answers.
echo "== DNS tricks (proxy using public DNS) =="
P="-x http://proxy-public-dns:4750"
try "check: public site"    "http://example.com/" $P
try "name -> router"        "http://192.168.1.1.nip.io/" $P
try "name -> loopback"      "http://127.0.0.1.nip.io/" $P
try "name -> loopback 2"    "http://localtest.me/" $P
try "name -> metadata"      "http://169.254.169.254.nip.io/" $P

echo "== Known gap: ports are not restricted by the proxy =="
try "public site, port 8080" "http://example.com:8080/"
