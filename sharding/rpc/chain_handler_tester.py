from eth_tester.backends.pyevm.main import get_default_account_keys
from eth_tester.utils.accounts import generate_contract_address
import eth_utils
from viper import compiler

from chain_handler import (
    TesterChainHandler,
    RPCChainHandler,
)
from vmc_utils import (
    decode_contract_call_result,
    mk_contract_tx_obj,
)

keys = get_default_account_keys()

def test_contract(ChainHandlerClass):
    chain_handler = ChainHandlerClass()
    chain_handler.mine(1)
    code = """
num_test: public(num)

@public
def __init__():
    self.num_test = 42

@public
def update_num_test(_num_test: num):
    self.num_test = _num_test
"""
    bytecode = compiler.compile(code)
    abi = compiler.mk_full_signature(code)
    sender_addr = keys[0].public_key.to_checksum_address()
    print(chain_handler.get_nonce(sender_addr))
    contract_addr = eth_utils.address.to_checksum_address(
        generate_contract_address(sender_addr, chain_handler.get_nonce(sender_addr))
    )
    print("contract_addr={}".format(contract_addr))
    tx_hash = chain_handler.deploy_contract(bytecode, sender_addr)
    chain_handler.mine(1)
    print(tx_hash)
    assert contract_addr == chain_handler.get_transaction_receipt(tx_hash)['contract_address']
    tx_obj = mk_contract_tx_obj('get_num_test', [], contract_addr, abi, sender_addr, 0, 50000, 1)
    result = chain_handler.call(tx_obj)
    decoded_result = decode_contract_call_result('get_num_test', abi, result)
    assert decoded_result == 42
    # tx_hash = chain_handler.send_transaction(tx_obj)
    chain_handler.mine(1)

    tx_obj = mk_contract_tx_obj(
        'update_num_test',
        [4],
        contract_addr,
        abi,
        sender_addr,
        0,
        50000,
        1,
    )
    tx_hash = chain_handler.send_transaction(tx_obj)
    chain_handler.mine(1)

    tx_obj = mk_contract_tx_obj('get_num_test', [], contract_addr, abi, sender_addr, 0, 50000, 1)
    result = chain_handler.call(tx_obj)
    decoded_result = decode_contract_call_result('get_num_test', abi, result)
    assert decoded_result == 4

if __name__ == '__main__':
    # test_contract(RPCChainHandler)
    test_contract(TesterChainHandler)
