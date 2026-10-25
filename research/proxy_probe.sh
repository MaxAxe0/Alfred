#!/bin/sh
# R2 probe: send requests through the proxy and report what happened.
# Runs in the curl image on the isolated network, with HTTP(S)_PROXY set.
#
# Smokescreen answers a refused request with HTTP 407. If the request never
# reached the proxy at all, say so: that is a test setup problem, not a pass.

try() {  # label url [extra curl options]
    label=$1; url=$2; shift 2
    out=$(curl -sS -o /dev/null --max-time 10 -D /tmp/headers \
        -w '%{http_code} %{http_connect} %{proxy_used}' "$@" "$url" 2>/dev/null)
    status=$?
    # Smokescreen explains its own errors in this header (e.g. a name it can't resolve).
    why=$(grep -i '^X-Smokescreen-Error:' /tmp/headers 2>/dev/null | head -1 | cut -d: -f2- | tr -d '\r')
    set -- $out  # $1 = HTTP status, $2 = tunnel status, $3 = 1 if the proxy was used
    if [ "$3" != "1" ]; then
        result="NOT SENT THROUGH PROXY (curl exit $status)"
    elif [ "$status" = "5" ] || [ "$status" = "7" -a "$1" = "000" -a "$2" = "000" ]; then
        # 5: proxy name not found; 7 with no response: proxy not answering.
        result="PROXY UNREACHABLE (curl exit $status) - test not run"
    elif [ "$1" = "407" ] || [ "$2" = "407" ]; then
        result="refused by proxy"
    elif [ -n "$why" ]; then
        result="blocked by proxy:$why"
    else
        case "$1" in
            2??|3??) result="ALLOWED (page loaded, status $1)" ;;
            *) result="ALLOWED by proxy, far end failed (curl exit $status)" ;;
        esac
    fi
    printf '%-24s %-36s %s\n' "$label" "$url" "$result"
    rm -f /tmp/headers
    # Stay under the proxy's rate limit (5 requests/second) so every check is judged.
    sleep 0.3
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

# Public DNS names that point at private addresses. The proxy asks public DNS
# (R2e), so these resolve to the private address and must be refused by the
# proxy itself rather than hidden by a home router.
echo "== DNS tricks =="
try "name -> router"        "http://192.168.1.1.nip.io/"
try "name -> loopback"      "http://127.0.0.1.nip.io/"
try "name -> loopback 2"    "http://localtest.me/"
try "name -> metadata"      "http://169.254.169.254.nip.io/"

echo "== Known gap: ports are not restricted by the proxy =="
try "public site, port 8080" "http://example.com:8080/"

# Fire 20 requests as fast as possible. With a burst of 10 and 5/second,
# roughly the first 10 should load and later ones should be turned away.
echo "== Rate limit (20 quick requests) =="
sleep 3  # let the proxy's allowance refill first
codes=""
i=0
while [ $i -lt 20 ]; do
    codes="$codes $(curl -s -o /dev/null --max-time 10 -w '%{http_code}' http://example.com/)"
    i=$((i + 1))
done
echo "status codes:$codes"
