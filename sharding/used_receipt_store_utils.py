import os

from ethereum import abi, utils, vm
from ethereum.transactions import Transaction
from viper import compiler

from sharding.validator_manager_utils import (GASPRICE, STARTGAS,
                                              call_msg, call_tx,
                                              get_tx_rawhash)

_urs_contracts = {}
_urs_ct = None
_urs_code = None
_urs_bytecode = None

def _setup_tx(shard_id):
    tx, addr, sender_addr = create_urs_tx(shard_id)
    _urs_contracts[shard_id] = {
        'tx': tx,
        'addr': addr,
        'sender_addr': sender_addr
    }


def get_urs_contract(shard_id):
    if shard_id not in _urs_contracts.keys():
        _setup_tx(shard_id)
    return _urs_contracts[shard_id]


def get_urs_ct(shard_id):
    global _urs_ct, _urs_code
    if not _urs_ct:
        _urs_ct = abi.ContractTranslator(
            compiler.mk_full_signature(get_urs_code(shard_id))
        )
    return _urs_ct


def get_urs_code(shard_id):
    global _urs_code
    if not _urs_code:
        mydir = os.path.dirname(__file__)
        urs_path = os.path.join(mydir, 'contracts/used_receipt_store.v.py')
        _urs_code = open(urs_path).read()
    return _urs_code


def get_urs_bytecode(shard_id):
    global _urs_bytecode
    if not _urs_bytecode:
        _urs_bytecode = compiler.compile(get_urs_code(shard_id))
    return _urs_bytecode


def create_urs_tx(shard_id, gasprice=GASPRICE):
    bytecode = get_urs_bytecode(shard_id)
    tx = Transaction(0 , gasprice, 2000000, to=b'', value = 0, data=bytecode)
    tx.v = 27
    tx.r = 10000
    tx.s = shard_id + 1
    tx_rawhash = get_tx_rawhash(tx)
    urs_sender_addr = utils.sha3(
        utils.ecrecover_to_pub(tx_rawhash, tx.v, tx.r, tx.s)
    )[-20:]
    urs_addr = utils.mk_contract_address(urs_sender_addr, 0)
    return tx, urs_addr, urs_sender_addr


def mk_initiating_txs_for_urs(sender_privkey, sender_starting_nonce, shard_id):
    tx = get_urs_contract(shard_id)['tx']
    tx_send_money_to_urs = Transaction(sender_starting_nonce, GASPRICE, 90000, tx.sender, tx.startgas * tx.gasprice + tx.value, '').sign(sender_privkey)
    return [tx_send_money_to_urs, tx]


def call_add_used_receipt(state, sender_privkey, value, shard_id, receipt_id):
    return call_tx(
        state, get_urs_ct(shard_id), 'add_used_receipt', [receipt_id],
        sender_privkey, get_urs_contract(shard_id)['addr'], value
    )


def call_get_used_receipts(state, shard_id, receipt_id):
    dummy_addr = b'\xff' * 20
    return bool(utils.big_endian_to_int(call_msg(
        state, get_urs_ct(shard_id), 'get_used_receipts', [receipt_id],
        dummy_addr, get_urs_contract(shard_id)['addr']
    )))