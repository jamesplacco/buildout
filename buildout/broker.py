"""Brokers (v0.42): one interface, three ways to reach a market.

    Broker              what the trader needs: the account, quotes, a limit order, its status, a cancel
    PaperBroker         a model account filled at the quote plus the collar; its state is a JSON file. Runs in public
                        every day from the daily workflow (paper/account.json) and privately for rehearsal.
    AssistantBroker     places nothing. It writes each order into the ticket's hand-off for an assistant that holds
                        Robinhood's Trading MCP (Claude with the Robinhood connector), which places the orders and
                        reports the fills back through record_fills. Buildout holds no credential on this route.
    MCPBroker           Buildout's own client on Robinhood's Trading MCP (https://agent.robinhood.com/mcp/trading):
                        JSON-RPC 2.0 over streamable HTTP with OAuth, in the standard library. Robinhood publishes the
                        endpoint and the tool categories but not the tool names (support pages read Nov 8, 2026), so
                        the names and argument shapes live in private/broker.toml, filled from `python -m buildout broker probe`,
                        which lists what the server offers. Untested against the live endpoint from this build.

Every broker's place() is idempotent on client_id: the same ticket order is never sent twice.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "private"
ROBINHOOD_MCP = "https://agent.robinhood.com/mcp/trading"
UA = "buildout-trader/0.42"


class Broker(Protocol):
    name: str

    def account(self) -> dict: ...
    def quotes(self, symbols: list[str]) -> dict: ...
    def place(self, symbol: str, side: str, quantity: float, limit: float, client_id: str) -> dict: ...
    def order(self, order_id: str) -> dict: ...
    def cancel(self, order_id: str) -> dict: ...
    def open_orders(self) -> list[dict]: ...


# ---------------------------------------------------------------- paper
class PaperBroker:
    """A cash account marked at the last quote. Fills happen at the limit when the limit is through the quote (a buy
    at or above the ask, a sell at or below the bid), else the order rests and is cancelled at the ticket's expiry."""

    name = "paper"

    def __init__(self, path: str | Path | None = None, quote_fn=None, start_cash: float = 100_000.0):
        self.path = Path(path) if path else PRIVATE / "paper_account.json"
        self.quote_fn = quote_fn
        self.start_cash = start_cash
        self.state = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {"account_type": "agentic (paper)", "cash": self.start_cash, "positions": {}, "orders": {}, "marks": {}, "opened": datetime.now(timezone.utc).date().isoformat(),
                "equity_history": [], "start_cash": self.start_cash}

    def save(self, state: dict | None = None) -> None:
        """Atomic: write a temporary file beside the account, then rename it over. A crash leaves the old file or
        the new one, never half of one (v0.42.3)."""
        _atomic_write_json(self.path, self.state if state is None else state)

    def quotes(self, symbols: list[str]) -> dict:
        if self.quote_fn is None:
            raise RuntimeError("the paper broker needs a quote source")
        q = self.quote_fn([s.upper() for s in symbols])
        for s, v in q.items():
            self.state["marks"][s] = {"last": float(v["last"]), "asof": v.get("asof", "")}
        return q

    def mark(self, quotes: dict | None = None) -> dict:
        """Equity at the latest marks; appends a daily point to the equity history (one per date)."""
        if quotes:
            for s, v in quotes.items():
                self.state["marks"][s.upper()] = {"last": float(v["last"]), "asof": v.get("asof", "")}
        pos = self.state["positions"]
        value = sum(float(q) * float(self.state["marks"].get(s, {}).get("last") or 0) for s, q in pos.items())
        eq = round(float(self.state["cash"]) + value, 2)
        asof = max((m.get("asof", "") for m in self.state["marks"].values()), default="")
        hist = self.state["equity_history"]
        if asof and (not hist or hist[-1][0] != asof):
            hist.append([asof, eq])
        elif hist and asof:
            hist[-1][1] = eq
        return {"equity": eq, "positions_value": round(value, 2), "asof": asof}

    def account(self) -> dict:
        m = self.mark()
        return {"account_type": self.state["account_type"], "cash": round(float(self.state["cash"]), 2), "equity": m["equity"],
                "positions": [{"symbol": s, "quantity": q} for s, q in sorted(self.state["positions"].items()) if abs(q) > 1e-9], "marks_asof": m["asof"]}

    def place(self, symbol: str, side: str, quantity: float, limit: float, client_id: str) -> dict:
        """Validate, compute the account as it would be, check it, write it, and only then adopt it (v0.42.3). A
        refused order leaves the account in memory and on disk exactly as it was."""
        symbol, side, quantity, limit = validate_order(symbol, side, quantity, limit, client_id)
        prior = self.state["orders"].get(client_id)
        if prior is not None:
            if (prior["symbol"], prior["side"], float(prior["quantity"]), float(prior["limit"])) != (symbol, side, quantity, limit):
                raise ValueError(f"client id {client_id} was used for a different order ({prior['side']} {prior['quantity']:g} {prior['symbol']} at {prior['limit']}); refusing")
            return prior                                              # the same order again: the first result, no second effect
        mk = self.state["marks"].get(symbol)
        if not mk:
            raise RuntimeError(f"no quote for {symbol}; call quotes() first")
        last = float(mk["last"])
        bid, ask = last * (1 - 0.0005), last * (1 + 0.0005)
        fills = (side == "buy" and limit >= ask - 1e-9) or (side == "sell" and limit <= bid + 1e-9)
        new = json.loads(json.dumps(self.state))                       # the candidate account
        if fills:
            held = float(new["positions"].get(symbol, 0.0))
            if side == "sell" and quantity > held + 1e-9:
                raise RuntimeError(f"paper: selling {quantity:g} {symbol} with {held:g} held")
            cash = float(new["cash"]) - (quantity if side == "buy" else -quantity) * limit
            if cash < -1e-6:
                raise RuntimeError(f"paper: the buy costs {quantity * limit:,.2f} with {float(new['cash']):,.2f} in cash")
            pos = held + (quantity if side == "buy" else -quantity)
            if abs(pos) < 1e-9:
                new["positions"].pop(symbol, None)
            else:
                new["positions"][symbol] = pos
            new["cash"] = cash
        o = {"order_id": f"paper-{client_id}", "client_id": client_id, "symbol": symbol, "side": side, "quantity": quantity, "limit": limit,
             "status": "filled" if fills else "open", "filled_qty": quantity if fills else 0.0, "avg_price": limit if fills else None,
             "placed": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        new["orders"][client_id] = o
        self.save(new)                                                 # raises before adoption if the disk refuses
        self.state = new
        return o

    def order(self, order_id: str) -> dict:
        for o in self.state["orders"].values():
            if o["order_id"] == order_id:
                return o
        raise KeyError(order_id)

    def cancel(self, order_id: str) -> dict:
        o = self.order(order_id)
        if o["status"] == "open":
            o["status"] = "cancelled"
            self.save()
        return o

    def open_orders(self) -> list[dict]:
        return [o for o in self.state["orders"].values() if o["status"] == "open"]


# ---------------------------------------------------------------- the assistant route
class AssistantBroker:
    """Nothing is sent from here. place() records the order as a hand-off; the assistant holding Robinhood's MCP
    places it and reports fills through record_fills. account() and quotes() come from the ticket's inputs, which the
    assistant fetched from Robinhood and passed in."""

    name = "assistant"

    def __init__(self, account: dict, quotes: dict):
        self._account, self._quotes, self.handoff = account, {k.upper(): v for k, v in quotes.items()}, []

    def account(self) -> dict:
        return self._account

    def quotes(self, symbols: list[str]) -> dict:
        return {s.upper(): self._quotes[s.upper()] for s in symbols if s.upper() in self._quotes}

    def place(self, symbol: str, side: str, quantity: float, limit: float, client_id: str) -> dict:
        o = {"order_id": None, "client_id": client_id, "symbol": symbol.upper(), "side": side, "quantity": float(quantity), "limit": float(limit), "status": "handoff",
             "instruction": f"Through Robinhood's Trading MCP, in the Agentic account: {side} {quantity:g} {symbol.upper()} at a limit of {limit:.2f}, day order. Then report the fill through record_fills with this client_id."}
        self.handoff.append(o)
        return o

    def order(self, order_id: str) -> dict:
        return {"order_id": order_id, "status": "unknown", "note": "fills on this route arrive through record_fills"}

    def cancel(self, order_id: str) -> dict:
        return {"order_id": order_id, "status": "ask the assistant to cancel through Robinhood's MCP"}

    def open_orders(self) -> list[dict]:
        return []


# ---------------------------------------------------------------- Robinhood's Trading MCP, directly
def _post_json(url: str, body: dict, headers: dict, timeout: int = 30) -> tuple[int, dict, bytes]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", "User-Agent": UA, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def _get_json(url: str, headers: dict | None = None, timeout: int = 20) -> dict | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except (urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None


def _parse_mcp_response(status: int, headers: dict, raw: bytes) -> dict:
    """JSON, or the last JSON-RPC message of an SSE stream."""
    text = raw.decode(errors="replace")
    ctype = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
    if "text/event-stream" in ctype:
        msgs = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        for m in reversed(msgs):
            try:
                d = json.loads(m)
                if "result" in d or "error" in d:
                    return d
            except json.JSONDecodeError:
                continue
        raise RuntimeError(f"MCP: no JSON-RPC result in the event stream (HTTP {status})")
    try:
        return json.loads(text) if text.strip() else {"result": None}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"MCP: HTTP {status}, not JSON: {text[:200]}") from exc


