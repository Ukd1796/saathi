"""Thin client for the Bolna REST API (https://api.bolna.ai, bearer auth)."""

import httpx

from .config import BOLNA_API, BOLNA_API_KEY


class BolnaError(Exception):
    pass


def _request(method, path, **kwargs):
    if not BOLNA_API_KEY:
        raise BolnaError("BOLNA_API_KEY is not set on the backend")
    try:
        r = httpx.request(method, BOLNA_API + path, headers={"Authorization": f"Bearer {BOLNA_API_KEY}"},
                          timeout=30, **kwargs)
    except httpx.HTTPError as exc:
        raise BolnaError(f"Bolna unreachable: {exc}") from exc
    if r.status_code >= 400:
        raise BolnaError(f"Bolna {method} {path} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


def create_agent(config):
    return _request("POST", "/v2/agent", json=config)


def update_agent(agent_id, config):
    return _request("PUT", f"/v2/agent/{agent_id}", json=config)


def get_agent(agent_id):
    return _request("GET", f"/v2/agent/{agent_id}")


def create_dispositions(payload):
    return _request("POST", "/dispositions/bulk", json=payload)


def list_dispositions(agent_id):
    return _request("GET", "/dispositions/", params={"agent_id": agent_id})


def update_disposition(disposition_id, payload):
    return _request("PUT", f"/dispositions/{disposition_id}", json=payload)


def list_numbers():
    return _request("GET", "/phone-numbers/all")


def set_inbound(agent_id, phone_number_id):
    return _request("POST", "/inbound/setup", json={"agent_id": agent_id, "phone_number_id": phone_number_id})


def make_call(agent_id, to_number, user_data=None, from_number=None):
    body = {"agent_id": agent_id, "recipient_phone_number": to_number, "user_data": user_data or {}}
    if from_number:
        body["from_phone_number"] = from_number
    return _request("POST", "/call", json=body)
