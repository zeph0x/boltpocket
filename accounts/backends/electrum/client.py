"""
Electrum JSON-RPC client.
Centralizes RPC calls and wallet path — all tasks import from here.
"""

import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def electrum_command(command, params=None):
    """Execute an Electrum JSON-RPC command."""
    if params is None:
        params = {}
    payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": command,
        "params": params,
    }
    response = requests.post(settings.ELECTRUM_RPC_URL, json=payload)
    result = response.json()

    if "error" in result and result["error"] is not None:
        raise Exception(f"Electrum RPC error: {result['error']}")

    return result["result"]


def electrum_wallet_command(command, params=None):
    """Execute an Electrum JSON-RPC command. Wallet is loaded at daemon start."""
    if params is None:
        params = {}
    return electrum_command(command, params)


def getinfo():
    return electrum_command("getinfo")


def getbalance():
    return electrum_wallet_command("getbalance")


def get_unused_address():
    return electrum_wallet_command("getunusedaddress")


def create_new_address():
    return electrum_wallet_command("createnewaddress")


def lnpay(invoice, max_fee_msat=None):
    params = {"invoice": invoice}
    if max_fee_msat is not None:
        params["max_fee_msat"] = max_fee_msat
    return electrum_wallet_command("lnpay", params)


def list_requests():
    return electrum_wallet_command("list_requests")


def add_request(amount_btc, memo="", expiry=3600, lightning=True):
    """Create a payment request (supports both on-chain and LN)."""
    params = {
        "amount": str(amount_btc),
        "memo": memo,
        "expiry": expiry,
    }
    if lightning:
        params["lightning"] = True
    return electrum_wallet_command("add_request", params)


def paytomany(outputs):
    """Create, sign, and return a signed on-chain transaction with multiple outputs.
    outputs: list of [destination, amount_btc_string] pairs.
    """
    return electrum_wallet_command("paytomany", {
        "outputs": outputs,
    })


def broadcast(tx_hex):
    """Broadcast a signed transaction. Returns txid."""
    return electrum_wallet_command("broadcast", {"tx": tx_hex})


def get_tx_status(txid):
    """Get transaction status (confirmations, etc)."""
    return electrum_wallet_command("get_tx_status", {"txid": txid})


def lightning_history():
    """Get full lightning payment history."""
    return electrum_wallet_command("lightning_history")


def get_lightning_payment_status(payment_hash):
    """Check if a lightning payment succeeded by looking at payment history."""
    try:
        history = lightning_history()
        if isinstance(history, list):
            for payment in history:
                if payment.get('payment_hash') == payment_hash:
                    return payment
        elif isinstance(history, dict):
            for key, payment in history.items():
                if isinstance(payment, dict) and payment.get('payment_hash') == payment_hash:
                    return payment
    except Exception:
        pass
    return None