class OAuth:
    """The MCP authorization flow (OAuth 2.1 with PKCE): protected-resource metadata, authorization-server metadata,
    dynamic client registration when the server offers it, a browser for the person's consent, a localhost callback,
    and refresh. Tokens live in private/<name>_oauth.json."""

    def __init__(self, resource: str, store: Path, redirect_port: int = 8765, scopes: str | None = None):
        self.resource, self.store, self.port, self.scopes = resource, store, redirect_port, scopes
        self.tok = json.loads(store.read_text()) if store.exists() else {}

    def discover(self) -> dict:
        base = urllib.parse.urlsplit(self.resource)
        origin = f"{base.scheme}://{base.netloc}"
        out = {"resource": self.resource}
        prm = _get_json(f"{origin}/.well-known/oauth-protected-resource{base.path}") or _get_json(f"{origin}/.well-known/oauth-protected-resource")
        out["protected_resource"] = prm
        auth_servers = (prm or {}).get("authorization_servers") or [origin]
        asm = None
        for a in auth_servers:
            asm = _get_json(a.rstrip("/") + "/.well-known/oauth-authorization-server") or _get_json(a.rstrip("/") + "/.well-known/openid-configuration")
            if asm:
                break
        out["authorization_server"] = asm
        if prm and prm.get("scopes_supported") and not self.scopes:
            self.scopes = " ".join(prm["scopes_supported"])
        return out

    def register(self, asm: dict) -> dict:
        if self.tok.get("client_id"):
            return {"client_id": self.tok["client_id"]}
        reg = asm.get("registration_endpoint")
        if not reg:
            raise RuntimeError("the authorization server offers no dynamic client registration; set client_id in private/broker.toml from Robinhood's developer settings")
        st, hd, raw = _post_json(reg, {"client_name": "Buildout trader", "redirect_uris": [f"http://127.0.0.1:{self.port}/callback"], "grant_types": ["authorization_code", "refresh_token"],
                                       "response_types": ["code"], "token_endpoint_auth_method": "none"}, {})
        if st not in (200, 201):
            raise RuntimeError(f"client registration failed: HTTP {st} {raw[:200]!r}")
        d = json.loads(raw)
        self.tok.update({"client_id": d["client_id"], "client_secret": d.get("client_secret")})
        self._save()
        return d

    def login(self, asm: dict) -> dict:
        """Opens the browser for consent and waits for the callback; stores the tokens."""
        verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode().rstrip("=")
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state = secrets.token_urlsafe(16)
        redirect = f"http://127.0.0.1:{self.port}/callback"
        q = {"response_type": "code", "client_id": self.tok["client_id"], "redirect_uri": redirect, "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "resource": self.resource}
        if self.scopes:
            q["scope"] = self.scopes
        url = asm["authorization_endpoint"] + "?" + urllib.parse.urlencode(q)
        got: dict = {}

        class H(BaseHTTPRequestHandler):
            def do_GET(self_inner):
                qs = urllib.parse.parse_qs(urllib.parse.urlsplit(self_inner.path).query)
                got.update({k: v[0] for k, v in qs.items()})
                self_inner.send_response(200)
                self_inner.send_header("Content-Type", "text/plain")
                self_inner.end_headers()
                self_inner.wfile.write(b"Buildout: signed in. You can close this tab.")

            def log_message(self_inner, *a):
                pass

        srv = HTTPServer(("127.0.0.1", self.port), H)
        print(f"Open this address to sign in (a browser should open):\n{url}")
        webbrowser.open(url)
        srv.timeout = 300
        srv.handle_request()
        srv.server_close()
        if got.get("state") != state or not got.get("code"):
            raise RuntimeError(f"sign-in did not complete: {got.get('error') or 'no code'}")
        body = {"grant_type": "authorization_code", "code": got["code"], "redirect_uri": redirect, "client_id": self.tok["client_id"], "code_verifier": verifier, "resource": self.resource}
        if self.tok.get("client_secret"):
            body["client_secret"] = self.tok["client_secret"]
        st, hd, raw = self._token_post(asm["token_endpoint"], body)
        if st != 200:
            raise RuntimeError(f"token exchange failed: HTTP {st} {raw[:200]!r}")
        self._store_token(json.loads(raw))
        return {"ok": True, "expires_at": self.tok.get("expires_at")}

    def _token_post(self, url: str, body: dict) -> tuple[int, dict, bytes]:
        data = urllib.parse.urlencode(body).encode()
        req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def _store_token(self, d: dict) -> None:
        self.tok.update({"access_token": d["access_token"], "refresh_token": d.get("refresh_token", self.tok.get("refresh_token")),
                         "expires_at": time.time() + float(d.get("expires_in", 3600)) - 60, "token_type": d.get("token_type", "Bearer")})
        self._save()

    def _save(self) -> None:
        self.store.parent.mkdir(parents=True, exist_ok=True)
        self.store.write_text(json.dumps(self.tok, indent=1))
        try:
            os.chmod(self.store, 0o600)
        except OSError:
            pass

    def token(self, asm: dict | None = None) -> str:
        if self.tok.get("access_token") and time.time() < float(self.tok.get("expires_at", 0)):
            return self.tok["access_token"]
        if self.tok.get("refresh_token") and asm:
            body = {"grant_type": "refresh_token", "refresh_token": self.tok["refresh_token"], "client_id": self.tok["client_id"], "resource": self.resource}
            if self.tok.get("client_secret"):
                body["client_secret"] = self.tok["client_secret"]
            st, hd, raw = self._token_post(asm["token_endpoint"], body)
            if st == 200:
                self._store_token(json.loads(raw))
                return self.tok["access_token"]
        raise RuntimeError("no valid token; run `python -m buildout broker login`")


class MCPBroker:
    """Robinhood's Trading MCP through Buildout's own JSON-RPC client. The tool names and argument shapes come from
    private/broker.toml ([tools] and [args]); `probe()` lists the server's tools so the person can fill them in."""

    name = "robinhood_mcp"

    def __init__(self, config: dict | None = None, oauth: OAuth | None = None):
        cfg = config if config is not None else load_broker_config()
        self.url = cfg.get("url", ROBINHOOD_MCP)
        self.tools = cfg.get("tools", {})
        self.args = cfg.get("args", {})
        self.paths = cfg.get("paths", {})
        self.oauth = oauth or OAuth(self.url, PRIVATE / "robinhood_oauth.json")
        self.session_id: str | None = None
        self.account_key = str(cfg.get("account", "agentic"))       # journal namespace: broker and account
        self.asm: dict | None = None
        self._id = 0
        self._initialized = False

    # -- transport
    def _headers(self) -> dict:
        h = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        tok = self.oauth.token(self.asm)
        h["Authorization"] = f"Bearer {tok}"
        return h

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self._id += 1
        st, hd, raw = _post_json(self.url, {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}, self._headers())
        if st == 401:
            raise RuntimeError("Robinhood's MCP refused the token (401); run `python -m buildout broker login`")
        sid = hd.get("Mcp-Session-Id") or hd.get("mcp-session-id")
        if sid:
            self.session_id = sid
        d = _parse_mcp_response(st, hd, raw)
        if "error" in d and d["error"]:
            raise RuntimeError(f"MCP {method}: {d['error']}")
        return d.get("result") or {}

    def initialize(self) -> dict:
        if self._initialized:
            return {}
        if self.asm is None:
            self.asm = (self.oauth.discover().get("authorization_server") or {})
        r = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "buildout-trader", "version": "0.42"}})
        self._id += 1
        _post_json(self.url, {"jsonrpc": "2.0", "method": "notifications/initialized"}, self._headers())
        self._initialized = True
        return r

    def list_tools(self) -> list[dict]:
        self.initialize()
        out, cursor = [], None
        for _ in range(20):
            r = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            out += r.get("tools", [])
            cursor = r.get("nextCursor")
            if not cursor:
                break
        return out

    def call(self, role: str, **kw) -> dict:
        """Call the tool configured for a role (account, positions, quotes, place, order, cancel, open_orders) with
        the configured argument template filled from kw."""
        name = self.tools.get(role)
        if not name:
            raise RuntimeError(f"no tool configured for {role!r}; run `python -m buildout broker probe` and fill [tools] in private/broker.toml")
        tmpl = self.args.get(role, {})
        args = _fill(tmpl, kw) if tmpl else dict(kw)
        self.initialize()
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        if r.get("isError"):
            raise RuntimeError(f"{name}: {r.get('content')}")
        return _tool_payload(r)

    # -- the Broker interface, through the configured tools and response paths
    def account(self) -> dict:
        d = self.call("account")
        p = self.paths
        acct = _dig(d, p.get("account", "")) if p.get("account") else d
        src = self.call("positions") if self.tools.get("positions") else d
        positions = _dig(src, p["positions"]) if p.get("positions") else (src.get("positions", []) if isinstance(src, dict) else src)
        positions = positions or []
        return {"account_type": str(_dig(acct, p.get("account_type", "account_type")) or ""), "equity": float(_dig(acct, p.get("equity", "equity")) or 0),
                "cash": float(_dig(acct, p.get("cash", "cash")) or 0),
                "positions": [{"symbol": str(_dig(x, p.get("pos_symbol", "symbol"))).upper(), "quantity": float(_dig(x, p.get("pos_quantity", "quantity")) or 0)} for x in positions]}

    def quotes(self, symbols: list[str]) -> dict:
        out = {}
        if self.tools.get("quotes"):
            d = self.call("quotes", symbols=[s.upper() for s in symbols], symbols_csv=",".join(s.upper() for s in symbols))
            rows = _dig(d, self.paths.get("quotes", "")) if self.paths.get("quotes") else d
            rows = rows if isinstance(rows, list) else [rows]
            for x in rows:
                s = str(_dig(x, self.paths.get("q_symbol", "symbol"))).upper()
                out[s] = {"bid": float(_dig(x, self.paths.get("q_bid", "bid")) or 0), "ask": float(_dig(x, self.paths.get("q_ask", "ask")) or 0), "last": float(_dig(x, self.paths.get("q_last", "last")) or 0)}
        else:
            for s in symbols:
                x = self.call("quote", symbol=s.upper())
                out[s.upper()] = {"bid": float(_dig(x, self.paths.get("q_bid", "bid")) or 0), "ask": float(_dig(x, self.paths.get("q_ask", "ask")) or 0), "last": float(_dig(x, self.paths.get("q_last", "last")) or 0)}
        return out

    def place(self, symbol: str, side: str, quantity: float, limit: float, client_id: str) -> dict:
        """At most once (v0.42.3). The intent is written to the journal before anything is sent; the journal says
        what happened after. A send whose outcome is not known (a dropped connection, a crash, a failed write) is
        'unknown' and is never sent again by this code: it is reconciled against the broker by client id, or
        resolved by the person (`python -m buildout broker resolve`)."""
        symbol, side, quantity, limit = validate_order(symbol, side, quantity, limit, client_id)
        J = OrderJournal(self.name, self.account_key)
        intent = {"symbol": symbol, "side": side, "quantity": quantity, "limit": round(limit, 2)}
        rec = J.get(client_id)
        if rec is not None:
            if rec["payload_hash"] != _payload_hash(intent):
                raise ValueError(f"client id {client_id} is already journaled for a different order; refusing")
            if rec["state"] in ("prepared", "submitting", "unknown"):
                found = self.reconcile(client_id)
                if found is None:
                    J.update(client_id, state="unknown", note="not found at the broker by client id; not re-sent")
                    raise OrderUnknown(f"{client_id}: an earlier send may have reached Robinhood; not sending again. Check the account, then "
                                       f"`python -m buildout broker resolve {client_id} --order-id <id>` or `--not-sent`")
                return J.update(client_id, state="acknowledged", order_id=found.get("order_id"), status=found.get("status"), note="reconciled by client id")
            return rec                                                         # acknowledged or later: the first result
        J.prepare(client_id, intent)                                           # durable before the network
        if self.tools.get("review"):
            try:
                self.call("review", symbol=symbol, side=side, quantity=quantity, limit=round(limit, 2), client_id=client_id)
            except Exception as exc:                                           # nothing was placed: the intent is closed, not left open
                J.update(client_id, state="rejected", note=f"review refused: {str(exc)[:160]}")
                raise
        J.update(client_id, state="submitting")
        try:
            d = self.call("place", symbol=symbol, side=side, quantity=quantity, limit=round(limit, 2), client_id=client_id)
        except Exception as exc:                                               # it may or may not have reached the broker
            J.update(client_id, state="unknown", note=f"send failed after it may have arrived: {str(exc)[:160]}")
            raise OrderUnknown(f"{client_id}: the send failed ({str(exc)[:120]}); it may still have been placed. Not retried.") from exc
        o = {"order_id": str(_dig(d, self.paths.get("order_id", "id")) or ""), "client_id": client_id, **intent,
             "status": str(_dig(d, self.paths.get("order_status", "state")) or "submitted"), "placed": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            J.update(client_id, state="acknowledged", order_id=o["order_id"], status=o["status"])
        except Exception:                                                      # placed, but the journal could not say so: never resend
            o["journal_warning"] = "the order was placed but the journal write failed; it reads 'submitting' and will be reconciled, not re-sent"
        return {**o, "raw": d}

    def reconcile(self, client_id: str) -> dict | None:
        """Look for an order with this client id among the broker's orders. Needs a tool that lists orders and a path
        to the client id in each (paths.client_id); without them nothing can be proven and None is returned."""
        if not self.tools.get("open_orders") and not self.tools.get("recent_orders"):
            return None
        path = self.paths.get("client_id", "client_id")
        for role in ("recent_orders", "open_orders"):
            if not self.tools.get(role):
                continue
            try:
                d = self.call(role)
            except Exception:
                return None
            rows = _dig(d, self.paths.get(role, "")) if self.paths.get(role) else d
            for x in rows if isinstance(rows, list) else []:
                if str(_dig(x, path)) == client_id:
                    return {"order_id": str(_dig(x, self.paths.get("order_id", "id")) or ""), "status": str(_dig(x, self.paths.get("order_status", "state")) or "")}
        return None

    def order(self, order_id: str) -> dict:
        d = self.call("order", order_id=order_id)
        return {"order_id": order_id, "status": str(_dig(d, self.paths.get("order_status", "state")) or ""), "filled_qty": float(_dig(d, self.paths.get("filled_qty", "filled_quantity")) or 0),
                "avg_price": _dig(d, self.paths.get("avg_price", "average_price")), "raw": d}

    def cancel(self, order_id: str) -> dict:
        return {"order_id": order_id, "raw": self.call("cancel", order_id=order_id)}

    def open_orders(self) -> list[dict]:
        if not self.tools.get("open_orders"):
            return []
        d = self.call("open_orders")
        rows = _dig(d, self.paths.get("open_orders", "")) if self.paths.get("open_orders") else d
        return rows if isinstance(rows, list) else []

    def probe(self) -> dict:
        """What the server offers: discovery, registration status, the tool list with input schemas. Nothing is traded."""
        rep: dict = {"url": self.url, "steps": []}
        try:
            disc = self.oauth.discover()
            rep["steps"].append({"discover": "ok", "authorization_server": bool(disc.get("authorization_server")), "protected_resource": bool(disc.get("protected_resource"))})
            self.asm = disc.get("authorization_server") or {}
            if not self.oauth.tok.get("client_id") and self.asm:
                self.oauth.register(self.asm)
                rep["steps"].append({"register": "ok"})
            if not self.oauth.tok.get("access_token"):
                rep["steps"].append({"login": "needed: run `python -m buildout broker login`"})
                return rep
            tools = self.list_tools()
            rep["tools"] = [{"name": t.get("name"), "description": (t.get("description") or "")[:200], "input": t.get("inputSchema")} for t in tools]
            rep["steps"].append({"tools/list": f"{len(tools)} tools"})
            missing = [r for r in ("account", "quotes", "place", "order") if not self.tools.get(r)]
            rep["configured"] = {k: v for k, v in self.tools.items()}
            rep["missing_roles"] = missing
        except Exception as exc:  # noqa: BLE001  the probe reports, it does not raise
            rep["steps"].append({"error": str(exc)})
        return rep


def _fill(tmpl, kw: dict):
    """A template with "{name}" placeholders: a string that is exactly one placeholder takes the value with its type;
    other strings have their placeholders substituted as text; dicts and lists are walked."""
    if isinstance(tmpl, dict):
        return {k: _fill(v, kw) for k, v in tmpl.items()}
    if isinstance(tmpl, list):
        return [_fill(v, kw) for v in tmpl]
    if isinstance(tmpl, str):
        m = tmpl.strip()
        if m.startswith("{") and m.endswith("}") and m[1:-1] in kw:
            return kw[m[1:-1]]
        out = tmpl
        for k, v in kw.items():
            out = out.replace("{" + k + "}", str(v))
        return out
    return tmpl


def validate_order(symbol, side, quantity, limit, client_id) -> tuple[str, str, float, float]:
    """The checks every broker makes before anything else (v0.42.3): a symbol, buy or sell, a finite positive quantity
    and limit, a client id."""
    import math
    sym = str(symbol or "").strip().upper()
    if not sym or not sym.replace(".", "").isalnum():
        raise ValueError(f"bad symbol {symbol!r}")
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be buy or sell, not {side!r}")
    try:
        q, lim = float(quantity), float(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("quantity and limit must be numbers") from exc
    if not (math.isfinite(q) and q > 0):
        raise ValueError(f"quantity must be a finite positive number, not {quantity!r}")
    if not (math.isfinite(lim) and lim > 0):
        raise ValueError(f"limit must be a finite positive price, not {limit!r}")
    if not str(client_id or "").strip():
        raise ValueError("a client id is required")
    return sym, side, q, lim


def _atomic_write_json(path: Path, obj) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with open(tmp, "w") as fh:
        fh.write(json.dumps(obj, indent=1, sort_keys=True))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _tool_payload(r: dict):
    """A tool result's structured content, else its first text block parsed as JSON, else the text."""
    if r.get("structuredContent") is not None:
        return r["structuredContent"]
    for c in r.get("content") or []:
        if c.get("type") == "text":
            try:
                return json.loads(c["text"])
            except (json.JSONDecodeError, TypeError):
                return {"text": c["text"]}
    return r


def _dig(d, path: str):
    """'a.b.0.c' into nested dicts and lists; '' returns d."""
    if not path:
        return d
    cur = d
    for part in str(path).split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


class OrderUnknown(RuntimeError):
    """An order whose outcome is not known. The trader records it as a failure and stops; nothing re-sends it."""


STATES = ("prepared", "submitting", "acknowledged", "partially_filled", "filled", "cancelled", "rejected", "unknown")


def _payload_hash(intent: dict) -> str:
    return hashlib.sha256(json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


class OrderJournal:
    """One JSON file of order intents per broker and account, under the trading state root (v0.42.3). Every write is
    atomic and taken under an exclusive lock, so two passes cannot both prepare the same client id."""

    def __init__(self, broker: str, account: str = "default", root: Path | None = None):
        from .execution import state_root
        self.path = (root or state_root()) / "trader" / f"orders_{broker}_{account}.json"
        self.lock = self.path.with_suffix(".lock")

    def _locked(self, fn):
        import fcntl
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.lock, "w") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            try:
                d = json.loads(self.path.read_text()) if self.path.exists() else {}
                out = fn(d)
                _atomic_write_json(self.path, d)
                return out
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    def all(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def get(self, client_id: str) -> dict | None:
        return self.all().get(client_id)

    def prepare(self, client_id: str, intent: dict) -> dict:
        def f(d):
            if client_id in d:
                raise ValueError(f"client id {client_id} is already journaled")
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            d[client_id] = {"client_id": client_id, **intent, "payload_hash": _payload_hash(intent), "state": "prepared", "created": now, "history": [["prepared", now]]}
            return d[client_id]
        return self._locked(f)

    def update(self, client_id: str, state: str, **fields) -> dict:
        if state not in STATES:
            raise ValueError(f"unknown order state {state!r}")

        def f(d):
            r = d[client_id]
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            r.update({k: v for k, v in fields.items() if v is not None})
            r["state"] = state
            r.setdefault("history", []).append([state, now])
            return dict(r)
        return self._locked(f)

    def unresolved(self) -> list[dict]:
        return [r for r in self.all().values() if r["state"] in ("prepared", "submitting", "unknown")]


def resolve(client_id: str, order_id: str | None = None, not_sent: bool = False, broker: str = "robinhood_mcp", account: str = "agentic") -> dict:
    """The person's answer for an unknown order: it was placed (with its order id), or it was not."""
    J = OrderJournal(broker, account)
    if J.get(client_id) is None:
        raise KeyError(client_id)
    if bool(order_id) == bool(not_sent):
        raise ValueError("give exactly one of order_id or not_sent")
    if order_id:
        return J.update(client_id, state="acknowledged", order_id=order_id, note="resolved by the person: placed")
    return J.update(client_id, state="rejected", note="resolved by the person: never reached the broker")


def load_broker_config(path: str | Path | None = None) -> dict:
    import tomllib
    p = Path(path) if path else PRIVATE / "broker.toml"
    if not p.exists():
        return {"url": ROBINHOOD_MCP, "tools": {}, "args": {}, "paths": {}}
    return tomllib.loads(p.read_text())


def broker_template() -> str:
    return f'''# Buildout broker map for Robinhood's Trading MCP. Fill [tools] from `python -m buildout broker probe`.
url = "{ROBINHOOD_MCP}"

[tools]                 # role = the server's tool name
# account = "get_account"
# positions = "get_positions"
# quotes = "get_quotes"           # or quote = "get_quote" for one symbol at a time
# review = "review_equity_order"
# place = "place_equity_order"
# order = "get_order"
# cancel = "cancel_order"
# open_orders = "get_open_orders"

[args]                  # argument templates per role; {{symbol}} {{side}} {{quantity}} {{limit}} {{client_id}} {{order_id}} {{symbols}} are filled in
# place = {{ symbol = "{{symbol}}", side = "{{side}}", quantity = "{{quantity}}", type = "limit", limit_price = "{{limit}}", time_in_force = "gfd" }}
# order = {{ order_id = "{{order_id}}" }}

[paths]                 # where each field sits in a tool's result (dot paths); defaults are symbol, quantity, equity, cash, bid, ask, last, id, state
# equity = "portfolio.equity"
# positions = "results"
'''
