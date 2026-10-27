"""Turn MongoDB driver errors into plain-English messages."""


def explain(err: str) -> str:
    e = (err or "").lower()
    if "authentication failed" in e or "auth failed" in e or "bad auth" in e:
        return ("The username or password is wrong. If they are correct, try setting "
                "'Login database' to admin.")
    if "not authorized" in e or "unauthorized" in e:
        return "Connected, but this user doesn't have permission to read that database."
    if any(x in e for x in ("nodename nor servname", "name or service not known", "getaddrinfo",
                            "no address associated", "dns", "nxdomain", "name resolution")):
        return "The server address can't be found. Check the spelling, or connect to VPN if it's a private server."
    if any(x in e for x in ("timed out", "serverselectiontimeout", "no servers", "connection refused",
                            "network is unreachable", "no route to host", "actively refused")):
        return ("Can't reach the database from this computer. Usually: VPN is off, this computer's IP "
                "isn't allowed on the database server, or a firewall blocks the port. "
                "Ask your server admin to allow this computer's IP.")
    if "invalid uri" in e or "must begin with" in e or "invalid port" in e or "not a valid" in e:
        return "The connection details look incomplete or mistyped. Please check them."
    if "replicaset" in e or "replica set" in e:
        return "The database is a replica set. Tick 'Connect directly to this server' and try again."
    return "Couldn't connect. Technical detail: " + (err or "")[:200]
