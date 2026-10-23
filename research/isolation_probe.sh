#!/bin/sh
# R1 probe: try each target and report whether it answered.
# Uses only BusyBox tools built into Alpine. Every attempt has a timeout.

lookup() {  # name
    if nslookup "$1" >/dev/null 2>&1; then
        echo "resolves     $1"
    else
        echo "no answer    $1"
    fi
}

check() {  # label host port
    if nc -z -w 3 "$2" "$3" >/dev/null 2>&1; then
        echo "REACHABLE    $1 ($2:$3)"
    else
        echo "unreachable  $1 ($2:$3)"
    fi
}

echo "== DNS lookups =="
lookup host.docker.internal
lookup example.com

echo "== Connections =="
check "router web page"  "$ROUTER_IP" 80
check "router HTTPS"     "$ROUTER_IP" 443
check "PC file sharing"  "$PC_IP" 445
check "Ollama on the PC" host.docker.internal 11434
check "cloud metadata"   169.254.169.254 80
check "public website"   example.com 443

# On the isolated network names don't resolve, so a failure above could be DNS
# alone. Direct addresses prove the network itself is blocked.
echo "== Direct addresses (no DNS) =="
check "PC via Docker host address" 192.168.65.254 11434
check "public address"             1.1.1.1 443
